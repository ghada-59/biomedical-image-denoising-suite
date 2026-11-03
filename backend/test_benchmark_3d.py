"""Tests of benchmark 3D (benchmark_3d.py): geometry of the filters, the field-of-view handling, the error decomposition, the protocol,
and two synthetic volumes whose right answer is known in advance (one where smoothing across slices must help, one where it must hurt)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import benchmark_3d as b3
import benchmark_v2 as b2

SPACING = (0.7, 0.7, 3.0)
PADDING = -2048.0


def phantom(z_mode: str, slices: int = 45, size: int = 128) -> np.ndarray:
    """A body disc with a lung-like hole inside a circular field of view; padding (-2048 HU) outside.

    ``same``: every slice identical (the third dimension carries no information, so averaging slices must help).
    ``alternating``: the body alternates by +-150 HU from slice to slice (averaging across slices costs structure).
    """
    yy, xx = np.mgrid[0:size, 0:size]
    centre = size / 2 - 0.5
    radius = np.hypot(yy - centre, xx - centre)
    one = np.full((size, size), -1000.0)
    one[radius < 40] = 40.0
    one[np.hypot(yy - centre, xx - centre - 12) < 20] = -800.0
    one[radius >= 62] = PADDING
    volume = np.repeat(one[None], slices, axis=0)
    if z_mode == "alternating":
        for z in range(slices):
            volume[z][(radius < 40) & (volume[z] > -500)] += 150.0 if z % 2 else -150.0
    return volume


# --- geometry and filters -------------------------------------------------------------------------------


def test_sigma_in_millimetres_becomes_voxels_per_axis_with_the_physical_spacing():
    assert b3.sigma_voxels(1.0, 1.5, (0.5, 0.8, 3.0)) == pytest.approx((0.5, 1.25, 2.0))
    with pytest.raises(ValueError):
        b3.sigma_voxels(1.0, 1.0, (0.5, 0.0, 3.0))
    with pytest.raises(ValueError):
        b3.sigma_voxels(-1.0, 1.0, (0.5, 0.5, 3.0))


def test_a_sigma_of_zero_leaves_that_axis_untouched():
    volume = np.random.default_rng(0).normal(size=(9, 12, 12))
    only_in_plane = b3.smooth(volume, {"sigma_xy_mm": 1.4, "sigma_z_mm": 0.0}, (0.7, 0.7, 3.0))
    per_slice = np.stack([b3.ndimage.gaussian_filter(s, sigma=2.0, mode="reflect") for s in volume])   # 1.4 mm / 0.7 mm = 2 px
    assert np.allclose(only_in_plane, per_slice, atol=1e-12)
    assert np.array_equal(b3.smooth(volume, {"sigma_xy_mm": 0.0, "sigma_z_mm": 0.0}, SPACING), volume)   # both sigmas 0: the identity


def test_a_kernel_that_reaches_beyond_the_slab_is_refused():
    with pytest.raises(ValueError, match="HALF_SLAB"):
        b3.smooth(np.zeros((5, 8, 8)), {"sigma_xy_mm": 1.0, "sigma_z_mm": 7.0}, (0.7, 0.7, 3.0))   # reach 4 * 2.33 slices = 9 > 8


@pytest.mark.parametrize("index", [0, 3, 14, 29])
@pytest.mark.parametrize("with_valid", [False, True])
def test_smoothing_the_slab_equals_smoothing_the_whole_volume_at_its_centre(index, with_valid):
    volume = np.random.default_rng(1).normal(size=(30, 12, 12))
    valid = None
    if with_valid:
        valid = np.ones(volume.shape, bool)
        valid[:, :, :3] = False
    params = {"sigma_xy_mm": 1.1, "sigma_z_mm": 6.0}      # the widest z kernel of the grid: radius exactly HALF_SLAB
    whole = b3.smooth(volume, params, SPACING, valid)[index]
    slab, centre = b3.extract_slab(volume, index)
    slab_valid = None if valid is None else valid[max(0, index - b3.HALF_SLAB):index + b3.HALF_SLAB + 1]
    assert np.allclose(b3.smooth(slab, params, SPACING, slab_valid)[centre], whole, atol=1e-10)


def test_every_grid_point_stays_inside_the_slab():
    for configs in b3.method_grid().values():
        for params in configs:
            assert b3.kernel_radius(b3.sigma_voxels(params["sigma_xy_mm"], params["sigma_z_mm"], (0.54, 0.54, 3.0))[0]) <= b3.HALF_SLAB


def test_the_anisotropic_family_contains_the_slice_wise_family_and_the_identity():
    grid = b3.method_grid()
    two_d = {(p["sigma_xy_mm"], p["sigma_z_mm"]) for p in grid[b3.METHODS[0]]}
    aniso = {(p["sigma_xy_mm"], p["sigma_z_mm"]) for p in grid[b3.METHODS[2]]}
    assert two_d <= aniso and all(z == 0.0 for _, z in two_d) and (0.0, 0.0) in two_d


# --- the padding outside the field of view -------------------------------------------------------------


def test_padding_does_not_leak_into_the_body_with_normalised_convolution_but_does_without_it():
    volume = np.full((9, 40, 40), PADDING)
    volume[:, 10:30, 10:30] = 50.0                                   # a body that touches the padding
    valid = volume > b2.PADDING_HU
    params = {"sigma_xy_mm": 1.4, "sigma_z_mm": 3.0}
    with_valid = b3.smooth(volume, params, SPACING, valid)
    plain = b3.smooth(volume, params, SPACING)
    assert np.allclose(with_valid[valid], 50.0, atol=1e-9)           # a constant body stays constant, edge included
    assert np.abs(plain[valid] - 50.0).max() > 400.0                 # plain smoothing drags the -2048 into the body edge


def test_the_filter_with_a_field_of_view_is_still_linear():
    rng = np.random.default_rng(4)
    valid = np.ones((9, 24, 24), bool)
    valid[:, :, :5] = False
    a, b = rng.normal(size=valid.shape) * 100, rng.normal(size=valid.shape) * 30
    params = {"sigma_xy_mm": 1.1, "sigma_z_mm": 3.0}
    assert np.allclose(b3.smooth(a + b, params, SPACING, valid), b3.smooth(a, params, SPACING, valid) + b3.smooth(b, params, SPACING, valid), atol=1e-9)


def test_the_field_of_view_normalisation_also_holds_along_z_when_one_slice_has_a_different_valid_region():
    volume = np.full((9, 30, 30), 50.0)
    valid = np.ones(volume.shape, bool)
    valid[4] = False                                                 # one slice entirely outside the field of view
    volume[4] = PADDING
    out = b3.smooth(volume, {"sigma_xy_mm": 1.0, "sigma_z_mm": 3.0}, SPACING, valid)
    assert np.allclose(out[valid], 50.0, atol=1e-9)                  # the neighbours of that slice must not be pulled towards 0 or towards -2048


# --- the error decomposition ----------------------------------------------------------------------------


def test_a_linear_filter_splits_into_the_filtered_reference_and_the_filtered_noise():
    rng = np.random.default_rng(2)
    reference, noise = rng.normal(size=(9, 16, 16)) * 100, rng.normal(size=(9, 16, 16)) * 25
    params = {"sigma_xy_mm": 1.1, "sigma_z_mm": 3.0}
    assert np.allclose(b3.smooth(reference + noise, params, SPACING), b3.smooth(reference, params, SPACING) + b3.smooth(noise, params, SPACING), atol=1e-9)


def test_rmse_squared_is_blur_squared_plus_residual_squared_plus_the_cross_term_exactly():
    rng = np.random.default_rng(3)
    reference = rng.normal(size=(40, 40)) * 100
    mask = np.zeros((40, 40), bool)
    mask[5:35, 5:35] = True
    filtered_reference = reference * 0.8 + 3.0
    filtered_noisy = filtered_reference + rng.normal(size=(40, 40)) * 12
    parts = b3.tradeoff(reference, filtered_reference, filtered_noisy, mask)
    total = b3.rms((filtered_noisy - reference)[mask])
    assert total**2 == pytest.approx(parts["blur_rmse_hu"] ** 2 + parts["residual_noise_hu"] ** 2 + parts["cross_term_hu2"], rel=1e-12)


def test_the_noise_left_by_a_gaussian_matches_the_theoretical_gain():
    params = {"sigma_xy_mm": 1.4, "sigma_z_mm": 3.0}
    impulse = np.zeros((17, 41, 41))
    impulse[8, 20, 20] = 1.0
    gain = np.sqrt((b3.smooth(impulse, params, SPACING) ** 2).sum())      # white noise of unit sigma keeps this standard deviation
    noise = b3.white_noise((17, 96, 96), 20.0, seed=5)
    measured = b3.rms(b3.smooth(noise, params, SPACING)[8, 24:72, 24:72])
    assert measured == pytest.approx(20.0 * gain, rel=0.04)


def test_white_noise_is_reproducible_and_has_the_requested_sigma():
    a, b = b3.white_noise((4, 64, 64), 25.0, 7), b3.white_noise((4, 64, 64), 25.0, 7)
    assert np.array_equal(a, b) and not np.array_equal(a, b3.white_noise((4, 64, 64), 25.0, 8))
    assert a.std() == pytest.approx(25.0, rel=0.03) and abs(a.mean()) < 0.5


def test_the_regions_come_from_the_reference_and_the_soft_region_lies_inside_the_body():
    masks = b3.region_masks(phantom("same")[10])
    assert set(masks) == {"main", "inner", "soft"} and masks["soft"].sum() >= b3.MIN_SOFT_PIXELS
    assert not (masks["soft"] & ~masks["main"]).any() and not (masks["inner"] & ~masks["main"]).any()


# --- the protocol on volumes with a known answer --------------------------------------------------------


@pytest.fixture(scope="module")
def runs():
    results = {}
    for mode in ("same", "alternating"):
        volume = phantom(mode)
        tune_slices, test_slices = b3.plan_slices(volume, n_tune=3, n_test=4)
        tables = b3.run(volume, SPACING, tune_slices, test_slices, tune_repeats=1, test_repeats=2, n_boot=200)
        results[mode] = (volume, tune_slices, test_slices, tables)
    return results


def _selected_sigma_z(tables, method):
    selected = tables["selected_parameters"]
    return selected[selected["method"] == method]["params"].map(lambda p: json.loads(p)["sigma_z_mm"])


def test_tuning_and_test_slices_are_disjoint_and_a_slab_apart(runs):
    for _volume, tune_slices, test_slices, tables in runs.values():
        assert not set(tune_slices) & set(test_slices)
        assert min(abs(a - b) for a in tune_slices for b in test_slices) >= b3.HALF_SLAB
        assert set(tables["test_per_run"]["slice"]) == set(test_slices)
        assert set(tables["tuning_grid"].columns) >= {"condition", "method", "params", "RMSE_HU_main", "blur_rmse_hu_soft", "residual_noise_hu_soft"}


def test_when_the_third_dimension_adds_nothing_smoothing_across_slices_wins_and_is_selected(runs):
    _volume, _tune, _test, tables = runs["same"]
    assert (_selected_sigma_z(tables, b3.METHODS[2]) > 0).all()
    summary = tables["test_summary"]
    for condition in ("white_25HU", "white_50HU"):
        rows = summary[(summary["condition"] == condition) & (summary["mask"] == b3.PRIMARY_MASK)].set_index("method")
        assert rows.loc[b3.METHODS[2], "RMSE_HU_mean"] < 0.9 * rows.loc[b3.METHODS[0], "RMSE_HU_mean"]
        assert rows.loc[b3.METHODS[2], "residual_noise_hu_mean"] < rows.loc[b3.METHODS[0], "residual_noise_hu_mean"]


def test_when_neighbouring_slices_disagree_strong_smoothing_across_slices_is_not_selected(runs):
    """Smoothing across slices removes noise to first order in the weight given to the neighbours but costs structure to second order,
    so a very light z kernel can still pay off at high noise; at 10 and 25 HU the +-150 HU alternation makes any z smoothing a loss."""
    _volume, _tune, _test, tables = runs["alternating"]
    aniso = tables["selected_parameters"]
    aniso = aniso[aniso["method"] == b3.METHODS[2]].assign(sigma_z=lambda t: t["params"].map(lambda p: json.loads(p)["sigma_z_mm"]))
    low_noise = aniso[aniso["condition"].isin(["white_10HU", "white_25HU"])]
    assert (low_noise["sigma_z"] == 0.0).all()
    assert (aniso["sigma_z"] <= 1.0).all()                   # never beyond the lightest non-zero kernel of the grid
    pairs = tables["test_pairwise"]
    rows = pairs[(pairs["metric"] == "RMSE_HU") & (pairs["mask"] == b3.PRIMARY_MASK) & (pairs["A"] == b3.METHODS[1]) & (pairs["B"] == b3.METHODS[0])]
    assert (rows["mean_A_minus_B"] >= -1e-9).all()           # the isotropic 3D filter is never better than slice-wise smoothing here


def test_every_test_row_obeys_the_error_decomposition_and_has_no_missing_value(runs):
    for mode, (_volume, _tune, _test, tables) in runs.items():
        per_run = tables["test_per_run"]
        columns = ["RMSE_HU", "blur_rmse_hu", "residual_noise_hu", "cross_term_hu2"]
        assert not per_run[per_run["mask"] != "soft"][columns].isna().any().any()
        if mode == "same":
            assert not per_run[columns].isna().any().any()
        else:   # the alternating body is at 40 +- 150 HU, outside the 0-100 HU soft-tissue range: that region is empty, and reported as missing
            assert per_run[per_run["mask"] == "soft"]["RMSE_HU"].isna().all() and (per_run[per_run["mask"] == "soft"]["mask_pixels"] == 0).all()
        assert set(per_run["mask"]) == {"main", "inner", "soft"}
        masks = per_run[per_run["mask"].isin(["main", "inner"])]
        assert not masks[["PSNR_dB", "SSIM_Wang2004"]].isna().any().any()
        assert per_run[per_run["mask"] == "soft"]["PSNR_dB"].isna().all()       # PSNR and SSIM are not defined for the soft-tissue region
        assert np.allclose(per_run["RMSE_HU"] ** 2, per_run["blur_rmse_hu"] ** 2 + per_run["residual_noise_hu"] ** 2 + per_run["cross_term_hu2"], rtol=1e-6, atol=1e-6, equal_nan=True)
        unfiltered = per_run[(per_run["method"] == b3.BASELINE) & per_run["RMSE_HU"].notna()]
        assert (unfiltered["blur_rmse_hu"] == 0).all()
        sigma = unfiltered["condition"].map(lambda c: float(c.split("_")[1].removesuffix("HU")))
        assert np.allclose(unfiltered["RMSE_HU"], sigma, rtol=0.1)       # unfiltered error is the noise level


def test_all_methods_see_the_same_noisy_slice(runs):
    _volume, _tune, _test, tables = runs["same"]
    per_run = tables["test_per_run"]
    keys = ["condition", "mask", "slice", "repeat"]
    assert (per_run.groupby(keys)["seed"].nunique() == 1).all()
    assert per_run.groupby(keys)["method"].nunique().eq(4).all()


def test_the_benchmark_is_reproducible_to_the_last_bit():
    volume = phantom("same", slices=45)
    plan = b3.plan_slices(volume, n_tune=2, n_test=2)
    first = b3.run(volume, SPACING, *plan, tune_repeats=1, test_repeats=1, n_boot=50)
    second = b3.run(volume, SPACING, *plan, tune_repeats=1, test_repeats=1, n_boot=50)
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name])


def test_overlapping_slice_sets_are_refused():
    with pytest.raises(ValueError, match="disjoint"):
        b3.run(phantom("same", slices=45), SPACING, [10, 12], [12, 20], 1, 1, 10)


def test_the_figures_are_written_from_the_tables(runs, tmp_path):
    _volume, _tune, _test, tables = runs["same"]
    paths = b3.make_figures(tables, tmp_path)
    assert [p.name for p in paths] == ["tradeoff_curves.png", "test_rmse.png"] and all(p.stat().st_size > 5000 for p in paths)


def test_the_selected_parameters_are_the_first_minimum_of_the_tuning_error_on_the_principal_mask(runs):
    assert b3.PRIMARY_MASK == "main"                                 # the principal mask named in the README and in run_metadata.json
    for _volume, _tune, _test, tables in runs.values():
        grid, selected = tables["tuning_grid"], tables["selected_parameters"]
        assert len(selected) == len(b3.NOISE_SIGMAS_HU) * len(b3.METHODS)
        for _, row in selected.iterrows():
            group = grid[(grid["condition"] == row["condition"]) & (grid["method"] == row["method"])]
            first_minimum = group.loc[group["RMSE_HU_main"].idxmin()]
            assert json.loads(row["params"]) == json.loads(first_minimum["params"])           # an exact tie goes to the weaker (earlier) setting


def test_the_reported_intervals_use_the_documented_bootstrap_seed():
    rng = np.random.default_rng(0)
    rows = [{"condition": "white_10HU", "mask": "main", "slice": s, "method": m, **{k: float(rng.normal(10, 2)) for k in b3.SUMMARY_METRICS}, "n_repeats": 5}
            for s in range(8) for m in b3.METHODS]
    per_slice = pd.DataFrame(rows)
    assert b3.BOOTSTRAP_SEED == 12345                                # the seed recorded in run_metadata.json: changing it would change every recorded interval
    summary = b3.summarise(per_slice, n_boot=300)
    row = summary[summary.method == b3.METHODS[0]].iloc[0]
    values = per_slice[per_slice.method == b3.METHODS[0]].sort_values("slice")["RMSE_HU"].to_numpy()
    assert (row["RMSE_HU_ci_low"], row["RMSE_HU_ci_high"]) == b2.bootstrap_ci(values, 300, seed=12345)
    a, b = b3.PAIRS[0]
    paired = b3.pairwise(per_slice, n_boot=300)
    row = paired[(paired.A == a) & (paired.B == b) & (paired.metric == "RMSE_HU")].iloc[0]
    wide = per_slice.pivot(index="slice", columns="method", values="RMSE_HU")
    assert (row["ci_low"], row["ci_high"]) == b2.bootstrap_ci((wide[a] - wide[b]).to_numpy(), 300, seed=12345)


def test_tuning_and_test_noise_come_from_separate_seed_bases_and_never_coincide(monkeypatch):
    calls = []
    real = b2.condition_seed

    def spy(base, index, condition_index, repeat):
        seed = real(base, index, condition_index, repeat)
        calls.append((base, index, seed))
        return seed

    monkeypatch.setattr(b2, "condition_seed", spy)
    volume = phantom("same")
    tune_slices, test_slices = b3.plan_slices(volume, n_tune=2, n_test=2)
    tables = b3.run(volume, SPACING, tune_slices, test_slices, tune_repeats=1, test_repeats=1, n_boot=50)
    assert b3.TUNING_BASE_SEED != b3.TEST_BASE_SEED
    assert {base for base, _, _ in calls} == {b3.TUNING_BASE_SEED, b3.TEST_BASE_SEED}        # no other source of noise seeds
    tuning = {seed for base, _, seed in calls if base == b3.TUNING_BASE_SEED}
    testing = {seed for base, _, seed in calls if base == b3.TEST_BASE_SEED}
    assert tuning and testing and not tuning & testing
    assert {index for base, index, _ in calls if base == b3.TUNING_BASE_SEED} == set(tune_slices)
    assert {index for base, index, _ in calls if base == b3.TEST_BASE_SEED} == set(test_slices)
    assert set(tables["test_per_run"]["seed"]) == testing                                    # the recorded seeds are exactly the test seeds


# --- the shipped run --------------------------------------------------------------------------------------


SHIPPED = sorted((Path(__file__).resolve().parent / "docs" / "results").glob("benchmark_3d_*"))


@pytest.mark.skipif(not SHIPPED, reason="no recorded benchmark 3D run is shipped")
def test_the_shipped_run_files_match_the_hashes_in_its_metadata():
    for run_dir in SHIPPED:
        meta = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
        for name, digest in {**meta["files_sha256"], **meta["figures_sha256"]}.items():
            assert b2.sha256_of(run_dir / name) == digest, name
        assert set(meta["parameters"]["tune_slices"]).isdisjoint(meta["parameters"]["test_slices"])
        assert "limitations" in meta and meta["input_series"]["dicom_instances"] > 0 and "git_commit" in meta
