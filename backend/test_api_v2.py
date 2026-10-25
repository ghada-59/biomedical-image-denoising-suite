"""Tests of the benchmark V2 endpoints on a small real run computed from a synthetic phantom."""
from __future__ import annotations

import json
import shutil

import cv2
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import api_v2
import benchmark_v2 as B

CONDITIONS = (B.CONDITIONS[1], B.CONDITIONS[4], B.CONDITIONS[6])   # white 25 HU, correlated 25 HU, salt & pepper
TUNE, TEST = [6], [11, 15]


def phantom_volume(n: int = 24, size: int = 48) -> np.ndarray:
    """Air outside, a soft-tissue disc with two lung discs, a bone block and an unsupported-by-padding rim."""
    yy, xx = np.mgrid[0:size, 0:size]
    c = size / 2
    body = np.hypot(yy - c, xx - c) < size * 0.42
    volume = np.full((n, size, size), -1000.0)
    texture = np.random.default_rng(0).normal(0, 2.0, size=(n, size, size))
    for s in range(n):
        volume[s][body] = 20.0
        if 4 <= s < 20:
            for dx in (-size * 0.18, size * 0.18):
                volume[s][np.hypot(yy - c, xx - (c + dx)) < size * 0.12] = -800.0
        volume[s][int(size * 0.20):int(size * 0.28), int(size * 0.40):int(size * 0.60)] = 600.0
        volume[s] += texture[s]
        volume[s, 0, 0] = -1000.0 - s
    return volume


@pytest.fixture(scope="module")
def run_source(tmp_path_factory):
    """A complete run produced by the benchmark code itself (small grid of slices, two conditions' worth of repeats)."""
    volume = phantom_volume()
    config = B.Config(tune_slices=TUNE, test_slices=TEST, tune_repeats=1, test_repeats=2, n_boot=200)
    tables = B.run_benchmark(volume, config, conditions=CONDITIONS)
    out = tmp_path_factory.mktemp("runs") / "phantom_run"
    metadata = {
        "schema_version": B.SCHEMA_VERSION, "generated_at": "2026-01-01T00:00:00+00:00", "git_commit": "abc123+dirty",
        "series_directory_name": "phantom", "limitations": "phantom run for tests",
        "parameters": {"conditions": [c.__dict__ for c in CONDITIONS], "tune_slices": TUNE, "test_slices": TEST, "tune_repeats": 1,
                       "test_repeats": 2, "tune_base_seed": config.tune_base_seed, "test_base_seed": config.test_base_seed,
                       "grid_version": "expanded"},
    }
    B.write_outputs(tables, out, metadata)
    return out, volume


@pytest.fixture()
def run(run_source, tmp_path, monkeypatch):
    source, volume = run_source
    target = tmp_path / "phantom_run"
    shutil.copytree(source, target)
    series = tmp_path / "series"
    series.mkdir()
    monkeypatch.setenv("BENCHMARK_RUN_DIRS", str(target))
    monkeypatch.setenv("CT_SERIES_DIR", str(series))
    monkeypatch.setattr(api_v2, "_volume", lambda *_: volume)
    api_v2._case_bundle.cache_clear()
    return target


@pytest.fixture()
def client():
    return TestClient(api.app)


# --- runs ------------------------------------------------------------------------------------


def test_no_run_is_reported_when_nothing_is_configured(client, monkeypatch):
    monkeypatch.delenv("BENCHMARK_RUN_DIRS", raising=False)
    body = client.get("/api/v2/runs").json()
    assert body["configured"] is False and body["runs"] == []
    assert any("one patient" in c.lower() for c in body["caveats"])


def test_a_directory_without_metadata_is_not_a_run(client, tmp_path, monkeypatch):
    (tmp_path / "empty_run").mkdir()
    monkeypatch.setenv("BENCHMARK_RUN_DIRS", str(tmp_path / "empty_run"))
    assert client.get("/api/v2/runs").json()["runs"] == []


def test_run_listing_reports_provenance_and_integrity(client, run):
    entry = client.get("/api/v2/runs").json()["runs"][0]
    assert entry["id"] == "phantom_run" and entry["integrity"]["status"] == "verified"
    assert entry["source_state"] == "uncommitted working tree (dirty)"
    assert entry["tune_slices"] == TUNE and entry["test_slices"] == TEST
    assert entry["comparable_with_historical_results"] is False
    assert "test_summary" in entry["tables"] and "test_per_run" not in entry["tables"]


def test_a_modified_csv_is_reported_as_an_integrity_mismatch(client, run):
    path = run / "selected_parameters.csv"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    integrity = client.get("/api/v2/runs").json()["runs"][0]["integrity"]
    assert integrity["status"] == "mismatch" and "selected_parameters.csv" in integrity["mismatched"]


def test_unknown_runs_and_traversal_attempts_are_rejected(client, run):
    for run_id in ("other", "..", "..%2f..%2fetc", "phantom_run%2f..", "%2e%2e"):
        assert client.get(f"/api/v2/runs/{run_id}").status_code in (404, 422)
    assert client.get("/api/v2/runs/phantom_run").status_code == 200


# --- tables ----------------------------------------------------------------------------------


def test_table_filters_and_json_safety(client, run):
    body = client.get("/api/v2/runs/phantom_run/tables/test_summary", params={"condition": "white_25HU", "mask": "main"}).json()
    assert body["n_rows"] == 7 and {r["condition"] for r in body["rows"]} == {"white_25HU"}
    baseline = next(r for r in body["rows"] if r["family"] == B.BASELINE)
    assert baseline["RMSE_HU_gain_mean"] is None            # NaN is serialised as null, never as the string "NaN"


def test_table_csv_export_is_named_and_filtered(client, run):
    response = client.get("/api/v2/runs/phantom_run/tables/selected_parameters", params={"format": "csv", "condition": "white_25HU"})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert 'filename="phantom_run_selected_parameters.csv"' in response.headers["content-disposition"]
    frame = pd.read_csv(pd.io.common.StringIO(response.text))
    assert set(frame["condition"]) == {"white_25HU"} and len(frame) == 6


def test_only_whitelisted_tables_are_served(client, run):
    for name in ("test_per_run", "run_metadata", "..%2frun_metadata", "nonexistent"):
        assert client.get(f"/api/v2/runs/phantom_run/tables/{name}").status_code == 404
    assert client.get("/api/v2/runs/phantom_run/tables/test_summary", params={"format": "xml"}).status_code == 422


# --- interpretation --------------------------------------------------------------------------


def _summary(rows):
    return pd.DataFrame(rows)


def _row(family, rmse, gain=(np.nan, np.nan, np.nan), mask="main", n=8):
    return {"condition": "c", "mask": mask, "family": family, "n_slices": n, "RMSE_HU_mean": rmse,
            "RMSE_HU_gain_mean": gain[0], "RMSE_HU_gain_ci_low": gain[1], "RMSE_HU_gain_ci_high": gain[2]}


def test_interpretation_identifies_the_lowest_rmse_and_its_change_against_the_unfiltered_image():
    statements = api_v2.interpret(_summary([_row(B.BASELINE, 25.0), _row("Mean", 20.0, (-5.0, -6.0, -4.0)), _row("Median", 22.0, (-3.0, -4.0, -2.0))]))
    best = statements[0]
    assert best["best_family"] == "Mean" and best["change_vs_unfiltered"] == "lower" and best["unfiltered_rmse_hu"] == 25.0
    assert "entirely below zero" in best["text"] and "only" in best["text"]


@pytest.mark.parametrize("gain, expected", [((0.0, 0.0, 0.0), "identical"), ((1e-13, -1e-13, 2e-13), "identical"), ((3.0, 1.0, 5.0), "higher"),
                                            ((-1.0, -3.0, 2.0), "unresolved")])
def test_interpretation_classifies_the_change_with_a_materiality_tolerance(gain, expected):
    statements = api_v2.interpret(_summary([_row(B.BASELINE, 25.0), _row("Mean", 24.0, gain)]))
    assert statements[0]["change_vs_unfiltered"] == expected


def test_interpretation_reports_mask_dependence_and_is_indeterminate_without_values():
    rows = [_row(B.BASELINE, 25.0), _row("Mean", 20.0), _row("Median", 22.0),
            _row(B.BASELINE, 25.0, mask="inner"), _row("Mean", 23.0, mask="inner"), _row("Median", 21.0, mask="inner")]
    kinds = {s["kind"]: s for s in api_v2.interpret(_summary(rows))}
    assert kinds["mask_dependent"]["main"] == "Mean" and kinds["mask_dependent"]["inner"] == "Median"
    missing = api_v2.interpret(_summary([_row(B.BASELINE, 25.0), _row("Mean", np.nan)]))
    assert missing[0]["kind"] == "indeterminate"


def test_interpretation_endpoint_matches_the_tables(client, run):
    statements = client.get("/api/v2/runs/phantom_run/interpretation").json()["statements"]
    summary = pd.read_csv(run / "test_summary.csv")
    filters = summary[summary.family != B.BASELINE]
    for s in (s for s in statements if s["kind"] == "best_rmse"):
        group = filters[(filters.condition == s["condition"]) & (filters["mask"] == s["mask"])]
        assert s["best_family"] == group.loc[group.RMSE_HU_mean.idxmin(), "family"]


# --- slice comparison ------------------------------------------------------------------------


def _compare(client, **params):
    base = {"slice": 11, "condition": "white_25HU", "repeat": 1}
    return client.get("/api/v2/runs/phantom_run/slice-comparison", params={**base, **params})


def test_a_test_slice_reproduces_the_recorded_run_exactly(client, run):
    body = _compare(client).json()
    assert body["role"] == "test" and body["reproduces_recorded_run"] == {"compared": 7, "all_match": True}
    assert [o["family"] for o in body["outputs"]][0] == B.BASELINE and len(body["outputs"]) == 7
    assert body["boundary_band_px"] == 3 and 0 < body["band_fraction_of_mask"] < 1
    assert all(len(v) == body["shape"][1] for v in body["profile"]["series"].values())


def test_a_tuning_slice_is_labelled_and_has_no_recorded_values_to_compare(client, run):
    body = _compare(client, slice=6).json()
    assert body["role"] == "tuning" and body["reproduces_recorded_run"] is None


def test_identity_selections_return_the_unfiltered_values(client, run):
    body = _compare(client).json()
    baseline = body["outputs"][0]["metrics"]["main"]["RMSE_HU"]
    for output in body["outputs"]:
        if output["identity"]:
            assert output["metrics"]["main"]["RMSE_HU"] == pytest.approx(baseline, abs=1e-6)


@pytest.mark.parametrize("params", [{"slice": 3}, {"condition": "nope"}, {"repeat": 3}, {"repeat": 0}, {"row": 99999}, {"slice": -1}])
def test_invalid_slice_comparison_requests_are_rejected(client, run, params):
    assert _compare(client, **params).status_code == 422


def test_comparison_needs_a_configured_series(client, run, monkeypatch):
    monkeypatch.delenv("CT_SERIES_DIR")
    api_v2._case_bundle.cache_clear()
    response = _compare(client)
    assert response.status_code == 503 and "No CT series" in response.json()["detail"]


def _image(client, **params):
    base = {"slice": 11, "condition": "white_25HU", "repeat": 1, "view": "noisy"}
    return client.get("/api/v2/runs/phantom_run/slice-image", params={**base, **params})


def _decode(response):
    return cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_UNCHANGED)


def test_images_are_png_with_the_image_size_and_respect_the_window(client, run):
    reference = _decode(_image(client, view="reference"))
    assert reference.shape == (48, 48) and reference.dtype == np.uint8
    wide = _decode(_image(client, view="reference", window_center=0, window_width=4000))
    assert wide.mean() != reference.mean()
    assert _image(client, view="reference").headers["content-type"] == "image/png"


def test_difference_maps_are_mid_gray_where_the_output_equals_the_reference(client, run):
    selected = pd.read_csv(run / "selected_parameters.csv")
    gray = _decode(_image(client, view="diff:Mean", diff_range_hu=100))
    row = selected[(selected.condition == "white_25HU") & (selected.family == "Mean")].iloc[0]
    assert gray.shape == (48, 48)
    assert np.abs(gray.astype(int) - 128).mean() < 60          # error of ~25 HU against a +-100 HU scale stays near mid-gray
    assert json.loads(row["params"])


def test_overlay_draws_the_mask_boundary_in_colour(client, run):
    plain, overlaid = _decode(_image(client, view="reference")), _decode(_image(client, view="reference", overlay="inner"))
    assert overlaid.ndim == 3 and overlaid.shape[:2] == plain.shape
    red = (overlaid[..., 2] == 230) & (overlaid[..., 1] == 60) & (overlaid[..., 0] == 60)
    assert red.any()


@pytest.mark.parametrize("params", [{"view": "bad"}, {"view": "filtered:Nope"}, {"view": "diff:"}, {"window_width": 0},
                                    {"window_center": 99999}, {"diff_range_hu": 0}, {"overlay": "other"}])
def test_invalid_image_requests_are_rejected(client, run, params):
    assert _image(client, **params).status_code == 422


def test_boundary_split_partitions_the_mask():
    mask = np.zeros((40, 40), bool)
    mask[5:35, 5:35] = True
    core, band = api_v2._boundary_split(mask, band_px=3)
    assert not (core & band).any() and (core | band).sum() == mask.sum()
    assert band.sum() > 0 and core.sum() > 0 and band[5, 5] and not core[5, 5]


def test_error_responses_do_not_reveal_server_paths(client, run, tmp_path):
    for response in (client.get("/api/v2/runs/missing"), _compare(client, slice=3)):
        assert str(tmp_path) not in response.text and "Traceback" not in response.text


def test_the_api_can_be_imported_without_matplotlib():
    """The hosted API installs requirements-api.txt, which has no matplotlib; importing it must not need it."""
    import subprocess
    import sys
    from pathlib import Path

    folder = str(Path(api.__file__).resolve().parent)
    code = ("import sys; sys.dont_write_bytecode = True; sys.path.insert(0, sys.argv[1]); "
            "sys.modules['matplotlib'] = None; sys.modules['matplotlib.pyplot'] = None; import api; print('imported')")
    result = subprocess.run([sys.executable, "-c", code, folder], capture_output=True, text=True)
    assert result.returncode == 0 and "imported" in result.stdout, result.stderr[-500:]


def test_a_run_whose_metadata_contains_nan_is_still_served_as_valid_json(client, run):
    path = run / "run_metadata.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["reference_noise_context"] = {"per_slice": [{"slice": 1, "white_noise_equivalent_sd_hu": float("nan")}]}
    path.write_text(json.dumps(document), encoding="utf-8")                          # Python writes the token NaN here
    assert "NaN" in path.read_text(encoding="utf-8")
    response = client.get("/api/v2/runs/phantom_run")
    assert response.status_code == 200
    assert response.json()["metadata"]["reference_noise_context"]["per_slice"][0]["white_noise_equivalent_sd_hu"] is None


def test_a_relative_run_directory_means_relative_to_backend_whatever_the_working_directory(monkeypatch, tmp_path):
    from pathlib import Path

    runs = Path(api_v2.__file__).resolve().parent / "docs" / "results"
    shipped = sorted(p.name for p in runs.glob("benchmark_v2_*") if (p / "run_metadata.json").is_file())
    assert shipped
    monkeypatch.chdir(tmp_path)                                   # not backend/
    monkeypatch.setenv("BENCHMARK_RUN_DIRS", "docs/results/" + shipped[0])
    assert list(api_v2.configured_runs()) == [shipped[0]]
