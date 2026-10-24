"""Tests for benchmark V2: body mask, slice split, HU noise, HU metrics, CIs, tuning/test separation.

Every expected value is derived from the definition (geometry, NumPy, closed-form results),
not by calling the function under test.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pytest
from scipy import ndimage

import benchmark_v2 as B
import filters
from evaluate_denoising import window_ct_slice



def phantom_volume(n=24, size=48, lung_slices=range(4, 20), soft_tissue=20.0):
    """Air outside, a soft-tissue body disc, two lung discs on ``lung_slices``; unique corner marker per slice."""
    yy, xx = np.mgrid[0:size, 0:size]
    c = size / 2
    body = np.hypot(yy - c, xx - c) < size * 0.42
    volume = np.full((n, size, size), -1000.0)
    texture = np.random.default_rng(0).normal(0, 2.0, size=(n, size, size))
    for s in range(n):
        volume[s][body] = soft_tissue
        if s in lung_slices:
            for dx in (-size * 0.18, size * 0.18):
                volume[s][np.hypot(yy - c, xx - (c + dx)) < size * 0.12] = -800.0
        volume[s][int(size * 0.20):int(size * 0.28), int(size * 0.40):int(size * 0.60)] = 600.0  # bone, above the window
        volume[s] += texture[s]
        volume[s, 0, 0] = -1000.0 - s  # unique marker, stays far below the body threshold
    return volume


# --- body mask and lung fraction -------------------------------------------------------


def test_body_mask_fills_lungs_and_excludes_air_and_small_blobs():
    hu = np.full((40, 40), -1000.0)
    hu[5:35, 5:35] = 30.0           # body
    hu[12:20, 12:20] = -800.0       # lung hole inside the body
    hu[1:3, 1:3] = 60.0             # separate small blob (e.g. a marker), must be dropped
    mask = B.body_mask(hu)
    assert mask[5:35, 5:35].all()
    assert not mask[:5, :].any() and not mask[35:, :].any()
    assert not mask[1:3, 1:3].any()
    assert mask.sum() == 30 * 30


def test_body_mask_of_all_air_is_empty():
    assert not B.body_mask(np.full((10, 10), -1000.0)).any()


def test_lung_fraction_equals_lung_area_over_body_area():
    hu = np.full((40, 40), -1000.0)
    hu[5:35, 5:35] = 30.0           # 900 px body
    hu[10:20, 10:20] = -800.0       # 100 px lung
    assert B.lung_fraction(hu) == pytest.approx(100 / 900)


def test_eligible_slices_are_exactly_those_with_lung():
    volume = phantom_volume()
    assert B.eligible_slices(volume) == list(range(4, 20))


# --- slice split -----------------------------------------------------------------------


@pytest.mark.parametrize("n_eligible, n_tune, n_test, gap", [(78, 3, 8, 3), (40, 3, 8, 3), (30, 1, 5, 2), (60, 5, 10, 4)])
def test_tuning_and_test_slices_are_disjoint_and_separated(n_eligible, n_tune, n_test, gap):
    eligible = list(range(16, 16 + n_eligible))
    tune, test = B.split_slices(eligible, n_tune, n_test, gap)
    assert set(tune).isdisjoint(test)
    assert len(test) == n_test and set(tune) <= set(eligible) and set(test) <= set(eligible)
    assert min(abs(a - b) for a in test for b in tune) >= gap


def test_split_is_deterministic_and_spread_over_the_range():
    eligible = list(range(16, 94))
    first = B.split_slices(eligible)
    assert first == B.split_slices(eligible)
    tune, test = first
    assert tune[0] < tune[1] < tune[2]
    assert min(test) <= eligible[0] + 5 and max(test) >= eligible[-1] - 5


def test_split_rejects_too_few_slices():
    with pytest.raises(ValueError):
        B.split_slices(list(range(10)), n_tune=3, n_test=8, min_gap=3)
    with pytest.raises(ValueError):
        B.split_slices([], n_tune=3)
    with pytest.raises(ValueError):
        B.split_slices(list(range(30)), min_gap=0)


# --- seeds ----------------------------------------------------------------------------


def test_seeds_are_deterministic_unique_and_disjoint_between_tuning_and_test():
    config = B.Config([35, 54, 74], [16, 25, 39, 48, 61, 70, 84, 93])
    tune = {B.condition_seed(config.tune_base_seed, s, c, r) for s in config.tune_slices for c in range(8) for r in range(config.tune_repeats)}
    test = {B.condition_seed(config.test_base_seed, s, c, r) for s in config.test_slices for c in range(8) for r in range(config.test_repeats)}
    assert len(tune) == 3 * 8 * 2 and len(test) == 8 * 8 * 5
    assert tune.isdisjoint(test)
    assert config.tune_base_seed != config.test_base_seed
    assert B.condition_seed(1, 2, 3, 4) == B.condition_seed(1, 2, 3, 4)
    assert all(0 <= s < 2**32 for s in tune | test)


# --- noise ----------------------------------------------------------------------------


def _lag1(noise):
    a, b = noise[:, :-1].ravel(), noise[:, 1:].ravel()
    return float(np.corrcoef(a, b)[0, 1])


@pytest.mark.parametrize("sigma", [10.0, 25.0, 50.0])
def test_white_noise_has_the_requested_std_zero_mean_and_no_correlation(sigma):
    noise = B.hu_noise((400, 400), sigma, "white", seed=1)
    assert noise.std() == pytest.approx(sigma, rel=0.01)
    assert abs(noise.mean()) < 0.02 * sigma
    assert abs(_lag1(noise)) < 0.01


@pytest.mark.parametrize("sigma", [10.0, 25.0, 50.0])
def test_correlated_noise_has_the_requested_std_and_the_expected_correlation(sigma):
    noise = B.hu_noise((400, 400), sigma, "correlated", seed=2)
    assert noise.std() == pytest.approx(sigma, rel=0.03)
    # Gaussian-smoothed white noise (sigma_c = 1 px): lag-1 correlation exp(-1 / (4 sigma_c^2)).
    assert _lag1(noise) == pytest.approx(math.exp(-0.25), abs=0.03)


def test_noise_is_reproducible_and_depends_on_the_seed():
    a = B.hu_noise((32, 32), 10, "white", 5)
    assert np.array_equal(a, B.hu_noise((32, 32), 10, "white", 5))
    assert not np.array_equal(a, B.hu_noise((32, 32), 10, "white", 6))


@pytest.mark.parametrize("args", [((8, 8), 0, "white", 1), ((8, 8), -5, "white", 1), ((8, 8), float("nan"), "white", 1), ((8, 8), 5, "poisson", 1)])
def test_invalid_noise_arguments_are_rejected(args):
    with pytest.raises(ValueError):
        B.hu_noise(*args)


# --- fixed evaluation mask -----------------------------------------------------------------


def _bone_pixels(volume, index=1):
    """Pixels of the phantom bone (600 HU, above the display-window upper limit of 149.5 HU)."""
    return volume[index] > 400


def test_the_mask_is_the_body_of_the_clean_reference_only():
    hu = phantom_volume(n=3, size=64, lung_slices=range(3))[1]
    assert np.array_equal(B.evaluation_mask(hu), B.body_mask(hu))


@pytest.mark.parametrize("condition", B.CONDITIONS, ids=[c.name for c in B.CONDITIONS])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_noise_condition_and_seed_gets_exactly_the_same_mask(condition, seed):
    hu = phantom_volume(n=3, size=64, lung_slices=range(3))[1]
    case = B.make_case(hu, condition, seed)
    assert np.array_equal(case.mask, B.evaluation_mask(hu))
    assert np.array_equal(case.reference_hu, hu)


def test_the_mask_does_not_depend_on_the_noise_level():
    hu = phantom_volume(n=3, size=64, lung_slices=range(3))[1]
    masks = [B.make_case(hu, B.Condition("c", "d", "white", "main", sigma_hu=s), 1).mask for s in (1.0, 10.0, 50.0, 500.0)]
    assert all(np.array_equal(masks[0], m) for m in masks[1:])


def test_pixels_beyond_the_display_window_stay_in_the_mask():
    """Bone (600 HU) lies above the 149.5 HU window limit; the old 3-sigma rule dropped such pixels."""
    volume = phantom_volume(n=3, size=64, lung_slices=range(3))
    hu = volume[1]
    bone = _bone_pixels(volume)
    lower, upper = B.window_bounds()
    assert bone.sum() > 50 and hu[bone].min() > upper
    mask = B.evaluation_mask(hu)
    assert mask[bone].all(), "bone pixels must be inside the evaluation mask"
    assert mask.sum() == B.body_mask(hu).sum()
    assert not mask[0, 0]                     # air outside the body is the only thing excluded


def test_all_outputs_of_one_case_are_scored_on_the_same_mask(monkeypatch):
    hu = phantom_volume(n=3, size=64, lung_slices=range(3))[1]
    case = B.make_case(hu, B.CONDITIONS[1], 5)
    seen = []
    original = B.hu_errors

    def spy(reference, output, mask):
        seen.append(mask)
        return original(reference, output, mask)

    monkeypatch.setattr(B, "hu_errors", spy)
    for family in (B.BASELINE, "Mean", "Median", "Gaussian", "FFT ideal", "FFT Gaussian", "FFT Butterworth"):
        params = {"kernel_size": 5, "sigma": 1.0, "cutoff_ratio": 0.2}
        B.evaluate_output(case, B.filter_hu(case.noisy_hu, family, params))
    assert len(seen) >= 7 and all(m is case.mask for m in seen)


def test_pixels_outside_the_mask_have_no_influence_and_pixels_inside_do():
    hu = phantom_volume(n=3, size=64, lung_slices=range(3))[1]
    case = B.make_case(hu, B.CONDITIONS[1], 5)
    perfect = case.reference_hu.copy()
    outside = perfect.copy()
    outside[~case.mask] += 500.0
    inside = perfect.copy()
    inside[case.mask] += 5.0
    ok = B.evaluate_output(case, outside)
    assert ok["RMSE_HU"] == 0 and ok["MAE_HU"] == 0 and ok["RMSE_windowed"] == 0 and math.isinf(ok["PSNR_dB"])
    bad = B.evaluate_output(case, inside)
    assert bad["RMSE_HU"] == pytest.approx(5.0) and bad["RMSE_windowed"] > 0 and bad["PSNR_dB"] < 80


def test_an_empty_mask_gives_nan_errors():
    ref = np.zeros((6, 6))
    none = np.zeros((6, 6), bool)
    assert all(math.isnan(v) for v in B.hu_errors(ref, ref, none))


# --- no silent clipping ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["white", "correlated"])
@pytest.mark.parametrize("sigma", [10.0, 25.0, 50.0])
def test_unfiltered_hu_rmse_equals_sigma_over_the_whole_mask_including_bone_and_soft_tissue(kind, sigma):
    volume = phantom_volume(n=4, size=160, lung_slices=range(4))
    case = B.make_case(volume[1], B.Condition("c", "d", kind, "main", sigma_hu=sigma), seed=7)
    assert case.mask.sum() > 8000
    metrics = B.evaluate_output(case, case.noisy_hu, full=False)
    assert metrics["RMSE_HU"] == pytest.approx(sigma, rel=0.03)
    assert metrics["MAE_HU"] == pytest.approx(sigma * math.sqrt(2 / math.pi), rel=0.03)


def test_noise_on_pixels_beyond_the_window_is_not_truncated():
    volume = phantom_volume(n=4, size=160, lung_slices=range(4))
    bone = _bone_pixels(volume)
    case = B.make_case(volume[1], B.Condition("c", "d", "white", "main", sigma_hu=40.0), seed=3)
    error = (case.noisy_hu - case.reference_hu)[bone]
    assert error.size > 300 and error.std() == pytest.approx(40.0, rel=0.10)   # ~3.6 % sampling error with 384 pixels
    assert error.min() < -60 and error.max() > 60


def test_the_display_window_saturates_equally_reference_and_output_but_hu_errors_are_kept():
    hu = np.full((20, 20), 600.0)                 # above the window upper limit
    case = B.Case(hu, hu + 30.0, np.ones((20, 20), bool))
    metrics = B.evaluate_output(case, case.noisy_hu)
    assert metrics["RMSE_HU"] == pytest.approx(30.0)      # nothing is hidden in HU
    assert metrics["RMSE_windowed"] == 0.0                 # both are displayed as 1.0
    assert B.display(hu).max() == B.display(hu + 30.0).min() == 1.0


def test_hu_to_unit_round_trips_and_refuses_values_outside_the_range():
    low, high = B.NORMALISATION_RANGE_HU
    hu = np.array([[low, 0.0, 1234.5, high]])
    unit = B.hu_to_unit(hu)
    assert unit.min() == 0.0 and unit.max() == 1.0
    np.testing.assert_allclose(B.unit_to_hu(unit), hu, atol=1e-9)
    with pytest.raises(ValueError, match="refusing to clip"):
        B.hu_to_unit(np.array([[low - 1.0]]))
    with pytest.raises(ValueError, match="refusing to clip"):
        B.hu_to_unit(np.array([[high + 1.0]]))


def test_the_normalisation_range_contains_everything_that_can_occur_in_the_series():
    low, high = B.NORMALISATION_RANGE_HU
    assert low <= -2048 - 500 and high >= 3800 + 4000   # padding value, brightest voxel, 5 sigma of speckle on bone


def test_filtering_in_the_normalised_domain_is_exactly_filtering_in_hu():
    rng = np.random.default_rng(4)
    hu = rng.normal(-300, 200, (48, 48))
    for family, params, direct in (
        ("Mean", {"kernel_size": 5}, cv2.boxFilter(hu, -1, (5, 5), borderType=cv2.BORDER_REFLECT101)),
        ("Median", {"kernel_size": 5}, ndimage.median_filter(hu, size=5, mode="reflect")),
        ("Gaussian", {"kernel_size": 7, "sigma": 1.2}, cv2.GaussianBlur(hu, (7, 7), sigmaX=1.2, borderType=cv2.BORDER_REFLECT101)),
    ):
        np.testing.assert_allclose(B.filter_hu(hu, family, params), direct, atol=1e-8)


def test_the_result_does_not_depend_on_the_chosen_normalisation_range(monkeypatch):
    hu = np.random.default_rng(5).normal(-300, 200, (48, 48))
    reference = {f: B.filter_hu(hu, f, p) for f, p in (("FFT Gaussian", {"cutoff_ratio": 0.2}), ("Median", {"kernel_size": 7}),
                                                       ("FFT ideal", {"cutoff_ratio": 0.15}))}
    monkeypatch.setattr(B, "NORMALISATION_RANGE_HU", (-9000.0, 20000.0))
    for family, params in (("FFT Gaussian", {"cutoff_ratio": 0.2}), ("Median", {"kernel_size": 7}), ("FFT ideal", {"cutoff_ratio": 0.15})):
        np.testing.assert_allclose(B.filter_hu(hu, family, params), reference[family], atol=1e-6)


def test_a_filtered_output_touching_the_range_limit_stops_the_run():
    low, high = B.NORMALISATION_RANGE_HU
    saturated = np.full((16, 16), high)
    with pytest.raises(RuntimeError, match="possible clipping"):
        B.filter_hu(saturated, "Mean", {"kernel_size": 3})
    assert np.array_equal(B.filter_hu(saturated, B.BASELINE, {}), saturated)  # baseline is never filtered


# --- the display window and the windowed metrics -----------------------------------------------


def test_the_display_window_is_the_documented_lung_window():
    assert (B.DISPLAY_WINDOW_CENTER, B.DISPLAY_WINDOW_WIDTH) == (-600.0, 1500.0)
    lower, upper = B.window_bounds()
    assert (lower, upper) == (-600 - 0.5 - 749.5, -600 - 0.5 + 749.5) == (-1350.0, 149.0)
    np.testing.assert_allclose(B.display(np.array([[lower, upper, -600.5]])), [[0.0, 1.0, 0.5]], atol=1e-12)


def test_the_v2_display_equals_the_historical_lung_window_function():
    """Same window formula and values as the historical benchmark's display (continuity of the images, not of the metrics)."""
    hu = np.linspace(-2048, 1000, 50 * 50).reshape(50, 50)
    np.testing.assert_array_equal(B.display(hu), window_ct_slice(hu, -600.0, 1500.0))


def test_the_same_window_is_applied_to_the_reference_and_to_every_output():
    hu = phantom_volume(n=3, size=48, lung_slices=range(3))[1]
    case = B.make_case(hu, B.CONDITIONS[1], 2)
    identical = B.evaluate_output(case, case.reference_hu)
    assert identical["RMSE_windowed"] == 0 and math.isinf(identical["PSNR_dB"])
    assert identical["SSIM_skimage_default"] == pytest.approx(1.0) and identical["SSIM_Wang2004"] == pytest.approx(1.0)


def test_masked_psnr_matches_its_definition_and_the_reference_function_on_a_full_mask():
    rng = np.random.default_rng(6)
    ref = rng.uniform(0, 1, (30, 30))
    out = np.clip(ref + rng.normal(0, 0.05, (30, 30)), 0, 1)
    full = np.ones((30, 30), bool)
    assert B.masked_psnr(ref, out, full) == pytest.approx(filters.calculate_metrics(ref, out)[0], abs=1e-9)
    half = np.zeros((30, 30), bool)
    half[:15] = True
    assert B.masked_psnr(ref, out, half) == pytest.approx(10 * math.log10(1 / np.mean((out - ref)[half] ** 2)))


def test_masked_ssim_equals_the_library_value_on_the_interior_and_depends_on_the_mask():
    rng = np.random.default_rng(7)
    ref = rng.uniform(0, 1, (40, 40))
    out = np.clip(ref + rng.normal(0, 0.1, (40, 40)), 0, 1)
    interior = np.zeros((40, 40), bool)
    interior[3:-3, 3:-3] = True                       # skimage averages the SSIM map over this crop (7x7 window)
    assert B.masked_ssim(ref, out, interior, fully_inside=False) == pytest.approx(filters.calculate_metrics(ref, out)[1], abs=1e-12)
    corner = np.zeros((40, 40), bool)
    corner[3:12, 3:12] = True
    assert B.masked_ssim(ref, out, corner, fully_inside=False) != pytest.approx(B.masked_ssim(ref, out, interior, fully_inside=False), abs=1e-6)
    # the PRIMARY definition is the default: windows fully inside the mask
    assert B.masked_ssim(ref, out, corner) == B.masked_ssim(ref, out, corner, fully_inside=True)


# --- the noise models in HU --------------------------------------------------------------------


def test_impulse_noise_sets_the_requested_fraction_to_the_window_limits_only():
    hu = np.full((300, 300), -300.0)
    noisy = B.impulse_noise(hu, 0.05, seed=1)
    lower, upper = B.window_bounds()
    changed = noisy != hu
    assert changed.mean() == pytest.approx(0.05, abs=0.005)
    assert set(np.unique(noisy[changed])) == {lower, upper}
    assert (noisy[changed] == upper).mean() == pytest.approx(0.5, abs=0.05)
    assert np.array_equal(noisy[~changed], hu[~changed])


def test_speckle_leaves_air_unchanged_and_scales_with_hu_plus_1000():
    hu = np.full((300, 300), 40.0)
    hu[:, :100] = -1000.0
    noisy = B.speckle_noise(hu, 0.02, seed=2)
    assert np.array_equal(noisy[:, :100], hu[:, :100])
    relative = (noisy - hu)[:, 100:] / (40.0 + B.SPECKLE_OFFSET_HU)
    assert relative.std() == pytest.approx(math.sqrt(0.02), rel=0.03)


def test_make_case_is_reproducible_for_a_fixed_seed():
    hu = phantom_volume(n=3, size=32, lung_slices=range(3))[1]
    for condition in B.CONDITIONS:
        a, b = B.make_case(hu, condition, 11), B.make_case(hu, condition, 11)
        assert np.array_equal(a.noisy_hu, b.noisy_hu) and np.array_equal(a.mask, b.mask)
        assert not np.array_equal(a.noisy_hu, B.make_case(hu, condition, 12).noisy_hu)


def test_unknown_condition_kind_is_rejected():
    with pytest.raises(ValueError):
        B.make_case(np.zeros((8, 8)), B.Condition("x", "d", "poisson", "main"), 1)


# --- filters ---------------------------------------------------------------------------


def _test_image(seed=0):
    rng = np.random.default_rng(seed)
    return np.clip(0.5 + 0.2 * np.sin(np.arange(64)[:, None] / 5.0) + rng.normal(0, 0.1, (64, 64)), 0, 1)


@pytest.mark.parametrize("k", [3, 7, 11])
def test_mean_and_median_match_the_reference_implementation(k):
    image = _test_image()
    mean, median, _ = filters.apply_spatial_filters(image, kernel_size=k, sigma=0.0)
    np.testing.assert_allclose(B.apply_filter(image, "Mean", {"kernel_size": k}), mean, atol=1e-12)
    np.testing.assert_allclose(B.apply_filter(image, "Median", {"kernel_size": k}), median, atol=1e-12)


@pytest.mark.parametrize("sigma", [0.75, 1.5, 3.0])
def test_gaussian_matches_the_reference_implementation(sigma):
    image = _test_image(1)
    k = 2 * math.ceil(3 * sigma) + 1
    _, _, gaussian = filters.apply_spatial_filters(image, kernel_size=k, sigma=sigma)
    np.testing.assert_allclose(B.apply_filter(image, "Gaussian", {"kernel_size": k, "sigma": sigma}), gaussian, atol=1e-12)


@pytest.mark.parametrize("family, name", [("FFT ideal", "ideal"), ("FFT Gaussian", "gauss"), ("FFT Butterworth", "butterworth")])
def test_frequency_families_match_the_reference_implementation(family, name):
    image = _test_image(2)
    expected = filters.apply_frequency_lowpass(image, cutoff_ratio=0.2, filter_type=name, order=2)[0]
    np.testing.assert_allclose(B.apply_filter(image, family, {"cutoff_ratio": 0.2}), expected, atol=1e-12)


def test_baseline_is_the_identity_and_unknown_families_fail():
    image = _test_image()
    assert np.array_equal(B.apply_filter(image, B.BASELINE, {}), image)
    with pytest.raises(ValueError):
        B.apply_filter(image, "Bilateral", {})


def test_parameter_grid_covers_every_family_with_valid_odd_kernels():
    grid = B.parameter_grid()
    assert set(grid) == set(B.FAMILIES)
    for family in ("Mean", "Median", "Gaussian"):
        assert all(p["kernel_size"] % 2 == 1 for p in grid[family])
    assert all(p["kernel_size"] >= 6 * p["sigma"] for p in grid["Gaussian"])


# --- bootstrap ---------------------------------------------------------------------------


def test_bootstrap_ci_contains_the_mean_and_is_deterministic():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    low, high = B.bootstrap_ci(values, n_boot=2000)
    assert low <= np.mean(values) <= high
    assert (low, high) == B.bootstrap_ci(values, n_boot=2000)


def test_bootstrap_ci_of_constant_values_has_zero_width():
    low, high = B.bootstrap_ci([3.5] * 6, n_boot=500)
    assert low == high == 3.5


def test_bootstrap_ci_matches_the_normal_theory_width_for_a_large_sample():
    values = np.random.default_rng(0).normal(0, 1, 400)
    low, high = B.bootstrap_ci(values, n_boot=4000)
    assert (high - low) == pytest.approx(2 * 1.96 / math.sqrt(400), rel=0.15)


def test_bootstrap_ci_is_wider_with_fewer_slices():
    rng = np.random.default_rng(1)
    big = rng.normal(0, 1, 200)
    small = big[:8]
    wide = np.subtract(*B.bootstrap_ci(small, 2000)[::-1])
    narrow = np.subtract(*B.bootstrap_ci(big, 2000)[::-1])
    assert wide > 2 * narrow


def test_bootstrap_ci_with_one_value_or_only_nan_is_undefined():
    assert all(math.isnan(v) for v in B.bootstrap_ci([1.0]))
    assert all(math.isnan(v) for v in B.bootstrap_ci([float("nan")] * 3))
    assert all(math.isnan(v) for v in B.bootstrap_ci([]))


# --- tuning ---------------------------------------------------------------------------------


def test_tuning_selects_the_configuration_with_the_lowest_mean_criterion():
    volume = phantom_volume(n=4, size=48, lung_slices=range(4))
    condition = B.Condition("c", "d", "white", "main", sigma_hu=25.0)
    cases = [B.make_case(volume[i], condition, seed=i) for i in (1, 2)]
    grid = {"Mean": [{"kernel_size": 3}, {"kernel_size": 5}, {"kernel_size": 9}], "Median": [{"kernel_size": 3}, {"kernel_size": 7}]}
    table, selected = B.tune_condition(cases, condition, grid)
    for family, configs in grid.items():
        manual = [np.mean([B.hu_errors(c.reference_hu, B.filter_hu(c.noisy_hu, family, p), c.mask)[0] for c in cases]) for p in configs]
        assert selected[family] == configs[int(np.argmin(manual))]
    assert len(table) == 5 and (table["n_tuning_cases"] == 2).all()


def test_stronger_noise_selects_at_least_as_much_smoothing_for_the_mean_filter():
    volume = phantom_volume(n=3, size=64, lung_slices=range(3))
    sizes = []
    for sigma in (5.0, 60.0):
        condition = B.Condition("c", "d", "white", "main", sigma_hu=sigma)
        cases = [B.make_case(volume[1], condition, seed=s) for s in (1, 2)]
        _, selected = B.tune_condition(cases, condition, {"Mean": [{"kernel_size": k} for k in (3, 5, 7, 9, 11)]})
        sizes.append(selected["Mean"]["kernel_size"])
    assert sizes[1] >= sizes[0]


# --- summary statistics --------------------------------------------------------------------


def test_summary_gain_is_the_mean_of_paired_per_slice_differences():
    rows = []
    for s, (base, filt) in {1: (30.0, 20.0), 2: (28.0, 21.0), 3: (26.0, 22.0)}.items():
        for family, value in ((B.BASELINE, base), ("Mean", filt)):
            rows.append({"condition": "c", "group": "main", "mask": "main", "slice": s, "family": family, **{m: value for m in B.METRIC_COLUMNS}, "mask_pixels": 100, "n_repeats": 5})
    summary = B.summarise(pd.DataFrame(rows), n_boot=500)
    mean_row = summary[summary.family == "Mean"].iloc[0]
    assert mean_row["RMSE_HU_mean"] == pytest.approx(21.0)
    assert mean_row["RMSE_HU_gain_mean"] == pytest.approx(np.mean([-10.0, -7.0, -4.0]))
    assert mean_row["RMSE_HU_gain_ci_low"] <= mean_row["RMSE_HU_gain_mean"] <= mean_row["RMSE_HU_gain_ci_high"]
    assert "RMSE_HU_gain_mean" not in summary[summary.family == B.BASELINE].columns or math.isnan(summary[summary.family == B.BASELINE].iloc[0]["RMSE_HU_gain_mean"])


def test_pairwise_differences_are_antisymmetric_in_definition():
    rows = []
    for s in (1, 2, 3, 4):
        for family, value in (("Mean", 10.0 + s), ("Median", 8.0 + s)):
            rows.append({"condition": "c", "group": "main", "mask": "main", "slice": s, "family": family, **{m: value for m in B.METRIC_COLUMNS}})
    pairs = B.pairwise_differences(pd.DataFrame(rows), n_boot=300)
    row = pairs[(pairs.A == "Mean") & (pairs.B == "Median") & (pairs.metric == "RMSE_HU")].iloc[0]
    assert row["mean_A_minus_B"] == pytest.approx(2.0) and row["ci_low"] == row["ci_high"] == pytest.approx(2.0)


# --- full run on a small synthetic volume ----------------------------------------------------


SMALL = (B.CONDITIONS[1], B.CONDITIONS[4], B.CONDITIONS[6])  # white 25 HU, correlated 25 HU, salt & pepper


def _small_run(volume, record=None, monkeypatch=None):
    config = B.Config(tune_slices=[6], test_slices=[11, 15], tune_repeats=1, test_repeats=2, n_boot=200)
    return config, B.run_benchmark(volume, config, conditions=SMALL)


def test_run_produces_consistent_tables():
    volume = phantom_volume(n=24, size=48)
    config, tables = _small_run(volume)
    per_run, per_slice, summary, selected = tables["test_per_run"], tables["test_per_slice"], tables["test_summary"], tables["selected_parameters"]
    assert len(per_run) == 3 * 2 * 2 * 7 * 2                  # conditions x slices x repeats x (6 filters + baseline) x 2 masks
    assert set(per_run["mask"]) == {"main", "inner"}
    assert set(per_run["slice"]) == {11, 15}
    assert len(selected) == 3 * 6 and set(selected["family"]) == set(B.FAMILIES)
    assert (summary["n_slices"] == 2).all()
    assert set(per_slice["n_repeats"]) == {2}
    baseline = per_slice[(per_slice.condition == "white_25HU") & (per_slice.family == B.BASELINE) & (per_slice["mask"] == "main")]
    assert baseline["RMSE_HU"].mean() == pytest.approx(25.0, rel=0.1)
    # the evaluation mask is fixed by the reference slice: one value per slice, whatever the noise, filter or repeat
    for (slice_index, mask_name), group in per_run.groupby(["slice", "mask"]):
        assert group["mask_pixels"].nunique() == 1
        expected = B.reference_masks(volume[slice_index].astype(float))[mask_name]
        assert group["mask_pixels"].iloc[0] == expected.sum()
    assert per_run[["RMSE_windowed", "MAE_windowed", "PSNR_dB", "SSIM_skimage_default", "SSIM_Wang2004", "RMSE_HU", "MAE_HU"]].notna().all().all()
    assert tables["tuning_grid"]["n_tuning_cases"].eq(1).all()


def test_run_is_deterministic():
    volume = phantom_volume(n=24, size=48)
    _, first = _small_run(volume)
    _, second = _small_run(volume.copy())
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name])


def test_test_slices_never_influence_the_tuning():
    volume = phantom_volume(n=24, size=48)
    altered = volume.copy()
    for index in (11, 15):                       # change only the test slices, drastically
        altered[index][20:30, 20:30] = 100.0
    _, base = _small_run(volume)
    _, other = _small_run(altered)
    pd.testing.assert_frame_equal(base["selected_parameters"], other["selected_parameters"])
    pd.testing.assert_frame_equal(base["tuning_grid"], other["tuning_grid"])
    assert not base["test_summary"].equals(other["test_summary"])


def test_changing_a_tuning_slice_does_change_the_tuning_scores():
    volume = phantom_volume(n=24, size=48)
    altered = volume.copy()
    altered[6][20:30, 20:30] = 100.0
    _, base = _small_run(volume)
    _, other = _small_run(altered)
    assert not base["tuning_grid"]["mean_score"].equals(other["tuning_grid"]["mean_score"])


def test_every_generated_noise_realisation_comes_from_the_right_slice_and_phase(monkeypatch):
    volume = phantom_volume(n=24, size=48)
    config = B.Config(tune_slices=[6], test_slices=[11, 15], tune_repeats=2, test_repeats=2, n_boot=100)
    calls = []
    original = B.make_case

    def spy(hu, condition, seed, *args, **kwargs):
        calls.append((int(round(-1000.0 - hu[0, 0])), condition.name, seed))
        return original(hu, condition, seed, *args, **kwargs)

    monkeypatch.setattr(B, "make_case", spy)
    B.run_benchmark(volume, config, conditions=SMALL)
    tune_seeds = {B.condition_seed(config.tune_base_seed, 6, ci, r) for ci in range(3) for r in range(2)}
    test_seeds = {B.condition_seed(config.test_base_seed, s, ci, r) for s in (11, 15) for ci in range(3) for r in range(2)}
    assert tune_seeds.isdisjoint(test_seeds)
    for slice_index, _, seed in calls:
        if seed in tune_seeds:
            assert slice_index == 6
        else:
            assert seed in test_seeds and slice_index in (11, 15)
    assert {s for s, _, seed in calls if seed in tune_seeds} == {6}


def test_overlapping_tuning_and_test_slices_are_refused():
    with pytest.raises(ValueError, match="disjoint"):
        B.run_benchmark(phantom_volume(), B.Config([6], [6, 11]), conditions=SMALL)


# --- outputs and safety ------------------------------------------------------------------------


def test_outputs_are_written_with_matching_hashes(tmp_path):
    tables = {"a": pd.DataFrame({"x": [1.0, 2.0]}), "b": pd.DataFrame({"y": ["u", "v"]})}
    paths = B.write_outputs(tables, tmp_path / "run", {"schema_version": 1, "note": "n"})
    meta = json.loads((tmp_path / "run" / "run_metadata.json").read_text(encoding="utf-8"))
    assert set(meta["files_sha256"]) == {"a.csv", "b.csv"}
    for name, path in paths.items():
        assert meta["files_sha256"][path.name] == B.sha256_of(path)
        assert len(pd.read_csv(path)) == 2


def test_refuses_to_write_inside_the_repository(tmp_path):
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    with pytest.raises(SystemExit):
        B.ensure_outside_repository(repo / "backend" / "reports", repo, allow=False)
    with pytest.raises(SystemExit):
        B.ensure_outside_repository(repo, repo, allow=False)
    B.ensure_outside_repository(tmp_path / "elsewhere", repo, allow=False)
    B.ensure_outside_repository(repo / "backend" / "reports", repo, allow=True)


def _write_dicom_series(directory: Path, volume: np.ndarray) -> Path:
    from conftest import make_dicom_bytes

    directory.mkdir(parents=True, exist_ok=True)
    for index, hu in enumerate(volume):
        payload = make_dicom_bytes(series_uid="1.2.826.0.1.3680043.8.498.555", instance_number=index + 1, z_mm=3.0 * index,
                                   rows=hu.shape[0], cols=hu.shape[1], hu=np.round(hu), pixel_spacing=(0.7, 0.7))
        (directory / f"s{index:03d}.dcm").write_bytes(payload)
    return directory


def test_command_line_run_on_a_dicom_series_writes_tables_and_metadata(tmp_path, capsys):
    series = _write_dicom_series(tmp_path / "series", phantom_volume(n=24, size=40))
    out = tmp_path / "out"
    B.main(["--dicom-series", str(series), "--out", str(out), "--n-tune", "1", "--n-test", "3", "--min-gap", "2",
            "--tune-repeats", "1", "--test-repeats", "1", "--n-boot", "50"])
    assert sorted(p.name for p in out.iterdir()) == sorted(
        ["tuning_grid.csv", "selected_parameters.csv", "grid_bracketing.csv", "tuning_criteria_comparison.csv", "mask_summary.csv",
         "test_per_run.csv", "test_per_slice.csv", "test_summary.csv", "test_pairwise.csv", "mask_sensitivity.csv", "mask_ranking.csv",
         "ssim_sensitivity.csv", "run_metadata.json"])
    meta = json.loads((out / "run_metadata.json").read_text(encoding="utf-8"))
    params = meta["parameters"]
    assert set(params["tune_slices"]).isdisjoint(params["test_slices"]) and len(params["test_slices"]) == 3
    assert meta["schema_version"] == 2
    window = meta["protocol"]["display_window"]
    assert (window["center_hu"], window["width_hu"]) == (-600.0, 1500.0) and window["lower_hu"] == -1350.0
    assert (params["display_window_center"], params["display_window_width"]) == (-600.0, 1500.0)
    assert meta["protocol"]["normalisation_range_hu"]["low"] == B.NORMALISATION_RANGE_HU[0]
    assert meta["protocol"]["evaluation_mask"]["pixels_dropped_by_hu_value_or_window"] == 0
    assert {"noise realisation", "noise level", "noise type", "filter", "filter parameters", "display window"} == set(meta["protocol"]["evaluation_mask"]["independent_of"])
    assert "NOT comparable" in meta["protocol"]["comparability_with_historical_results"]
    assert params["tuning_criterion"] == "RMSE_HU" and "clip_margin_sigmas" not in params
    assert meta["dicom_conversion"]["RescaleSlope"] == "1.0" and meta["dicom_conversion"]["RescaleIntercept"] == "-1024.0"
    assert "NOT used" in meta["dicom_conversion"]["note"]
    assert set(params["test_slices"]) <= set(params["eligible_slices"])
    assert meta["benchmark"] == "V2" and meta["schema_version"] == B.SCHEMA_VERSION == 2 and meta["git_commit"]
    assert {"python", "numpy", "scikit-image"} <= set(meta["packages"])
    assert "not ground" in meta["limitations"] and "no clinical validation" in meta["limitations"]
    assert [c["name"] for c in params["conditions"]] == [c.name for c in B.CONDITIONS]
    for name, digest in meta["files_sha256"].items():
        assert B.sha256_of(out / name) == digest
    summary = pd.read_csv(out / "test_summary.csv")
    assert len(summary) == len(B.CONDITIONS) * 7 * 2                       # conditions x (6 filters + baseline) x 2 masks
    assert set(summary["mask"]) == {"main", "inner"}
    # SSIM definition, windows and evaluated pixel counts are recorded
    ssim = meta["protocol"]["ssim"]
    assert "fully_inside=True" in ssim["primary_definition"] and "7x7" in ssim["windows"]["SSIM_skimage_default"] and "11x11" in ssim["windows"]["SSIM_Wang2004"]
    assert "every filter, slice, noise condition and repeat" == ssim["rule_identical_for"]
    assert params["ssim_primary_fully_inside"] is True and (params["ssim_radius_default_px"], params["ssim_radius_wang_px"]) == (3, 5)
    counts = {r["slice"]: r for r in meta["mask_pixel_counts_by_slice"]}
    assert set(counts) == set(params["tune_slices"]) | set(params["test_slices"])
    for row in counts.values():
        assert row["ssim_pixels_default_main"] > 0 and row["ssim_pixels_wang_main"] > 0 and row["inner_pixels"] <= row["main_pixels"]
    assert set(meta["mask_sha256_by_slice"]) == {str(i) for i in counts}
    inner = meta["protocol"]["inner_mask"]
    assert inner["margin_px"] == 10 and inner["padding_threshold_hu"] == -1500.0 and "EXPERIMENTAL" in inner["status"] and "not clinically validated" in inner["status"]
    assert "principal mask only" in inner["parameters_are_tuned_on"]
    # every row of the run uses the same SSIM rule: the evaluated pixel counts depend only on (slice, mask)
    per_run = pd.read_csv(out / "test_per_run.csv")
    for _, group in per_run.groupby(["slice", "mask"]):
        assert group["ssim_pixels_default"].nunique() == 1 and group["ssim_pixels_wang"].nunique() == 1
    assert "slices" in capsys.readouterr().out


def test_plan_only_writes_nothing_and_inside_repository_is_refused(tmp_path, capsys):
    series = _write_dicom_series(tmp_path / "series", phantom_volume(n=24, size=40))
    out = tmp_path / "out"
    B.main(["--dicom-series", str(series), "--out", str(out), "--n-tune", "1", "--n-test", "3", "--min-gap", "2", "--plan-only"])
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "tuning slices" in printed and "test slices" in printed
    inside = Path(B.__file__).resolve().parent / "this_folder_must_not_be_created"
    with pytest.raises(SystemExit):
        B.main(["--dicom-series", str(series), "--out", str(inside), "--plan-only"])
    assert not inside.exists()


def test_the_default_conditions_match_the_agreed_protocol():
    main = [c for c in B.CONDITIONS if c.group == "main"]
    robust = [c for c in B.CONDITIONS if c.group == "robustness"]
    assert sorted(c.sigma_hu for c in main if c.kind == "white") == [10.0, 25.0, 50.0]
    assert sorted(c.sigma_hu for c in main if c.kind == "correlated") == [10.0, 25.0, 50.0]
    assert {c.kind for c in robust} == {"salt_pepper", "speckle"}
    assert all("not a CT noise model" in c.description for c in robust)
    assert all("unvalidated" in c.description for c in main if c.kind == "correlated")


# --- SSIM windows at the mask boundary ----------------------------------------------------------


def _ssim_support_radius(**options):
    """Largest distance at which changing ONE pixel changes the SSIM map (above rounding noise)."""
    from skimage.metrics import structural_similarity

    rng = np.random.default_rng(0)
    ref = rng.uniform(0, 1, (41, 41))
    out = np.clip(ref + rng.normal(0, 0.1, ref.shape), 0, 1)
    base = structural_similarity(ref, out, data_range=1.0, full=True, **options)[1]
    changed = out.copy()
    changed[20, 20] = 1.0 - changed[20, 20]
    diff = np.abs(structural_similarity(ref, changed, data_range=1.0, full=True, **options)[1] - base)
    ys, xs = np.where(diff > 1e-9)       # scipy's running sums leave ~1e-15 noise along the rows
    return max(20 - ys.min(), ys.max() - 20, 20 - xs.min(), xs.max() - 20)


def test_ssim_window_radii_are_the_ones_the_code_assumes():
    assert _ssim_support_radius() == B.SSIM_RADIUS_DEFAULT == 3
    assert _ssim_support_radius(gaussian_weights=True, sigma=1.5, use_sample_covariance=False) == B.SSIM_RADIUS_WANG == 5


def _blob_mask(shape=(60, 60)):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    return np.hypot(yy - shape[0] / 2, xx - shape[1] / 2) < 22


@pytest.mark.parametrize("wang", [False, True])
def test_interior_mask_contains_exactly_the_pixels_whose_whole_window_is_inside(wang):
    mask = _blob_mask()
    radius = B.SSIM_RADIUS_WANG if wang else B.SSIM_RADIUS_DEFAULT
    interior = B.ssim_interior_mask(mask, wang)
    padded = np.pad(mask, radius, constant_values=False)
    for y, x in zip(*np.where(mask)):
        window_inside = padded[y:y + 2 * radius + 1, x:x + 2 * radius + 1].all()
        assert interior[y, x] == window_inside
    assert not (interior & ~mask).any() and interior.sum() < mask.sum()


def test_current_masked_ssim_reads_pixels_outside_the_mask_but_the_interior_version_does_not():
    rng = np.random.default_rng(3)
    ref = rng.uniform(0, 1, (60, 60))
    out = np.clip(ref + rng.normal(0, 0.1, ref.shape), 0, 1)
    mask = _blob_mask()
    disturbed = out.copy()
    disturbed[~mask] = rng.uniform(0, 1, (~mask).sum())     # change ONLY pixels outside the mask
    for wang in (False, True):
        inside_only = (B.masked_ssim(ref, out, mask, wang, fully_inside=True), B.masked_ssim(ref, disturbed, mask, wang, fully_inside=True))
        everything = (B.masked_ssim(ref, out, mask, wang, fully_inside=False), B.masked_ssim(ref, disturbed, mask, wang, fully_inside=False))
        assert inside_only[0] == pytest.approx(inside_only[1], abs=1e-12)        # no leakage
        assert abs(everything[0] - everything[1]) > 1e-3                           # current definition leaks


def test_the_two_definitions_differ_by_a_small_systematic_amount_on_a_synthetic_case():
    rng = np.random.default_rng(4)
    ref = np.zeros((80, 80))
    ref[:, 40:] = 1.0                                                         # an edge crossing the mask
    ref += 0.02 * rng.standard_normal(ref.shape)
    ref = np.clip(ref, 0, 1)
    out = np.clip(ref + 0.15 * rng.standard_normal(ref.shape), 0, 1)
    mask = _blob_mask((80, 80))
    current = B.masked_ssim(ref, out, mask, fully_inside=False)
    interior = B.masked_ssim(ref, out, mask)
    assert current != pytest.approx(interior, abs=1e-6) and abs(current - interior) < 0.2
    assert B.ssim_interior_mask(mask).sum() < mask.sum()


def test_interior_ssim_with_a_full_mask_equals_the_library_value():
    rng = np.random.default_rng(5)
    ref = rng.uniform(0, 1, (40, 40))
    out = np.clip(ref + rng.normal(0, 0.1, ref.shape), 0, 1)
    full = np.ones((40, 40), bool)
    assert B.masked_ssim(ref, out, full, fully_inside=True) == pytest.approx(filters.calculate_metrics(ref, out)[1], abs=1e-12)
    assert math.isnan(B.masked_ssim(ref, out, np.zeros((40, 40), bool), fully_inside=True))


def test_pointwise_metrics_cannot_be_influenced_by_pixels_outside_the_mask():
    ref = np.random.default_rng(6).uniform(0, 1, (30, 30))
    out = ref + 0.05
    mask = _blob_mask((30, 30))
    other = out.copy()
    other[~mask] += 0.7
    assert B.masked_psnr(ref, out, mask) == B.masked_psnr(ref, other, mask)
    assert B.windowed_errors(ref, out, mask) == B.windowed_errors(ref, other, mask)
    assert B.hu_errors(ref * 100, out * 100, mask) == B.hu_errors(ref * 100, other * 100, mask)


# --- the HU chain: HU -> computing domain -> HU --------------------------------------------------


@pytest.mark.parametrize("hu, unit", [
    (-4096.0, 0.0), (8192.0, 1.0), (0.0, 4096.0 / 12288.0), (-1000.0, 3096.0 / 12288.0),
    (-2048.0, 2048.0 / 12288.0), (3071.0, 7167.0 / 12288.0), (-0.5, 4095.5 / 12288.0),
])
def test_hu_maps_to_the_documented_unit_values_and_back_exactly(hu, unit):
    assert B.hu_to_unit(np.array([hu]))[0] == pytest.approx(unit, abs=1e-15)
    assert B.unit_to_hu(np.array([unit]))[0] == pytest.approx(hu, abs=1e-9)


def test_every_integer_hu_of_the_ct_range_survives_the_round_trip():
    hu = np.arange(-3000, 4001, dtype=np.float64).reshape(-1, 1)
    np.testing.assert_allclose(B.unit_to_hu(B.hu_to_unit(hu)), hu, atol=1e-9)


@pytest.mark.parametrize("value", [-2048.0, -1000.0, -0.5, 0.0, 40.0, 3000.0])
@pytest.mark.parametrize("family, params", [
    ("Mean", {"kernel_size": 7}), ("Median", {"kernel_size": 7}), ("Gaussian", {"kernel_size": 7, "sigma": 1.5}),
    ("FFT ideal", {"cutoff_ratio": 0.15}), ("FFT Gaussian", {"cutoff_ratio": 0.15}), ("FFT Butterworth", {"cutoff_ratio": 0.15}),
])
def test_filtering_a_constant_image_returns_the_same_constant_so_the_chain_has_no_bias(value, family, params):
    out = B.filter_hu(np.full((32, 32), value), family, params)
    np.testing.assert_allclose(out, value, atol=1e-7)


def test_a_one_pixel_mean_filter_is_the_identity_on_extreme_hu_values():
    hu = np.random.default_rng(8).uniform(-2048, 3500, (40, 40))
    np.testing.assert_allclose(B.filter_hu(hu, "Mean", {"kernel_size": 1}), hu, atol=1e-8)


def test_hu_noise_is_defined_in_hu_not_in_normalised_units():
    hu = np.full((300, 300), -300.0)
    for sigma in (10.0, 25.0, 50.0):
        case = B.make_case(hu, B.Condition("c", "d", "white", "main", sigma_hu=sigma), 1)
        span = B.NORMALISATION_RANGE_HU[1] - B.NORMALISATION_RANGE_HU[0]
        unit_noise = B.hu_to_unit(case.noisy_hu) - B.hu_to_unit(case.reference_hu)
        assert unit_noise.std() * span == pytest.approx(sigma, rel=0.02)          # in HU after un-normalising
        assert unit_noise.std() < 0.01                                              # tiny in normalised units
        assert abs((case.noisy_hu - case.reference_hu).mean()) < 0.03 * sigma    # no bias


@pytest.mark.parametrize("offset", [7.0, -7.0])
@pytest.mark.parametrize("base", [-2048.0, -1000.0, 0.0, 3000.0])
def test_rmse_and_mae_are_in_hu_and_do_not_depend_on_where_the_values_sit(base, offset):
    reference = np.full((20, 20), base)
    case = B.Case(reference, reference + offset, np.ones((20, 20), bool))
    metrics = B.evaluate_output(case, case.noisy_hu, full=False)
    assert metrics["RMSE_HU"] == pytest.approx(7.0, abs=1e-9) and metrics["MAE_HU"] == pytest.approx(7.0, abs=1e-9)


def test_metrics_do_not_depend_on_the_normalisation_range(monkeypatch):
    hu = phantom_volume(n=3, size=48, lung_slices=range(3))[1]
    case = B.make_case(hu, B.CONDITIONS[1], 3)
    before = B.evaluate_output(case, B.filter_hu(case.noisy_hu, "FFT Gaussian", {"cutoff_ratio": 0.2}))
    monkeypatch.setattr(B, "NORMALISATION_RANGE_HU", (-20000.0, 40000.0))
    after = B.evaluate_output(case, B.filter_hu(case.noisy_hu, "FFT Gaussian", {"cutoff_ratio": 0.2}))
    for key in before:
        assert after[key] == pytest.approx(before[key], rel=1e-6, abs=1e-6), key


def test_real_dicom_values_at_the_limits_go_through_the_chain_unchanged(tmp_path):
    from conftest import make_dicom_bytes
    from src.dicom_volume import load_dicom_volume

    hu = np.array([[-2048.0, -1000.0, -1.0, 0.0], [1.0, 40.0, 3071.0, 3500.0]] * 2)     # padding, air, water, bone, extremes
    for index in range(2):
        (tmp_path / f"s{index}.dcm").write_bytes(make_dicom_bytes(series_uid="1.2.3", instance_number=index + 1, z_mm=2.0 * index,
                                                                rows=4, cols=4, hu=hu))
    volume, *_ = load_dicom_volume(tmp_path)
    np.testing.assert_array_equal(volume[0], hu)                                          # DICOM -> HU is exact
    np.testing.assert_allclose(B.unit_to_hu(B.hu_to_unit(volume[0].astype(np.float64))), hu, atol=1e-9)


# --- physical meaning of the filter parameters ---------------------------------------------------


def test_ideal_lowpass_cutoff_is_a_fraction_of_nyquist_and_keeps_amplitude_and_mean_in_hu():
    n, cutoff = 128, 0.2                                                  # radius = 0.2 * 64 = 12.8 frequency bins
    x = np.arange(n)[None, :] * np.ones((n, 1))
    for cycles, expected_gain in ((8, 1.0), (12, 1.0), (14, 0.0), (30, 0.0)):
        hu = -300.0 + 100.0 * np.cos(2 * np.pi * cycles * x / n)
        out = B.filter_hu(hu, "FFT ideal", {"cutoff_ratio": cutoff})
        assert out.mean() == pytest.approx(-300.0, abs=1e-6)
        amplitude = (out - out.mean()).max()
        assert amplitude == pytest.approx(100.0 * expected_gain, abs=1e-5), cycles


def _fft_gaussian_vs_spatial(ratio, n=96):
    hu = np.random.default_rng(9).normal(-300, 150, (n, n))
    direct = ndimage.gaussian_filter(hu, 1.0 / (math.pi * ratio), mode="wrap", truncate=10)
    return B.filter_hu(hu, "FFT Gaussian", {"cutoff_ratio": ratio}) - direct


@pytest.mark.parametrize("ratio", [0.05, 0.08, 0.1, 0.15])
def test_fft_gaussian_lowpass_equals_a_periodic_spatial_gaussian_of_sigma_spacing_over_pi_c(ratio):
    """Exact (rounding level) whenever the equivalent sigma is at least ~2 pixels."""
    assert np.abs(_fft_gaussian_vs_spatial(ratio)).max() < 1e-6


@pytest.mark.parametrize("ratio, bound_hu", [(0.2, 1e-3), (0.3, 1.0), (0.4, 10.0)])
def test_the_equivalence_degrades_gracefully_when_the_equivalent_sigma_nears_one_pixel(ratio, bound_hu):
    """A Gaussian sampled on ~1 pixel is not exactly the DFT of a sampled Gaussian mask (aliasing); the gap is bounded."""
    assert np.abs(_fft_gaussian_vs_spatial(ratio)).max() < bound_hu


def test_physical_equivalents_for_the_real_series_geometry():
    eq = B.grid_physical_equivalents(0.54, 512)
    assert eq["kernel_size_mm"][5] == pytest.approx(2.7) and eq["gaussian_sigma_mm"][1.5] == pytest.approx(0.81)
    assert eq["nyquist_cycles_per_mm"] == pytest.approx(0.9259, abs=1e-4)
    assert eq["fft_cutoff"][0.15]["cycles_per_mm"] == pytest.approx(0.1389, abs=1e-4)
    assert eq["fft_cutoff"][0.15]["equivalent_gaussian_sigma_mm"] == pytest.approx(0.54 / (math.pi * 0.15), abs=1e-3)
    assert set(eq["kernel_size_mm"]) == set(B.KERNEL_GRID) and set(eq["fft_cutoff"]) == set(B.CUTOFF_GRID)


# --- primary SSIM (windows fully inside the mask) and the sensitivity definition ---------------------


def _padded_phantom(n=24, size=64, padding_from=50):
    """Phantom whose body is truncated by artificial padding (-2048 HU) on the right, as in the real series."""
    volume = phantom_volume(n=n, size=size)
    volume[:, :, padding_from:] = -2048.0
    return volume


def test_ssim_is_computed_with_windows_fully_inside_the_mask_by_default():
    import inspect

    assert inspect.signature(B.masked_ssim).parameters["fully_inside"].default is True
    assert B.SSIM_OPTIONS[False] == {} and B.SSIM_OPTIONS[True]["sigma"] == 1.5


@pytest.mark.parametrize("mask_name", ["main", "inner"])
def test_no_pixel_outside_the_mask_can_influence_any_evaluated_primary_score(mask_name):
    volume = _padded_phantom()
    case = B.make_case(volume[1], B.CONDITIONS[1], 3)
    output = B.filter_hu(case.noisy_hu, "Median", {"kernel_size": 5})
    mask = case.masks()[mask_name]
    disturbed = output.copy()
    disturbed[~mask] += np.random.default_rng(0).uniform(-400, 400, (~mask).sum())     # change ONLY pixels outside this mask
    before = B.evaluate_masks(case, output, (mask_name,))[mask_name]
    after = B.evaluate_masks(case, disturbed, (mask_name,))[mask_name]
    for key in ("RMSE_HU", "MAE_HU", "RMSE_windowed", "MAE_windowed", "PSNR_dB", "SSIM_skimage_default", "SSIM_Wang2004"):
        assert after[key] == pytest.approx(before[key], rel=1e-9, abs=1e-12), key
    for key in ("SSIM_skimage_default_allpixels", "SSIM_Wang2004_allpixels"):          # the earlier definition does leak
        assert abs(after[key] - before[key]) > 1e-5, key


def test_the_primary_and_the_sensitivity_ssim_columns_are_distinct_and_documented_by_their_names():
    volume = _padded_phantom()
    case = B.make_case(volume[1], B.CONDITIONS[1], 3)
    result = B.evaluate_masks(case, B.filter_hu(case.noisy_hu, "Mean", {"kernel_size": 5}), ("main",))["main"]
    assert result["SSIM_Wang2004"] != result["SSIM_Wang2004_allpixels"]
    assert set(B.METRIC_COLUMNS) >= {"SSIM_skimage_default", "SSIM_Wang2004", "SSIM_skimage_default_allpixels", "SSIM_Wang2004_allpixels"}
    assert result["ssim_pixels_default"] > result["ssim_pixels_wang"] > 0         # a larger window leaves fewer evaluable pixels


def test_one_recorded_row_of_a_run_is_reproduced_by_an_independent_computation():
    from skimage.metrics import structural_similarity

    volume = _padded_phantom()
    config = B.Config([6], [11, 15], tune_repeats=1, test_repeats=2, n_boot=100)
    tables = B.run_benchmark(volume, config, conditions=SMALL)
    per_run = tables["test_per_run"]
    row = per_run[(per_run.condition == "white_25HU") & (per_run.family == "Median") & (per_run["mask"] == "inner")
                  & (per_run["slice"] == 15) & (per_run.repeat == 2)].iloc[0]
    masks = B.reference_masks(volume[15].astype(float))
    case = B.make_case(volume[15], B.CONDITIONS[1], int(row["seed"]), masks=masks)
    output = B.filter_hu(case.noisy_hu, "Median", json.loads(row["params"]))
    ref_d, out_d = B.display(case.reference_hu), B.display(output)
    # independent: library SSIM map + own erosion of the inner mask by the window radius
    smap = structural_similarity(ref_d, out_d, data_range=1.0, full=True)[1]
    window = np.ones((7, 7), bool)
    interior = ndimage.binary_erosion(masks["inner"], structure=window, border_value=0)
    assert row["SSIM_skimage_default"] == pytest.approx(smap[interior].mean(), abs=1e-12)
    assert row["ssim_pixels_default"] == interior.sum()
    assert row["SSIM_skimage_default_allpixels"] == pytest.approx(smap[masks["inner"]].mean(), abs=1e-12)
    assert row["RMSE_HU"] == pytest.approx(np.sqrt(np.mean((output - case.reference_hu)[masks["inner"]] ** 2)), abs=1e-9)


def test_the_same_ssim_rule_and_pixel_counts_apply_to_every_filter_condition_and_repeat():
    volume = _padded_phantom()
    config = B.Config([6], [11, 15], tune_repeats=1, test_repeats=3, n_boot=100)
    tables = B.run_benchmark(volume, config, conditions=SMALL)
    per_run = tables["test_per_run"]
    for (slice_index, mask_name), group in per_run.groupby(["slice", "mask"]):
        mask = B.reference_masks(volume[slice_index].astype(float))[mask_name]
        assert set(group["ssim_pixels_default"]) == {int(B.ssim_interior_mask(mask, False).sum())}
        assert set(group["ssim_pixels_wang"]) == {int(B.ssim_interior_mask(mask, True).sum())}
        assert group["family"].nunique() == 7 and group["condition"].nunique() == 3


# --- the inner mask (sensitivity analysis of the field-of-view boundary) ------------------------------


def _truncated_reference(size=64, padding_from=44):
    hu = np.full((size, size), -1000.0)
    hu[8:56, 4:padding_from] = 20.0
    hu[:, padding_from:] = -2048.0
    return hu


def test_the_inner_mask_removes_exactly_the_band_within_ten_pixels_of_the_padding():
    hu = _truncated_reference()
    main, inner = B.evaluation_mask(hu), B.inner_mask(hu)
    assert B.INNER_MARGIN_PX == 10 and B.PADDING_HU == -1500.0
    assert (inner & ~main).sum() == 0 and inner.sum() < main.sum()
    rows = slice(8, 56)
    assert not inner[rows, 34:44].any(), "pixels at distance <= 10 from the padding (columns 34..43) must be excluded"
    assert inner[rows, 4:34].all(), "pixels at distance >= 11 must stay"
    assert (main[rows, 34:44]).all()                                    # they were in the principal mask


def test_the_inner_mask_uses_the_euclidean_distance_to_the_nearest_padding_pixel():
    hu = np.full((41, 41), 20.0)
    hu[20, 20] = -2048.0                                               # a single padding pixel in the middle of the body
    main = np.ones((41, 41), bool)
    inner = B.inner_mask(hu, main=main)
    yy, xx = np.mgrid[0:41, 0:41]
    assert np.array_equal(inner, np.hypot(yy - 20, xx - 20) > 10.0)


def test_without_padding_the_inner_mask_equals_the_principal_mask():
    hu = phantom_volume(n=3, size=64, lung_slices=range(3))[1]
    assert np.array_equal(B.inner_mask(hu), B.evaluation_mask(hu))


@pytest.mark.parametrize("condition", B.CONDITIONS, ids=[c.name for c in B.CONDITIONS])
def test_the_inner_mask_never_depends_on_the_noise(condition):
    volume = _padded_phantom()
    reference = volume[1].astype(float)
    for seed in (1, 2):
        case = B.make_case(volume[1], condition, seed)
        assert np.array_equal(case.inner_mask, B.inner_mask(reference)) and np.array_equal(case.mask, B.evaluation_mask(reference))


def test_both_masks_of_a_slice_are_computed_once_and_reused_for_every_output(monkeypatch):
    volume = _padded_phantom()
    config = B.Config([6], [11, 15], tune_repeats=2, test_repeats=2, n_boot=50)
    calls = []
    original = B.reference_masks
    monkeypatch.setattr(B, "reference_masks", lambda hu: calls.append(1) or original(hu))
    B.run_benchmark(volume, config, conditions=SMALL)
    assert len(calls) == 3                                               # one per slice (1 tuning + 2 test), not per case or output


def test_every_output_of_a_case_is_scored_on_the_same_two_mask_objects(monkeypatch):
    volume = _padded_phantom()
    case = B.make_case(volume[1], B.CONDITIONS[1], 5)
    seen = []
    original = B.hu_errors
    monkeypatch.setattr(B, "hu_errors", lambda ref, out, mask: seen.append(mask) or original(ref, out, mask))
    for family in (B.BASELINE, "Mean", "Median", "Gaussian", "FFT ideal", "FFT Gaussian", "FFT Butterworth"):
        B.evaluate_masks(case, B.filter_hu(case.noisy_hu, family, {"kernel_size": 5, "sigma": 1.0, "cutoff_ratio": 0.2}))
    main_calls = [m for m in seen if m is case.mask]
    inner_calls = [m for m in seen if m is case.inner_mask]
    # hu_errors serves both the HU errors and the windowed errors: 2 calls per output and per mask
    assert len(main_calls) == len(inner_calls) == 7 * 2 and len(seen) == 7 * 2 * 2


def test_the_boundary_band_dominates_the_error_of_linear_filters_on_the_main_mask_but_not_on_the_inner_mask():
    hu = np.full((96, 96), 20.0)                                       # soft tissue everywhere ...
    hu[:, :20] = -2048.0                                                # ... except artificial padding on both sides
    hu[:, 76:] = -2048.0
    masks = B.reference_masks(hu)
    case = B.Case(hu, hu, masks["main"], masks["inner"])               # no noise: the error is the filter's own blur
    output = B.filter_hu(hu, "FFT Gaussian", {"cutoff_ratio": 0.15})
    main_error = B.evaluate_output(case, output, full=False, mask_name="main")["RMSE_HU"]
    inner_error = B.evaluate_output(case, output, full=False, mask_name="inner")["RMSE_HU"]
    assert main_error > 10 * inner_error and inner_error < 1.0         # the whole error sits in the band next to the padding


def test_the_inner_mask_stays_large_on_every_slice_of_a_realistic_geometry():
    for volume in (phantom_volume(), _padded_phantom()):
        for index in (4, 11, 15, 19):
            masks = B.reference_masks(volume[index].astype(float))
            assert masks["inner"].sum() / masks["main"].sum() >= B.MIN_INNER_FRACTION


def test_a_run_refuses_a_test_slice_whose_inner_mask_would_be_too_small():
    volume = _padded_phantom(padding_from=20)                          # padding eats most of the body
    config = B.Config([6], [11, 15], tune_repeats=1, test_repeats=1, n_boot=50)
    with pytest.raises(ValueError, match="inner mask keeps only"):
        B.run_benchmark(volume, config, conditions=SMALL)


def test_mask_summary_reports_pixel_counts_the_removed_band_and_stable_fingerprints():
    volume = _padded_phantom()
    config = B.Config([6], [11, 15], tune_repeats=1, test_repeats=1, n_boot=50)
    summary = B.run_benchmark(volume, config, conditions=SMALL)["mask_summary"]
    assert list(summary["slice"]) == [6, 11, 15] and list(summary["role"]) == ["tuning", "test", "test"]
    assert (summary["band_removed_pixels"] == summary["main_pixels"] - summary["inner_pixels"]).all() and (summary["band_removed_pixels"] > 0).all()
    assert (summary["inner_fraction_of_main"] >= B.MIN_INNER_FRACTION).all()
    assert (summary["padding_pixels"] > 0).all() and (summary["ssim_pixels_wang_main"] < summary["ssim_pixels_default_main"]).all()
    again = B.mask_fingerprint(B.reference_masks(volume[11].astype(float))["main"])
    assert summary.loc[summary["slice"] == 11, "main_mask_sha256"].iloc[0] == again


def test_sensitivity_tables_compare_the_two_masks_and_the_two_ssim_definitions():
    volume = _padded_phantom()
    # grid v1 on purpose: every family smooths, so the boundary band matters (with the expanded grid the identity can win)
    config = B.Config([6], [11, 15], tune_repeats=1, test_repeats=2, n_boot=100, grid_version="v1")
    tables = B.run_benchmark(volume, config, conditions=SMALL)
    sens = tables["mask_sensitivity"]
    fft = sens[(sens.condition == "white_25HU") & (sens.family == "FFT Gaussian") & (sens.metric == "RMSE_HU")].iloc[0]
    assert fft["inner_mean"] < fft["main_mean"] and fft["inner_minus_main_mean"] == pytest.approx(fft["inner_mean"] - fft["main_mean"])
    ranking = tables["mask_ranking"]
    assert set(ranking["rank_main"]) <= set(range(1, 7)) and (ranking["rank_change"] == ranking["rank_inner"] - ranking["rank_main"]).all()
    ssim = tables["ssim_sensitivity"]
    assert set(ssim["ssim"]) == {"SSIM_skimage_default", "SSIM_Wang2004"} and set(ssim["mask"]) == {"main", "inner"}
    assert (ssim["allpixels_minus_primary_mean"] != 0).any()


def test_the_metadata_documents_the_inner_mask_as_an_experimental_choice():
    description = B.protocol_description()
    assert "EXPERIMENTAL" in description["inner_mask"]["status"] and "not clinically validated" in description["inner_mask"]["status"]
    assert description["inner_mask"]["margin_px"] == 10
    assert description["evaluation_mask"]["pixels_dropped_by_hu_value_or_window"] == 0


def test_parameters_are_tuned_on_the_principal_mask_only():
    base = np.full((96, 96), 20.0)                                      # smooth tissue: the only edge is the padding step
    base[:, :20] = -2048.0
    base[:, 76:] = -2048.0
    volume = np.broadcast_to(base, (24, 96, 96)).copy()
    condition = B.CONDITIONS[1]
    config = B.Config([6], [11], tune_repeats=2, test_repeats=1, n_boot=50)
    tables = B.run_benchmark(volume, config, conditions=(condition,))
    cases = [B.make_case(volume[6], condition, B.condition_seed(config.tune_base_seed, 6, 0, r)) for r in range(2)]

    def best_per_family(mask_name):
        chosen = {}
        for family, configs in B.parameter_grid().items():
            scores = [np.mean([B.hu_errors(c.reference_hu, B.filter_hu(c.noisy_hu, family, p), c.masks()[mask_name])[0] for c in cases])
                      for p in configs]
            chosen[family] = configs[int(np.argmin(scores))]
        return chosen

    on_main, on_inner = best_per_family("main"), best_per_family("inner")
    selected = {row.family: json.loads(row.params) for row in tables["selected_parameters"].itertuples()}
    assert selected == on_main
    assert on_main != on_inner, "precondition: the two masks must lead to different choices for this test to discriminate"


# --- the expanded tuning grid --------------------------------------------------------------------------

# The tuning grid of the first benchmark run, copied from its run_metadata.json (parameters.grid).
FIRST_RUN_GRID = {
    "FFT Butterworth": [{"cutoff_ratio": 0.05}, {"cutoff_ratio": 0.08}, {"cutoff_ratio": 0.1}, {"cutoff_ratio": 0.15}, {"cutoff_ratio": 0.2}, {"cutoff_ratio": 0.3}, {"cutoff_ratio": 0.4}],
    "FFT Gaussian": [{"cutoff_ratio": 0.05}, {"cutoff_ratio": 0.08}, {"cutoff_ratio": 0.1}, {"cutoff_ratio": 0.15}, {"cutoff_ratio": 0.2}, {"cutoff_ratio": 0.3}, {"cutoff_ratio": 0.4}],
    "FFT ideal": [{"cutoff_ratio": 0.05}, {"cutoff_ratio": 0.08}, {"cutoff_ratio": 0.1}, {"cutoff_ratio": 0.15}, {"cutoff_ratio": 0.2}, {"cutoff_ratio": 0.3}, {"cutoff_ratio": 0.4}],
    "Gaussian": [{"kernel_size": 5, "sigma": 0.5}, {"kernel_size": 7, "sigma": 0.75}, {"kernel_size": 7, "sigma": 1.0}, {"kernel_size": 11, "sigma": 1.5}, {"kernel_size": 13, "sigma": 2.0}, {"kernel_size": 19, "sigma": 3.0}],
    "Mean": [{"kernel_size": 3}, {"kernel_size": 5}, {"kernel_size": 7}, {"kernel_size": 9}, {"kernel_size": 11}],
    "Median": [{"kernel_size": 3}, {"kernel_size": 5}, {"kernel_size": 7}, {"kernel_size": 9}, {"kernel_size": 11}],
}
INITIAL_RUN_METADATA_ENV = "BENCHMARK_V2_INITIAL_RUN_METADATA"      # optional: path of that run_metadata.json
IDENTITIES = {"Mean": {"kernel_size": 1}, "Median": {"kernel_size": 1}, "Gaussian": {"sigma": 0.0, "kernel_size": 1},
              "FFT ideal": {"cutoff_ratio": None}, "FFT Gaussian": {"cutoff_ratio": None}, "FFT Butterworth": {"cutoff_ratio": None}}


def test_the_v1_grid_is_exactly_the_grid_of_the_first_run():
    assert B.parameter_grid("v1")["Mean"] == [{"kernel_size": k} for k in (3, 5, 7, 9, 11)]
    assert [c["sigma"] for c in B.parameter_grid("v1")["Gaussian"]] == [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    assert [c["cutoff_ratio"] for c in B.parameter_grid("v1")["FFT ideal"]] == [0.05, 0.08, 0.10, 0.15, 0.20, 0.30, 0.40]
    assert B.parameter_grid("v1") == FIRST_RUN_GRID                  # always evaluated, no external file needed


def assert_grid_matches_metadata_file(path: Path) -> None:
    assert path.is_file(), f"the run metadata file does not exist: {path}"
    recorded = json.loads(path.read_text(encoding="utf-8"))["parameters"]["grid"]
    assert recorded == FIRST_RUN_GRID, "FIRST_RUN_GRID differs from the grid recorded in that metadata file"
    assert B.parameter_grid("v1") == recorded


def test_the_v1_grid_matches_the_first_runs_metadata_file_when_one_is_provided():
    configured = os.environ.get(INITIAL_RUN_METADATA_ENV)
    if not configured:
        pytest.skip(f"optional external check: set {INITIAL_RUN_METADATA_ENV} to the first run's run_metadata.json "
                    "(the embedded copy FIRST_RUN_GRID is always compared)")
    assert_grid_matches_metadata_file(Path(configured))                # a wrong or missing file FAILS; it is never skipped


def test_the_metadata_comparison_detects_a_missing_file_and_a_different_grid(tmp_path):
    with pytest.raises(AssertionError, match="does not exist"):
        assert_grid_matches_metadata_file(tmp_path / "absent.json")
    changed = json.loads(json.dumps(FIRST_RUN_GRID)); changed["Mean"].append({"kernel_size": 13})
    different = tmp_path / "different.json"; different.write_text(json.dumps({"parameters": {"grid": changed}}), encoding="utf-8")
    with pytest.raises(AssertionError, match="differs"):
        assert_grid_matches_metadata_file(different)
    same = tmp_path / "same.json"; same.write_text(json.dumps({"parameters": {"grid": FIRST_RUN_GRID}}), encoding="utf-8")
    assert_grid_matches_metadata_file(same)


def test_an_unknown_grid_version_is_rejected():
    with pytest.raises(ValueError):
        B.parameter_grid("bigger")


@pytest.mark.parametrize("family", B.FAMILIES)
def test_the_expanded_grid_keeps_every_v1_value_and_adds_only_weaker_smoothing(family):
    v1, expanded = B.parameter_grid("v1")[family], B.parameter_grid("expanded")[family]
    keys = lambda configs: {json.dumps(c, sort_keys=True) for c in configs}
    assert keys(v1) <= keys(expanded)
    weakest_v1 = min(B.smoothing_strength(family, c) for c in v1)
    added = [c for c in expanded if json.dumps(c, sort_keys=True) not in keys(v1)]
    assert added and all(B.smoothing_strength(family, c) < weakest_v1 for c in added)         # nothing added at the strong end
    assert max(B.smoothing_strength(family, c) for c in expanded) == max(B.smoothing_strength(family, c) for c in v1)


@pytest.mark.parametrize("family", B.FAMILIES)
def test_the_expanded_grid_runs_from_the_identity_to_the_strongest_smoothing(family):
    configs = B.parameter_grid("expanded")[family]
    strengths = [B.smoothing_strength(family, c) for c in configs]
    assert configs[0] == IDENTITIES[family] and B.is_identity(family, configs[0])
    assert strengths == sorted(strengths) and len(set(strengths)) == len(strengths) and strengths[0] == 0.0
    assert sum(B.is_identity(family, c) for c in configs) == 1


def test_smoothing_strength_goes_up_with_kernel_and_sigma_but_down_with_the_fft_cutoff():
    assert B.smoothing_strength("Mean", {"kernel_size": 5}) > B.smoothing_strength("Mean", {"kernel_size": 3})
    assert B.smoothing_strength("Gaussian", {"sigma": 1.0, "kernel_size": 7}) > B.smoothing_strength("Gaussian", {"sigma": 0.5, "kernel_size": 5})
    assert B.smoothing_strength("FFT Gaussian", {"cutoff_ratio": 0.1}) > B.smoothing_strength("FFT Gaussian", {"cutoff_ratio": 0.4})
    assert B.smoothing_strength("FFT Gaussian", {"cutoff_ratio": 4.0}) > B.smoothing_strength("FFT Gaussian", {"cutoff_ratio": None}) == 0.0


def test_gaussian_kernels_stay_wide_enough_for_their_sigma_and_odd():
    for config in B.parameter_grid("expanded")["Gaussian"]:
        assert config["kernel_size"] % 2 == 1 and config["kernel_size"] >= 6 * config["sigma"]


@pytest.mark.parametrize("family", B.FAMILIES)
def test_the_identity_configuration_leaves_the_image_and_the_hu_values_unchanged(family):
    image = _test_image(3)
    assert np.allclose(B.apply_filter(image, family, IDENTITIES[family], clip=False), image, atol=1e-12)
    hu = np.random.default_rng(2).uniform(-2048, 3000, (48, 48))
    np.testing.assert_allclose(B.filter_hu(hu, family, IDENTITIES[family]), hu, atol=1e-8)


def test_gaussian_sigma_zero_is_the_identity_here_whereas_opencv_would_read_it_as_automatic():
    image = _test_image(4)
    opencv_auto = cv2.GaussianBlur(image, (5, 5), sigmaX=0.0, borderType=cv2.BORDER_REFLECT101)
    assert np.abs(opencv_auto - image).max() > 1e-3                                  # why an explicit identity is needed
    assert np.array_equal(B.apply_filter(image, "Gaussian", {"sigma": 0.0, "kernel_size": 5}, clip=False), image)


def test_the_ideal_lowpass_is_exactly_the_identity_from_sqrt_two_and_not_before():
    image = _test_image(5)[:64, :64]
    assert np.abs(B.apply_filter(image, "FFT ideal", {"cutoff_ratio": 1.41}, clip=False) - image).max() > 1e-6     # corners still cut
    assert np.abs(B.apply_filter(image, "FFT ideal", {"cutoff_ratio": 1.42}, clip=False) - image).max() < 1e-12
    assert np.abs(B.apply_filter(image, "FFT ideal", {"cutoff_ratio": 1.5}, clip=False) - image).max() < 1e-12


@pytest.mark.parametrize("family", ["FFT Gaussian", "FFT Butterworth"])
def test_gaussian_and_butterworth_lowpass_approach_the_identity_as_the_cutoff_grows(family):
    image = _test_image(6)
    rms = lambda c: float(np.sqrt(np.mean((B.apply_filter(image, family, {"cutoff_ratio": c}, clip=False) - image) ** 2)))
    errors = [rms(c) for c in (0.5, 1.0, 2.0, 3.0, 4.0)]
    assert errors == sorted(errors, reverse=True)                       # monotone approach to the identity
    assert errors[-1] < 0.02 * image.std() and errors[0] > 10 * errors[-1]


@pytest.mark.parametrize("kind", ["ideal", "gauss", "butterworth"])
@pytest.mark.parametrize("ratio", [0.05, 0.15, 0.4, 0.8])
def test_the_local_fft_lowpass_equals_the_shared_implementation_inside_its_range(kind, ratio):
    image = 0.3 + 0.4 * _test_image(7)                                                # stays inside [0, 1] so no clipping differs
    shared = filters.apply_frequency_lowpass(image, cutoff_ratio=ratio, filter_type=kind, order=2)[0] if ratio < 1 else None
    local = B.fft_lowpass(image, ratio, kind)
    if shared is not None:
        np.testing.assert_allclose(np.clip(local, 0, 1), shared, atol=1e-12)
    assert local.shape == image.shape and np.isfinite(local).all()


@pytest.mark.parametrize("bad", [0.0, -0.1, float("nan"), float("inf")])
def test_the_local_fft_lowpass_validates_the_cutoff_and_the_kind(bad):
    with pytest.raises(ValueError):
        B.fft_lowpass(_test_image(), bad, "gauss")
    with pytest.raises(ValueError):
        B.fft_lowpass(_test_image(), 0.3, "box")


def _tuning_rows(family, scores, strengths_params):
    return pd.DataFrame([{"condition": "c", "family": family, "params": json.dumps(p, sort_keys=True), "mean_score": s,
                          "mean_PSNR_dB": 0.0, "mean_SSIM_Wang2004": 0.0, "n_tuning_cases": 1} for p, s in zip(strengths_params, scores)])


def _selected(grid_table, family, params):
    return pd.DataFrame([{"condition": "c", "family": family, "params": json.dumps(params, sort_keys=True)}])


@pytest.mark.parametrize("scores, pick, kernels, status, bracketed", [
    ([5.0, 4.0, 3.0, 4.0, 6.0], 2, [1, 3, 5, 7, 9], "interior", True),
    ([3.0, 4.0, 5.0, 6.0, 7.0], 0, [1, 3, 5, 7, 9], "identity", True),
    ([3.0, 4.0, 5.0, 6.0, 7.0], 0, [3, 5, 7, 9, 11], "weakest_end", False),          # a grid without the identity: not bracketed
    ([7.0, 6.0, 5.0, 4.0, 3.0], 4, [1, 3, 5, 7, 9], "strongest_end", False),
])
def test_bracketing_classifies_where_the_minimum_sits_in_the_ordered_grid(scores, pick, kernels, status, bracketed):
    params = [{"kernel_size": k} for k in kernels]
    table = _tuning_rows("Mean", scores, params)
    result = B.grid_bracketing(_selected(table, "Mean", params[pick]), table).iloc[0]
    assert result["status"] == status and bool(result["bracketed"]) is bracketed
    assert result["grid_size"] == 5 and result["position"] == pick + 1
    expected_weaker = scores[pick - 1] if pick > 0 else None
    assert (math.isnan(result["weaker_neighbour_score"]) if expected_weaker is None else result["weaker_neighbour_score"] == expected_weaker)


def test_bracketing_orders_fft_cutoffs_from_large_to_small_cutoff():
    params = [{"cutoff_ratio": None}, {"cutoff_ratio": 2.0}, {"cutoff_ratio": 0.5}, {"cutoff_ratio": 0.1}]
    table = _tuning_rows("FFT Gaussian", [9.0, 8.0, 7.0, 8.5], params).sample(frac=1, random_state=1)     # row order must not matter
    result = B.grid_bracketing(_selected(table, "FFT Gaussian", {"cutoff_ratio": 0.5}), table).iloc[0]
    assert result["status"] == "interior" and result["position"] == 3
    assert result["weaker_neighbour_score"] == 8.0 and result["stronger_neighbour_score"] == 8.5


def test_the_criteria_comparison_only_reports_where_psnr_and_ssim_would_choose_differently():
    params = [{"kernel_size": k} for k in (1, 3, 5)]
    table = _tuning_rows("Mean", [3.0, 2.0, 4.0], params)
    table["mean_PSNR_dB"] = [40.0, 41.0, 39.0]            # agrees with the RMSE choice (kernel 3)
    table["mean_SSIM_Wang2004"] = [0.90, 0.92, 0.97]      # prefers the strongest smoothing (kernel 5)
    row = B.tuning_criteria_comparison(table).iloc[0]
    assert json.loads(row["selected_by_RMSE_HU"]) == {"kernel_size": 3}
    assert row["PSNR_agrees"] and not row["SSIM_agrees"] and json.loads(row["best_by_SSIM_Wang2004"]) == {"kernel_size": 5}


def test_the_selection_criterion_is_still_the_rmse_in_hu_and_the_other_metrics_never_decide(monkeypatch):
    volume = _padded_phantom()
    cases = [B.make_case(volume[6], B.CONDITIONS[1], 1)]
    table, selected = B.tune_condition(cases, B.CONDITIONS[1], {"Mean": [{"kernel_size": 1}, {"kernel_size": 3}, {"kernel_size": 7}]})
    assert B.TUNING_CRITERION == "RMSE_HU" and set(table["criterion"]) == {"RMSE_HU"}
    best = table.loc[table["mean_score"].idxmin(), "params"]
    assert selected["Mean"] == json.loads(best)
    assert {"mean_PSNR_dB", "mean_SSIM_Wang2004"} <= set(table.columns)
    table["mean_SSIM_Wang2004"] = np.arange(len(table))[::-1]                          # whatever SSIM says, the choice is the RMSE argmin
    assert selected["Mean"] == json.loads(table.loc[table["mean_score"].idxmin(), "params"])


def test_an_exact_tie_goes_to_the_weaker_smoothing_because_the_grid_is_ordered_weakest_first(monkeypatch):
    monkeypatch.setattr(B, "evaluate_output", lambda case, output, full=True, mask_name="main": {"RMSE_HU": 1.0, "MAE_HU": 1.0})
    monkeypatch.setattr(B, "tuning_secondary_metrics", lambda case, output: (0.0, 0.0))
    case = B.make_case(_padded_phantom()[6], B.CONDITIONS[1], 1)
    _, selected = B.tune_condition([case], B.CONDITIONS[1], B.parameter_grid("expanded"))
    assert all(selected[family] == IDENTITIES[family] for family in B.FAMILIES)


def test_a_run_with_the_expanded_grid_records_bracketing_and_the_identity_equals_the_unfiltered_image():
    volume = _padded_phantom()
    low_noise = B.Condition("tiny_noise", "d", "white", "main", sigma_hu=2.0)          # smoothing should cost more than it gains
    config = B.Config([6], [11, 15], tune_repeats=2, test_repeats=2, n_boot=100)
    tables = B.run_benchmark(volume, config, conditions=(low_noise,))
    grid_rows = tables["tuning_grid"]
    assert config.grid_version == "expanded" and len(grid_rows) == sum(len(v) for v in B.parameter_grid("expanded").values())
    bracketing = tables["grid_bracketing"]
    assert set(bracketing["status"]) <= {"identity", "interior", "weakest_end", "strongest_end"} and len(bracketing) == 6
    identity_families = list(bracketing.loc[bracketing["status"] == "identity", "family"])
    assert identity_families, "precondition: with 2 HU of noise at least one family must select the identity"
    per_run = tables["test_per_run"]
    for family in identity_families:
        for mask in ("main", "inner"):
            a = per_run[(per_run.family == family) & (per_run["mask"] == mask)].sort_values(["slice", "repeat"])
            b = per_run[(per_run.family == B.BASELINE) & (per_run["mask"] == mask)].sort_values(["slice", "repeat"])
            for column in ("RMSE_HU", "MAE_HU", "PSNR_dB", "SSIM_Wang2004", "SSIM_skimage_default"):
                np.testing.assert_allclose(a[column].to_numpy(), b[column].to_numpy(), atol=1e-8)


def test_the_grid_version_and_bracketing_summary_are_recorded_in_the_metadata(tmp_path):
    series = _write_dicom_series(tmp_path / "series", phantom_volume(n=24, size=40))
    out = tmp_path / "out"
    B.main(["--dicom-series", str(series), "--out", str(out), "--n-tune", "1", "--n-test", "3", "--min-gap", "2",
            "--tune-repeats", "1", "--test-repeats", "1", "--n-boot", "50", "--grid-version", "v1"])
    meta = json.loads((out / "run_metadata.json").read_text(encoding="utf-8"))
    assert meta["parameters"]["grid_version"] == "v1" and meta["parameters"]["grid"] == B.parameter_grid("v1")
    assert meta["parameters"]["selection_criterion"] == "RMSE_HU"
    assert sum(meta["grid_bracketing_summary"].values()) == len(B.CONDITIONS) * 6
    assert "never select" in meta["grid_note"]
    assert len(pd.read_csv(out / "tuning_grid.csv")) == len(B.CONDITIONS) * sum(len(v) for v in B.parameter_grid("v1").values())
    assert {"grid_bracketing.csv", "tuning_criteria_comparison.csv"} <= {p.name for p in out.iterdir()}
