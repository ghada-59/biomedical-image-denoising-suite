"""Tests for the added denoiser families of benchmark V2 (the ``methods`` grid) and for the run provenance records.

Expected values come from definitions, invariances or an independent recomputation, never from the
function under test alone.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from scipy import ndimage

import api
import api_v2
import benchmark_v2 as B
import filters as F
from test_benchmark_v2 import _write_dicom_series, phantom_volume

ADDED = tuple(B.ADVANCED_FAMILIES)
WHITE_25 = B.CONDITIONS[1]
SIZE = 64          # large enough for the three wavelet levels of sym4 (deepest level 3)


def small_run(volume, grid_version, conditions=(WHITE_25,)):
    config = B.Config(tune_slices=[6], test_slices=[11, 15], tune_repeats=1, test_repeats=2, n_boot=200, grid_version=grid_version)
    return config, B.run_benchmark(volume, config, conditions=conditions)


@pytest.fixture(scope="module")
def phantom():
    return phantom_volume(n=24, size=SIZE)


@pytest.fixture(scope="module")
def runs(phantom):
    """The same experiment under the expanded grid and the methods grid."""
    return {version: small_run(phantom, version) for version in ("expanded", "methods")}


# --- grids ------------------------------------------------------------------------------------


def test_the_methods_grid_is_the_expanded_grid_plus_the_three_added_families():
    expanded, methods = B.parameter_grid("expanded"), B.parameter_grid("methods")
    assert set(methods) == set(expanded) | set(ADDED) and set(methods) == set(B.ALL_FAMILIES)
    assert all(methods[family] == expanded[family] for family in expanded)
    assert not set(ADDED) & set(B.parameter_grid("v1")) and not set(ADDED) & set(expanded)


def test_the_default_grid_and_the_six_original_families_are_unchanged():
    assert B.FAMILIES == ("Mean", "Median", "Gaussian", "FFT ideal", "FFT Gaussian", "FFT Butterworth")
    assert set(B.parameter_grid()) == set(B.FAMILIES)
    with pytest.raises(ValueError):
        B.parameter_grid("nope")


@pytest.mark.parametrize("family", ADDED)
def test_each_added_grid_starts_with_the_identity_then_strictly_increases(family):
    configs = B.parameter_grid("methods")[family]
    key = B.ADVANCED_FAMILIES[family]
    assert configs[0][key] is None and B.is_identity(family, configs[0])
    strengths = [c[key] for c in configs[1:]]
    assert strengths == sorted(set(strengths)) and all(s > 0 for s in strengths)
    assert not any(B.is_identity(family, c) for c in configs[1:])
    assert [B.smoothing_strength(family, c) for c in configs] == [0.0, *map(float, strengths)]


@pytest.mark.parametrize("family", ADDED)
def test_the_fixed_hyperparameters_are_recorded_in_every_configuration(family):
    configs = B.parameter_grid("methods")[family]
    fixed = {k: {c[k] for c in configs} for k in configs[0] if k != B.ADVANCED_FAMILIES[family]}
    assert fixed and all(len(values) == 1 for values in fixed.values())
    assert json.loads(json.dumps(configs)) == configs                  # selected parameters survive a CSV/JSON round trip


# --- filtering in the HU domain -----------------------------------------------------------------


@pytest.fixture(scope="module")
def noisy_hu(phantom):
    case = B.make_case(phantom[11], WHITE_25, seed=5)
    return case.noisy_hu, case


@pytest.mark.parametrize("family", ADDED)
def test_identity_configurations_return_the_input_up_to_the_round_trip_rounding(family, noisy_hu):
    hu, _ = noisy_hu
    identity = B.parameter_grid("methods")[family][0]
    out = B.filter_hu(hu, family, identity)
    assert np.abs(out - hu).max() < 1e-9                                  # HU -> normalised -> HU round-off only (~1e-12 HU)
    np.testing.assert_array_equal(B.apply_filter(B.hu_to_unit(hu), family, identity), B.hu_to_unit(hu))


def test_hu_strengths_are_converted_to_the_normalised_scale_exactly_once(noisy_hu):
    hu, _ = noisy_hu
    unit, span = B.hu_to_unit(hu), 12288.0
    cases = {
        "Bilateral": ({"sigma_color_hu": 40.0, "sigma_space_px": 1.5}, lambda: F.bilateral_filter(unit, 40.0 / span, 1.5)),
        "Non-local means": ({"h_hu": 30.0, "patch_size": 5, "patch_distance": 6}, lambda: F.non_local_means_filter(unit, 30.0 / span, 5, 6)),
        "Wavelet BayesShrink": ({"sigma_hu": 50.0, "wavelet": "sym4", "levels": 3, "max_shifts": 3},
                                lambda: F.wavelet_shrinkage_filter(unit, 50.0 / span, "sym4", 3, 3)),
    }
    for family, (params, direct) in cases.items():
        np.testing.assert_allclose(B.filter_hu(hu, family, params), B.unit_to_hu(direct()), atol=1e-9)


@pytest.mark.parametrize("family", ADDED)
def test_the_result_does_not_depend_on_the_chosen_normalisation_range(family, noisy_hu, monkeypatch):
    # Strengths are in HU, so widening the (non-clipping) normalisation range must not change a filtered HU image.
    hu, _ = noisy_hu
    params = next(c for c in B.parameter_grid("methods")[family] if not B.is_identity(family, c) and c[B.ADVANCED_FAMILIES[family]] >= 25)
    reference = B.filter_hu(hu, family, params)
    monkeypatch.setattr(B, "NORMALISATION_RANGE_HU", (-8192.0, 16384.0))
    wider = B.filter_hu(hu, family, params)
    np.testing.assert_allclose(wider, reference, atol=0.05)             # float32 (bilateral) and round-off only, in HU


@pytest.mark.parametrize("family", ADDED)
@pytest.mark.parametrize("value", [-2048.0, -1000.0, 40.0, 3000.0])
def test_a_constant_hu_image_stays_constant_through_the_chain(family, value):
    params = next(c for c in B.parameter_grid("methods")[family] if c[B.ADVANCED_FAMILIES[family]] == 40 or c[B.ADVANCED_FAMILIES[family]] == 50)
    out = B.filter_hu(np.full((SIZE, SIZE), value), family, params)
    np.testing.assert_allclose(out, value, atol=0.05)


def test_unknown_families_and_missing_parameters_fail_loudly():
    with pytest.raises(ValueError):
        B.advanced_configs("Median")
    with pytest.raises(KeyError):
        B.apply_filter(np.full((SIZE, SIZE), 0.3), "Bilateral", {"sigma_space_px": 1.5})


# --- tuning and runs -----------------------------------------------------------------------------


@pytest.mark.parametrize("family", ["Non-local means", "Wavelet BayesShrink"])
def test_stronger_noise_selects_a_stronger_setting(family, phantom):
    selected = {}
    for condition in (B.CONDITIONS[0], B.CONDITIONS[2]):             # white 10 HU and white 50 HU
        cases = [B.make_case(phantom[6], condition, seed) for seed in (1, 2)]
        _, chosen = B.tune_condition(cases, condition, {family: B.parameter_grid("methods")[family]})
        selected[condition.name] = chosen[family][B.ADVANCED_FAMILIES[family]]
    assert selected["white_50HU"] is not None
    assert selected["white_10HU"] is None or selected["white_50HU"] > selected["white_10HU"]


def test_tuning_picks_the_lowest_error_and_never_looks_at_the_test_slices(phantom):
    cases = [B.make_case(phantom[6], WHITE_25, seed) for seed in (1, 2)]
    grid = {"Non-local means": B.parameter_grid("methods")["Non-local means"]}
    table, chosen = B.tune_condition(cases, WHITE_25, grid)
    best = table.loc[table["mean_score"].idxmin()]
    assert json.loads(best["params"]) == chosen["Non-local means"]
    assert table["n_tuning_cases"].eq(2).all() and len(table) == len(grid["Non-local means"])


def test_the_six_original_families_give_identical_results_inside_a_methods_run(runs):
    """The methods run extends the expanded run; it must not change anything for the families both contain."""
    (_, expanded), (_, methods) = runs["expanded"], runs["methods"]
    original = list(B.FAMILIES) + [B.BASELINE]
    for name in ("selected_parameters", "tuning_grid", "grid_bracketing", "tuning_criteria_comparison", "test_per_run", "test_per_slice", "test_summary"):
        subset = methods[name][methods[name]["family"].isin(original)].reset_index(drop=True)
        pd.testing.assert_frame_equal(subset, expanded[name].reset_index(drop=True), obj=name)
    pairs = methods["test_pairwise"]
    pairs = pairs[pairs["A"].isin(original) & pairs["B"].isin(original)].reset_index(drop=True)
    pd.testing.assert_frame_equal(pairs, expanded["test_pairwise"].reset_index(drop=True), obj="test_pairwise")


def test_a_methods_run_has_every_family_for_every_slice_and_mask(runs):
    config, tables = runs["methods"]
    per_run = tables["test_per_run"]
    assert set(per_run["family"]) == set(B.ALL_FAMILIES) | {B.BASELINE}
    assert len(per_run) == 1 * 2 * 2 * 10 * 2                                  # conditions x slices x repeats x (9 + baseline) x masks
    assert set(tables["selected_parameters"]["family"]) == set(B.ALL_FAMILIES)
    summary = tables["test_summary"]
    assert (summary.groupby(["condition", "mask"]).size() == 10).all()
    assert summary[["RMSE_HU_mean", "PSNR_dB_mean", "SSIM_Wang2004_mean"]].notna().all().all()


def test_a_methods_run_scores_all_outputs_of_a_case_on_the_same_noisy_input_and_mask(runs):
    config, tables = runs["methods"]
    per_run = tables["test_per_run"]
    for (_, _, _), group in per_run.groupby(["slice", "repeat", "mask"]):
        assert group["seed"].nunique() == 1 and group["mask_pixels"].nunique() == 1 and len(group) == 10


def test_added_families_lower_the_error_of_a_noisy_phantom_and_the_selected_parameters_are_valid(runs):
    _, tables = runs["methods"]
    summary = tables["test_summary"]
    main = summary[summary["mask"] == "main"].set_index("family")
    for family in ADDED:
        assert main.loc[family, "RMSE_HU_mean"] < main.loc[B.BASELINE, "RMSE_HU_mean"]
    for row in tables["selected_parameters"].itertuples():
        params = json.loads(row.params)
        assert B.is_identity(row.family, params) or params[B.ADVANCED_FAMILIES.get(row.family, "x")] > 0 if row.family in ADDED else True


def test_bracketing_of_the_added_families_uses_their_own_strength_order(runs):
    _, tables = runs["methods"]
    bracketing = tables["grid_bracketing"]
    added = bracketing[bracketing["family"].isin(ADDED)]
    assert set(added["status"]) <= {"identity", "interior", "weakest_end", "strongest_end"} and len(added) == 3
    for row in added.itertuples():
        assert row.grid_size == len(B.parameter_grid("methods")[row.family])
        assert row.bracketed == (row.status in ("identity", "interior"))


# --- the dashboard API on a methods run ------------------------------------------------------------------


@pytest.fixture()
def methods_run(runs, phantom, tmp_path, monkeypatch):
    config, tables = runs["methods"]
    out = tmp_path / "methods_run"
    metadata = {
        "schema_version": B.SCHEMA_VERSION, "generated_at": "2026-01-01T00:00:00+00:00", "git_commit": "abc123",
        "series_directory_name": "phantom", "limitations": "phantom run for tests",
        "parameters": {"conditions": [WHITE_25.__dict__], "tune_slices": config.tune_slices, "test_slices": config.test_slices,
                       "tune_repeats": 1, "test_repeats": 2, "tune_base_seed": config.tune_base_seed, "test_base_seed": config.test_base_seed,
                       "grid_version": "methods"},
    }
    B.write_outputs(tables, out, metadata)
    series = tmp_path / "series"
    series.mkdir()
    monkeypatch.setenv("BENCHMARK_RUN_DIRS", str(out))
    monkeypatch.setenv("CT_SERIES_DIR", str(series))
    monkeypatch.setattr(api_v2, "_volume", lambda *_: phantom)
    api_v2._case_bundle.cache_clear()
    return out


def test_the_slice_comparison_recomputes_every_family_and_matches_the_recorded_run(methods_run):
    client = TestClient(api.app)
    body = client.get("/api/v2/runs/methods_run/slice-comparison", params={"slice": 11, "condition": "white_25HU", "repeat": 1}).json()
    families = [o["family"] for o in body["outputs"]]
    assert families == [B.BASELINE, *B.ALL_FAMILIES]
    assert body["reproduces_recorded_run"] == {"compared": 10, "all_match": True}
    by_family = {o["family"]: o for o in body["outputs"]}
    for family in ADDED:
        assert by_family[family]["identity"] == B.is_identity(family, by_family[family]["params"])
        assert set(by_family[family]["params"]) >= {B.ADVANCED_FAMILIES[family]}


def test_the_images_and_interpretation_endpoints_serve_the_added_families(methods_run):
    client = TestClient(api.app)
    for family in ADDED:
        response = client.get("/api/v2/runs/methods_run/slice-image",
                              params={"slice": 11, "condition": "white_25HU", "repeat": 1, "view": f"filtered:{family}"})
        assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    statements = client.get("/api/v2/runs/methods_run/interpretation").json()["statements"]
    assert any(s["kind"] == "best_rmse" and s["best_family"] in B.ALL_FAMILIES for s in statements)
    summary = client.get("/api/v2/runs").json()["runs"][0]
    assert summary["grid_version"] == "methods"


# --- noise estimate of the reference -----------------------------------------------------------------------


@pytest.mark.parametrize("sigma", [5.0, 20.0, 45.0])
def test_the_noise_estimate_recovers_the_standard_deviation_of_white_noise(sigma):
    rng = np.random.default_rng(0)
    hu = 30.0 + rng.normal(0, sigma, (200, 200))
    estimate = B.estimate_noise_hu(hu, np.ones(hu.shape, dtype=bool))
    assert estimate == pytest.approx(sigma, rel=0.03)


def test_the_noise_estimate_ignores_sparse_structures():
    rng = np.random.default_rng(1)
    hu = 30.0 + rng.normal(0, 20.0, (200, 200))
    hu[::17, ::13] += 1000.0                                           # isolated bright spots
    hu[:, 100:102] += 300.0                                            # a thin line
    assert B.estimate_noise_hu(hu, np.ones(hu.shape, dtype=bool)) == pytest.approx(20.0, rel=0.08)


def test_the_noise_estimate_of_correlated_noise_is_below_its_standard_deviation():
    hu = 30.0 + B.hu_noise((200, 200), 20.0, "correlated", seed=3)
    estimate = B.estimate_noise_hu(hu, np.ones(hu.shape, dtype=bool))
    assert 0 < estimate < 20.0 * 0.8                                   # the stated limitation: it is a white-noise equivalent


def test_the_noise_estimate_needs_enough_pixels_and_valid_shapes():
    hu = np.zeros((30, 30))
    assert math.isnan(B.estimate_noise_hu(hu, np.ones((30, 30), dtype=bool)))              # 28 x 28 interior pixels < 1000
    assert not math.isnan(B.estimate_noise_hu(hu, np.ones((30, 30), dtype=bool), min_pixels=100))
    assert not math.isnan(B.estimate_noise_hu(np.zeros((40, 40)), np.ones((40, 40), dtype=bool)))   # 38 x 38 = 1444 interior pixels
    with pytest.raises(ValueError):
        B.estimate_noise_hu(hu, np.ones((10, 10), dtype=bool))
    with pytest.raises(ValueError):
        B.estimate_noise_hu(np.zeros(5), np.ones(5, dtype=bool))


def test_the_region_for_the_noise_estimate_is_interior_soft_tissue_only(phantom):
    hu = B.hu_noise((160, 160), 1.0, "white", seed=1) * 0 + phantom_volume(n=24, size=160)[11]
    region = B.soft_tissue_region(hu)
    assert region.any()
    assert (hu[region] >= 0).all() and (hu[region] <= 100).all()
    body = B.body_mask(hu)
    eroded_body_distance = ndimage.distance_transform_edt(body)
    assert (eroded_body_distance[region] > B.SOFT_TISSUE_EROSION_PX).all()
    lungs = hu < -400
    assert not (ndimage.binary_dilation(lungs, iterations=B.SOFT_TISSUE_EROSION_PX) & region).any()


def test_the_reference_noise_context_reports_each_slice_and_the_spread():
    volume = phantom_volume(n=24, size=160)
    context = B.reference_noise_context(volume, [11, 6, 11])
    assert [r["slice"] for r in context["per_slice"]] == [6, 11]
    values = [r["white_noise_equivalent_sd_hu"] for r in context["per_slice"]]
    assert all(v == pytest.approx(2.0, rel=0.1) for v in values)               # the phantom texture is white noise of 2 HU
    assert context["median_hu"] == pytest.approx(np.median(values)) and context["range_hu"] == [min(values), max(values)]
    assert "ADDED to this existing noise" in context["interpretation"]


def test_slices_without_enough_soft_tissue_are_reported_as_null_not_nan():
    volume = phantom_volume(n=24, size=64)                     # the 64 px phantom's soft tissue is too small for the estimate
    context = B.reference_noise_context(volume, [6, 11])
    assert [r["white_noise_equivalent_sd_hu"] for r in context["per_slice"]] == [None, None]
    assert context["median_hu"] is None and context["range_hu"] is None
    json.dumps(context, allow_nan=False)                      # must be strict JSON


def test_json_safe_replaces_nan_and_infinity_everywhere_and_keeps_everything_else():
    nested = {"a": float("nan"), "b": [1, float("inf"), (float("-inf"), "x")], "c": {"d": np.float64("nan"), "e": np.float32(1.5), "f": True, "g": None}}
    safe = B.json_safe(nested)
    assert safe == {"a": None, "b": [1, None, [None, "x"]], "c": {"d": None, "e": 1.5, "f": True, "g": None}}
    json.dumps(safe, allow_nan=False)


def test_written_metadata_is_strict_json_even_when_a_value_is_nan(tmp_path):
    tables = {"t": pd.DataFrame({"x": [1.0]})}
    B.write_outputs(tables, tmp_path, {"estimate": float("nan"), "values": [1.0, float("inf")]})
    text = (tmp_path / "run_metadata.json").read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text, parse_constant=lambda token: pytest.fail(f"non-standard JSON constant {token}"))["estimate"] is None


def test_the_pywavelets_version_comes_from_the_installed_distribution():
    from importlib.metadata import version

    assert B.package_versions()["pywavelets"] == version("PyWavelets")


# --- provenance records ------------------------------------------------------------------------------------


def test_source_file_hashes_identify_the_content_whatever_the_line_endings(tmp_path):
    (tmp_path / "a.py").write_bytes(b"print(1)\r\nprint(2)\r\n")              # a Windows checkout
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_bytes(b"\x00\x01")
    hashes = B.source_file_hashes(tmp_path, ("a.py", "sub/b.txt", "missing.py"))
    assert hashes == {"a.py": hashlib.sha256(b"print(1)\nprint(2)\n").hexdigest(), "sub/b.txt": hashlib.sha256(b"\x00\x01").hexdigest()}
    (tmp_path / "a.py").write_bytes(b"print(1)\nprint(2)\n")                    # a Linux checkout of the same commit
    assert B.source_file_hashes(tmp_path, ("a.py",))["a.py"] == hashes["a.py"]
    (tmp_path / "a.py").write_bytes(b"print(1)\nprint(3)\n")
    assert B.source_file_hashes(tmp_path, ("a.py",))["a.py"] != hashes["a.py"]


def test_the_real_source_files_are_all_hashed():
    from pathlib import Path

    hashes = B.source_file_hashes(Path(B.__file__).resolve().parent)
    assert set(hashes) == set(B.SOURCE_FILES) and all(len(h) == 64 for h in hashes.values())


def test_the_series_record_lists_the_uid_the_files_and_a_reproducible_manifest(tmp_path):
    series = _write_dicom_series(tmp_path / "series", phantom_volume(n=6, size=24))
    (series / "LICENSE").write_text("CC BY 3.0\n", encoding="utf-8")
    record = B.series_input_record(series)
    assert record["series_instance_uid"] == "1.2.826.0.1.3680043.8.498.555"
    assert record["dicom_instances"] == 6 and record["files_in_directory"] == 7
    expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in series.iterdir()}
    assert record["files_sha256"] == expected
    manifest = "".join(f"{expected[name]}  {name}\n" for name in sorted(expected))
    assert record["manifest_sha256"] == hashlib.sha256(manifest.encode()).hexdigest()
    assert B.series_input_record(series)["manifest_sha256"] == record["manifest_sha256"]
    assert "patient" not in json.dumps(record).lower()                      # no patient identifiers are recorded
    target = series / "s000.dcm"
    target.write_bytes(target.read_bytes()[:-1] + bytes([target.read_bytes()[-1] ^ 1]))
    assert B.series_input_record(series)["manifest_sha256"] != record["manifest_sha256"]


def test_the_command_line_run_with_the_methods_grid_records_the_full_provenance(tmp_path, capsys):
    series = _write_dicom_series(tmp_path / "series", phantom_volume(n=24, size=SIZE))
    out = tmp_path / "out"
    B.main(["--dicom-series", str(series), "--out", str(out), "--n-tune", "1", "--n-test", "3", "--min-gap", "2",
            "--tune-repeats", "1", "--test-repeats", "1", "--n-boot", "50", "--grid-version", "methods"])
    meta = json.loads((out / "run_metadata.json").read_text(encoding="utf-8"),
                      parse_constant=lambda token: pytest.fail(f"non-standard JSON constant {token} in run_metadata.json"))
    assert meta["parameters"]["grid_version"] == "methods"
    assert set(meta["parameters"]["grid"]) == set(B.ALL_FAMILIES)
    added = meta["protocol"]["added_denoisers"]
    assert set(ADDED) <= set(added) and "ASSUMED" in added["Wavelet BayesShrink"]["tuned"]
    assert "BM3D" in added["not_included"]
    from pathlib import Path

    backend = Path(B.__file__).resolve().parent
    assert meta["source_files_sha256"] == {name: B.sha256_lf_normalised(backend / name) for name in B.SOURCE_FILES}
    assert "CRLF" in meta["source_files_hash_rule"]
    assert meta["input_series"]["manifest_sha256"] == B.series_input_record(series)["manifest_sha256"]
    assert meta["input_series"]["dicom_instances"] == 24
    assert len(meta["reference_noise_context"]["per_slice"]) == 4              # 1 tuning + 3 test slices
    assert "pywavelets" in meta["packages"]
    summary = pd.read_csv(out / "test_summary.csv")
    assert set(summary["family"]) == set(B.ALL_FAMILIES) | {B.BASELINE}
    for name, digest in meta["files_sha256"].items():
        assert B.sha256_of(out / name) == digest
    capsys.readouterr()


def test_the_default_run_is_unchanged_and_does_not_mention_the_added_denoisers(tmp_path, capsys):
    series = _write_dicom_series(tmp_path / "series", phantom_volume(n=24, size=40))
    out = tmp_path / "out"
    B.main(["--dicom-series", str(series), "--out", str(out), "--n-tune", "1", "--n-test", "3", "--min-gap", "2",
            "--tune-repeats", "1", "--test-repeats", "1", "--n-boot", "50"])
    meta = json.loads((out / "run_metadata.json").read_text(encoding="utf-8"))
    assert "added_denoisers" not in meta["protocol"] and meta["parameters"]["grid_version"] == "expanded"
    assert set(pd.read_csv(out / "test_summary.csv")["family"]) == set(B.FAMILIES) | {B.BASELINE}
    capsys.readouterr()
