"""Tests for the bilateral, non-local-means and wavelet denoisers of ``filters.py``.

Expected values come from definitions and invariances (a constant stays constant, a huge intensity
scale makes the bilateral filter a Gaussian, an affine change of units commutes with the filter when
its strength is expressed in the same units), not from the function under test.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from skimage.restoration import denoise_wavelet

import filters as F


def noisy_disc(size=48, sigma=0.05, seed=3):
    """A bright disc on a dark background with Gaussian noise; returns (clean, noisy)."""
    yy, xx = np.mgrid[0:size, 0:size]
    clean = np.where(np.hypot(yy - size / 2, xx - size / 2) < size * 0.3, 0.7, 0.3)
    return clean, clean + np.random.default_rng(seed).normal(0, sigma, clean.shape)


def rmse(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


FILTERS = {
    "bilateral": lambda image, s: F.bilateral_filter(image, s, 1.5),
    "nlm": lambda image, s: F.non_local_means_filter(image, s),
    "wavelet": lambda image, s: F.wavelet_shrinkage_filter(image, s, levels=2),
}


# --- properties every denoiser must have -----------------------------------------------


@pytest.mark.parametrize("name", FILTERS)
@pytest.mark.parametrize("value", [0.0, 0.37, -2.5, 1000.0])
def test_a_constant_image_is_returned_unchanged(name, value):
    image = np.full((48, 56), value)
    np.testing.assert_allclose(FILTERS[name](image, 0.05), image, rtol=2e-6, atol=1e-5)   # float32 arithmetic in OpenCV


@pytest.mark.parametrize("name", FILTERS)
def test_shape_is_kept_float64_and_the_input_is_not_modified(name):
    _, noisy = noisy_disc(size=48)
    rectangular = noisy[:44, :]
    before = rectangular.copy()
    out = FILTERS[name](rectangular, 0.08)
    assert out.shape == rectangular.shape and out.dtype == np.float64
    np.testing.assert_array_equal(rectangular, before)


@pytest.mark.parametrize("name", FILTERS)
def test_results_are_deterministic(name):
    _, noisy = noisy_disc()
    np.testing.assert_array_equal(FILTERS[name](noisy, 0.08), FILTERS[name](noisy.copy(), 0.08))


@pytest.mark.parametrize("name, strength", [("bilateral", 0.15), ("nlm", 0.06), ("wavelet", 0.05)])
def test_each_denoiser_lowers_the_error_of_a_noisy_piecewise_constant_image(name, strength):
    clean, noisy = noisy_disc(sigma=0.05)
    assert rmse(FILTERS[name](noisy, strength), clean) < 0.75 * rmse(noisy, clean)


@pytest.mark.parametrize("name, tiny", [("bilateral", 1e-9), ("nlm", 1e-9), ("wavelet", 1e-9)])
def test_a_vanishing_strength_approaches_the_identity(name, tiny):
    _, noisy = noisy_disc()
    np.testing.assert_allclose(FILTERS[name](noisy, tiny), noisy, atol=1e-4)


@pytest.mark.parametrize("name", FILTERS)
@pytest.mark.parametrize("gain, offset", [(1.0, 0.0), (2.5, 0.0), (0.4, 1.7), (12288.0, -4096.0)])
def test_an_affine_change_of_units_commutes_with_the_filter_when_the_strength_is_scaled(name, gain, offset):
    # The HU benchmark filters a linear normalisation of the HU image and expresses every strength in HU,
    # so this invariance is what makes filtering the normalised image equal to filtering in HU.
    _, noisy = noisy_disc()
    strength = 0.08
    base = FILTERS[name](noisy, strength)
    scaled = FILTERS[name](gain * noisy + offset, gain * strength)
    np.testing.assert_allclose(scaled, gain * base + offset, atol=2e-4 * max(gain, 1.0) + 1e-4 * abs(offset))


# --- bilateral filter ------------------------------------------------------------------


def test_bilateral_with_a_huge_intensity_scale_is_a_disc_truncated_gaussian_of_the_spatial_scale():
    # With an enormous intensity scale every intensity weight is 1, so only the spatial weights remain:
    # exp(-r^2 / 2 sigma^2) inside a disc of radius d // 2 (the support OpenCV uses), normalised, reflected borders.
    from scipy import ndimage

    _, noisy = noisy_disc()
    sigma_space = 1.5
    radius = (2 * int(np.ceil(3 * sigma_space)) + 1) // 2
    dy, dx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    r = np.hypot(dy, dx)
    kernel = np.where(r <= radius, np.exp(-(r**2) / (2 * sigma_space**2)), 0.0)
    kernel /= kernel.sum()
    expected = ndimage.correlate(noisy, kernel, mode="mirror")
    np.testing.assert_allclose(F.bilateral_filter(noisy, 1e6, sigma_space), expected, atol=2e-5)


def test_bilateral_keeps_a_strong_edge_that_a_gaussian_of_the_same_spatial_scale_blurs():
    step = np.zeros((32, 32))
    step[:, 16:] = 1.0
    noisy = step + np.random.default_rng(0).normal(0, 0.02, step.shape)
    bilateral = F.bilateral_filter(noisy, 0.1, 2.0)
    gaussian = cv2.GaussianBlur(noisy, (13, 13), 2.0, borderType=cv2.BORDER_REFLECT101)
    jump = lambda image: float(image[:, 17:20].mean() - image[:, 12:15].mean())
    assert jump(bilateral) > 0.97
    assert jump(gaussian) < 0.85


def test_bilateral_window_diameter_follows_the_documented_rule(monkeypatch):
    seen = {}
    real = cv2.bilateralFilter

    def spy(src, d, sigma_color, sigma_space, *args, **kwargs):
        seen.update(d=d, sigma_color=sigma_color, sigma_space=sigma_space, dtype=src.dtype)
        return real(src, d, sigma_color, sigma_space, *args, **kwargs)

    monkeypatch.setattr(cv2, "bilateralFilter", spy)
    F.bilateral_filter(np.zeros((16, 16)), 0.1, 2.0)
    assert seen == {"d": 13, "sigma_color": 0.1, "sigma_space": 2.0, "dtype": np.float32}


@pytest.mark.parametrize("sigma_color, sigma_space", [(0.0, 1.0), (-1.0, 1.0), (float("nan"), 1.0), (float("inf"), 1.0),
                                                     (0.1, 0.0), (0.1, -1.0), (0.1, F.BILATERAL_MAX_SIGMA_SPACE + 1)])
def test_bilateral_rejects_invalid_scales(sigma_color, sigma_space):
    with pytest.raises(ValueError):
        F.bilateral_filter(np.zeros((16, 16)), sigma_color, sigma_space)


# --- non-local means -------------------------------------------------------------------


def test_nlm_averages_repeated_patterns_better_than_a_local_mean_of_the_same_footprint():
    # Vertical stripes: every column is a copy of the pattern two columns away, which a local box filter mixes up
    # while a patch-based average does not.
    pattern = np.tile(np.array([0.2, 0.2, 0.8, 0.8]), 12)
    clean = np.tile(pattern, (48, 1))
    noisy = clean + np.random.default_rng(1).normal(0, 0.1, clean.shape)
    nlm = F.non_local_means_filter(noisy, 0.12)
    box = cv2.boxFilter(noisy, -1, (5, 5), borderType=cv2.BORDER_REFLECT101)
    assert rmse(nlm, clean) < rmse(box, clean)
    assert rmse(nlm, clean) < 0.7 * rmse(noisy, clean)


@pytest.mark.parametrize("h", [0.0, -0.1, float("nan"), float("inf")])
def test_nlm_rejects_invalid_h(h):
    with pytest.raises(ValueError):
        F.non_local_means_filter(np.zeros((16, 16)), h)


@pytest.mark.parametrize("patch_size, patch_distance", [(4, 6), (0, 6), (5, 0), (17, 6), (5, 16), (5.5, 6), (True, 6)])
def test_nlm_rejects_invalid_patch_settings(patch_size, patch_distance):
    with pytest.raises(ValueError):
        F.non_local_means_filter(np.zeros((16, 16)), 0.1, patch_size, patch_distance)


def test_nlm_is_the_documented_library_call(monkeypatch):
    import skimage.restoration as restoration

    seen = {}

    def spy(image, **kwargs):
        seen.update(kwargs)
        return image

    monkeypatch.setattr(restoration, "denoise_nl_means", spy)
    F.non_local_means_filter(np.zeros((16, 16)), 0.07, 5, 6)
    assert seen == dict(patch_size=5, patch_distance=6, h=0.07, fast_mode=True, sigma=0.0, preserve_range=True)


# --- wavelet shrinkage -----------------------------------------------------------------


def test_wavelet_without_shifts_is_the_plain_bayesshrink_call():
    _, noisy = noisy_disc()
    expected = denoise_wavelet(noisy, sigma=0.06, wavelet="sym4", mode="soft", wavelet_levels=2, method="BayesShrink", rescale_sigma=True)
    np.testing.assert_allclose(F.wavelet_shrinkage_filter(noisy, 0.06, levels=2, max_shifts=0), expected, atol=1e-12)


def test_wavelet_with_shifts_is_the_mean_of_the_unshifted_results_over_all_circular_shifts():
    _, noisy = noisy_disc(size=32)
    total = np.zeros_like(noisy)
    for dy in range(3):
        for dx in range(3):
            shifted = np.roll(noisy, (dy, dx), axis=(0, 1))
            out = denoise_wavelet(shifted, sigma=0.06, wavelet="sym4", mode="soft", wavelet_levels=2, method="BayesShrink", rescale_sigma=True)
            total += np.roll(out, (-dy, -dx), axis=(0, 1))
    np.testing.assert_allclose(F.wavelet_shrinkage_filter(noisy, 0.06, levels=2, max_shifts=2), total / 9, atol=1e-12)


def test_shift_averaging_lowers_the_error_of_the_decimated_transform():
    clean, noisy = noisy_disc(sigma=0.08)
    shifted = F.wavelet_shrinkage_filter(noisy, 0.08, levels=2, max_shifts=3)
    decimated = F.wavelet_shrinkage_filter(noisy, 0.08, levels=2, max_shifts=0)
    assert rmse(shifted, clean) < rmse(decimated, clean)


@pytest.mark.parametrize("shape", [(50, 37), (33, 64), (16, 16)])
def test_wavelet_handles_sizes_that_are_not_powers_of_two(shape):
    assert F.wavelet_max_level(shape) >= 1
    image = np.random.default_rng(2).normal(0.5, 0.05, shape)
    assert F.wavelet_shrinkage_filter(image, 0.05, levels=1, max_shifts=1).shape == shape


def test_wavelet_refuses_a_level_deeper_than_the_image_supports():
    image = np.zeros((32, 32))
    deepest = F.wavelet_max_level(image.shape, "sym4")
    assert deepest == 2
    F.wavelet_shrinkage_filter(image, 0.1, levels=deepest, max_shifts=0)
    with pytest.raises(ValueError, match="too deep"):
        F.wavelet_shrinkage_filter(image, 0.1, levels=deepest + 1, max_shifts=0)


@pytest.mark.parametrize("kwargs", [dict(sigma=0.0), dict(sigma=-1.0), dict(sigma=float("nan")), dict(sigma=0.1, wavelet="nope"),
                                    dict(sigma=0.1, levels=0), dict(sigma=0.1, levels=7), dict(sigma=0.1, levels=2.5),
                                    dict(sigma=0.1, max_shifts=-1), dict(sigma=0.1, max_shifts=8), dict(sigma=0.1, max_shifts=True)])
def test_wavelet_rejects_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        F.wavelet_shrinkage_filter(np.zeros((16, 16)), **kwargs)


# --- image validation shared by the three denoisers ------------------------------------


@pytest.mark.parametrize("name", FILTERS)
@pytest.mark.parametrize("bad", [np.zeros((16,)), np.zeros((4, 16, 16)), np.zeros((7, 16)), np.zeros((16, 3)),
                                 np.full((16, 16), np.nan), np.full((16, 16), np.inf), [[0.0] * 16] * 16])
def test_invalid_images_are_rejected(name, bad):
    with pytest.raises(ValueError):
        FILTERS[name](bad, 0.1)
