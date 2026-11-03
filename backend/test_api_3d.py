"""Tests of the Benchmark 3D endpoints, on the recorded run that ships with the repository (its CSV files are read, never regenerated)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import api_3d
import benchmark_3d as B3

SHIPPED = Path(api_3d.__file__).resolve().parent / "docs" / "results" / "benchmark_3d_2026-10-26"
RUN_ID = SHIPPED.name


@pytest.fixture()
def client():
    return TestClient(api.app)


@pytest.fixture()
def run(tmp_path, monkeypatch):
    """A private copy of the recorded run, so that a test can modify it."""
    target = tmp_path / RUN_ID
    shutil.copytree(SHIPPED, target)
    monkeypatch.setenv("BENCHMARK_3D_RUN_DIRS", str(target))
    return target


@pytest.fixture()
def shipped(monkeypatch):
    monkeypatch.setenv("BENCHMARK_3D_RUN_DIRS", str(SHIPPED))
    return SHIPPED


# --- runs ----------------------------------------------------------------------------------------


def test_no_run_is_reported_when_nothing_is_configured(client, monkeypatch):
    monkeypatch.delenv("BENCHMARK_3D_RUN_DIRS", raising=False)
    body = client.get("/api/3d/runs").json()
    assert body["configured"] is False and body["runs"] == []
    assert any("one patient" in c.lower() for c in body["caveats"])


def test_a_directory_without_metadata_is_not_a_run(client, tmp_path, monkeypatch):
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("BENCHMARK_3D_RUN_DIRS", str(tmp_path / "empty"))
    assert client.get("/api/3d/runs").json()["runs"] == []


def test_the_recorded_run_is_listed_with_its_provenance_and_a_verified_integrity(client, shipped):
    meta = json.loads((shipped / "run_metadata.json").read_text(encoding="utf-8"))
    entry = client.get("/api/3d/runs").json()["runs"][0]
    assert entry["id"] == RUN_ID and entry["integrity"]["status"] == "verified"
    assert entry["integrity"]["files_checked"] == len(meta["files_sha256"]) + len(meta["figures_sha256"]) and not entry["integrity"]["files_not_covered_by_metadata"]
    assert entry["tune_slices"] == meta["parameters"]["tune_slices"] and entry["test_slices"] == meta["parameters"]["test_slices"]
    assert entry["methods"] == list(B3.METHODS) and entry["noise_sigmas_hu"] == [10.0, 25.0, 50.0]
    assert "dirty" in entry["source_state"] and entry["git_commit"].endswith("+dirty")
    assert entry["noise_model"]["adjacent_slice_correlation"] == 0.0 and "independent" in entry["noise_model"]["kind"]
    assert entry["comparable_with_historical_results"] is False and "one patient" in entry["status"]
    assert sorted(entry["figures"]) == ["test_rmse.png", "tradeoff_curves.png"] and "benchmark_3d.py" in entry["source_files"]
    assert "test_per_run" not in entry["tables"] and "test_summary" in entry["tables"]


def test_a_modified_csv_is_reported_as_an_integrity_mismatch(client, run):
    path = run / "selected_parameters.csv"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    integrity = client.get("/api/3d/runs").json()["runs"][0]["integrity"]
    assert integrity["status"] == "mismatch" and "selected_parameters.csv" in integrity["mismatched"]


def test_a_modified_figure_and_a_missing_table_are_both_detected(client, run):
    (run / "test_rmse.png").write_bytes(b"not the recorded figure")
    (run / "tuning_grid.csv").unlink()
    integrity = client.get("/api/3d/runs").json()["runs"][0]["integrity"]
    assert integrity["status"] == "mismatch" and "test_rmse.png" in integrity["mismatched"] and "tuning_grid.csv" in integrity["missing"]


def test_a_correlated_noise_model_recorded_in_the_metadata_is_reported(client, run):
    meta = json.loads((run / "run_metadata.json").read_text(encoding="utf-8"))
    meta["parameters"]["noise_model"] = {"kind": "white inside a slice, correlated with the adjacent slice", "adjacent_slice_correlation": 0.3}
    (run / "run_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    assert client.get("/api/3d/runs").json()["runs"][0]["noise_model"]["adjacent_slice_correlation"] == 0.3


def test_unknown_runs_and_traversal_attempts_are_rejected(client, shipped):
    for run_id in ("other", "..", "..%2f..%2fetc", f"{RUN_ID}%2f..", "%2e%2e"):
        assert client.get(f"/api/3d/runs/{run_id}").status_code in (404, 422)


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_the_recorded_runs_are_read_only_over_http_and_stay_byte_for_byte_the_same(client, run, method):     # a private copy: the test can never damage the real run
    import hashlib

    def digest():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(run.iterdir()) if p.is_file()}

    before = digest()
    urls = ["/api/3d/runs", f"/api/3d/runs/{RUN_ID}", f"/api/3d/runs/{RUN_ID}/tables/test_summary", f"/api/3d/runs/{RUN_ID}/figures/test_rmse.png",
            f"/api/3d/runs/{RUN_ID}/interpretation"]
    for url in urls:
        response = getattr(client, method)(url, **({"json": {"x": 1}} if method != "delete" else {}))
        assert response.status_code == 405, (method, url, response.status_code)      # the endpoints answer reads only
    assert digest() == before


def test_the_run_detail_carries_the_recorded_metadata(client, shipped):
    body = client.get(f"/api/3d/runs/{RUN_ID}").json()
    assert body["summary"]["id"] == RUN_ID and body["metadata"]["parameters"]["bootstrap_seed"] == 12345
    assert body["metadata"]["input_series"]["dicom_instances"] == 100


# --- tables and figures --------------------------------------------------------------------------


def test_tables_are_served_filtered_and_equal_to_the_csv_files(client, shipped):
    body = client.get(f"/api/3d/runs/{RUN_ID}/tables/test_summary", params={"condition": "white_50HU", "mask": "main"}).json()
    csv = pd.read_csv(shipped / "test_summary.csv")
    expected = csv[(csv["condition"] == "white_50HU") & (csv["mask"] == "main")]
    assert body["n_rows"] == len(expected) == 4
    assert [r["method"] for r in body["rows"]] == list(expected["method"])
    assert [r["RMSE_HU_mean"] for r in body["rows"]] == pytest.approx(list(expected["RMSE_HU_mean"]))
    by_method = client.get(f"/api/3d/runs/{RUN_ID}/tables/test_summary", params={"method": B3.METHODS[2]}).json()
    assert {r["method"] for r in by_method["rows"]} == {B3.METHODS[2]}


def test_a_table_can_be_downloaded_as_csv_with_a_safe_file_name(client, shipped):
    response = client.get(f"/api/3d/runs/{RUN_ID}/tables/selected_parameters", params={"format": "csv"})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == f'attachment; filename="{RUN_ID}_selected_parameters.csv"'
    assert response.text.splitlines()[0] == "condition,method,params" and len(response.text.splitlines()) == 10


def test_unknown_and_internal_tables_are_not_served_and_a_large_answer_is_refused(client, shipped, monkeypatch):
    assert client.get(f"/api/3d/runs/{RUN_ID}/tables/test_per_run").status_code == 404          # 1,440 rows, an internal table
    assert client.get(f"/api/3d/runs/{RUN_ID}/tables/../run_metadata").status_code in (404, 422)
    assert client.get(f"/api/3d/runs/{RUN_ID}/tables/nothing").status_code == 404
    assert client.get(f"/api/3d/runs/{RUN_ID}/tables/test_summary", params={"format": "xml"}).status_code == 422
    monkeypatch.setattr(api_3d, "MAX_ROWS", 5)
    assert client.get(f"/api/3d/runs/{RUN_ID}/tables/tuning_grid").status_code == 413


def test_only_the_figures_named_by_the_metadata_are_served(client, shipped):
    ok = client.get(f"/api/3d/runs/{RUN_ID}/figures/tradeoff_curves.png")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png" and ok.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert ok.content == (shipped / "tradeoff_curves.png").read_bytes()
    for name in ("run_metadata.json", "test_summary.csv", "..%2frun_metadata.json", "%2e%2e%2frun_metadata.json", "nothing.png"):   # a literal '..' segment is normalised by the HTTP client itself
        assert client.get(f"/api/3d/runs/{RUN_ID}/figures/{name}").status_code in (404, 422), name


# --- interpretation ------------------------------------------------------------------------------


def _independent_slice_counts(shipped: Path, condition: str) -> tuple[int, int, int]:
    per_slice = pd.read_csv(shipped / "test_per_slice.csv")
    sub = per_slice[(per_slice["condition"] == condition) & (per_slice["mask"] == "main")]
    a = sub[sub["method"] == B3.METHODS[2]].set_index("slice")["RMSE_HU"]
    b = sub[sub["method"] == B3.METHODS[0]].set_index("slice")["RMSE_HU"]
    d = (a - b).tolist()
    return sum(x < -1e-6 for x in d), sum(x > 1e-6 for x in d), sum(abs(x) <= 1e-6 for x in d)


def test_the_interpretation_reports_the_recorded_mixed_sign_gain_at_50_hu_and_no_change_below(client, shipped):
    body = client.get(f"/api/3d/runs/{RUN_ID}/interpretation").json()
    by = {s["condition"]: s for s in body["statements"]}
    assert set(by) == {"white_10HU", "white_25HU", "white_50HU"} and body["mask"] == "main"
    for condition in ("white_10HU", "white_25HU"):
        assert by[condition]["kind"] == "identical" and by[condition]["slices_equal"] == 8 and by[condition]["slices_lower"] == 0 == by[condition]["slices_higher"]
    s = by["white_50HU"]
    assert (s["slices_lower"], s["slices_higher"], s["slices_equal"]) == _independent_slice_counts(shipped, "white_50HU") == (6, 2, 0)
    assert s["kind"] == "lower" and -0.12 < s["paired_difference_hu"] < -0.10 and s["ci_high"] < 0 and 0.4 < s["relative_percent"] < 0.6
    assert "this series only" in s["text"] and "lower in 6, higher in 2" in s["text"]
    summary = pd.read_csv(shipped / "test_summary.csv")
    row = summary[(summary["condition"] == "white_50HU") & (summary["mask"] == "main") & (summary["method"] == B3.BASELINE)].iloc[0]
    assert s["unfiltered_rmse_hu"] == pytest.approx(row["RMSE_HU_mean"])
    assert any("under-cover" in c for c in body["caveats"])


def _frames(mean: float, low: float, high: float, a: float = 7.0, b: float = 7.0):
    summary = pd.DataFrame([{"condition": "c", "mask": "main", "method": m, "RMSE_HU_mean": v} for m, v in
                            [(B3.BASELINE, 10.0), (B3.METHODS[0], b), (B3.METHODS[1], b), (B3.METHODS[2], a)]])
    pairwise = pd.DataFrame([{"condition": "c", "mask": "main", "metric": "RMSE_HU", "A": B3.METHODS[2], "B": B3.METHODS[0], "mean_A_minus_B": mean, "ci_low": low, "ci_high": high}])
    per_slice = pd.DataFrame([{"condition": "c", "mask": "main", "slice": s, "method": m, "RMSE_HU": v + (0.1 * s if m == B3.METHODS[2] else 0.0)}
                              for s in range(3) for m, v in [(B3.METHODS[0], 7.0), (B3.METHODS[2], 7.0)]])
    return summary, pairwise, per_slice


@pytest.mark.parametrize("mean, low, high, kind", [(-0.1, -0.2, -0.05, "lower"), (0.1, 0.05, 0.2, "higher"), (-0.1, -0.3, 0.2, "unresolved"), (0.0, 0.0, 0.0, "identical")])
def test_the_classification_of_a_paired_difference_follows_its_interval(mean, low, high, kind):
    assert api_3d.interpret(*_frames(mean, low, high))[0]["kind"] == kind


def test_a_condition_without_a_recorded_pair_is_reported_as_indeterminate():
    summary, pairwise, per_slice = _frames(-0.1, -0.2, -0.05)
    assert api_3d.interpret(summary, pairwise.iloc[0:0], per_slice)[0]["kind"] == "indeterminate"


def test_the_interpretation_never_claims_more_than_rmse_on_one_mask():
    summary, pairwise, per_slice = _frames(-0.1, -0.2, -0.05)
    text = api_3d.interpret(summary, pairwise, per_slice)[0]["text"]
    assert "RMSE_HU" in text and "this series only" in text
    for forbidden in ("better quality", "clinical", "diagnos", "superior", "generali"):
        assert forbidden not in text.lower()


def test_the_api_root_and_openapi_schema_list_the_3d_endpoints(client):
    assert client.get("/").json()["links"]["benchmark_3d_runs"] == "/api/3d/runs"
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/3d/runs", "/api/3d/runs/{run_id}", "/api/3d/runs/{run_id}/tables/{name}", "/api/3d/runs/{run_id}/figures/{name}", "/api/3d/runs/{run_id}/interpretation"} <= set(paths)
