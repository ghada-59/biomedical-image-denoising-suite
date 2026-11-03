"""The measurements of diagnostics.py, checked on synthetic volumes whose right answer is known."""

from __future__ import annotations

import numpy as np
import pytest

import benchmark_v2 as b2
import diagnostics as dg

SIZE = 160
RADIUS = 70
SLICES = 12


def _body_volume(noise: np.ndarray) -> np.ndarray:
    """A disc of 40 HU (soft tissue) on -1000 HU, plus ``noise`` of shape (slices, size, size)."""
    y, x = np.ogrid[:SIZE, :SIZE]
    disc = (x - SIZE / 2) ** 2 + (y - SIZE / 2) ** 2 <= RADIUS**2
    base = np.where(disc, 40.0, -1000.0)
    return base[None] + noise


def _independent_noise(seed: int, sd: float = 6.0) -> np.ndarray:
    return sd * np.random.default_rng(seed).standard_normal((SLICES + 1, SIZE, SIZE))


def test_independent_noise_gives_no_correlation_between_slices():
    result = dg.cross_slice_residual_correlation(_body_volume(_independent_noise(1)[:SLICES]), distances=(1, 2, 3))
    for d, row in result.items():
        assert row["pairs"] >= 5, d
        assert abs(row["mean"]) < 0.05, (d, row)


def test_noise_shared_by_neighbouring_slices_shows_up_at_distance_one_only():
    e = _independent_noise(2)
    shared = (e[:-1] + e[1:]) / np.sqrt(2.0)          # slice k and k + 1 share half of their noise: correlation 0.5, and 0 beyond
    result = dg.cross_slice_residual_correlation(_body_volume(shared), distances=(1, 2, 3))
    assert 0.4 < result[1]["mean"] < 0.6
    assert abs(result[2]["mean"]) < 0.05 and abs(result[3]["mean"]) < 0.05


def test_a_slice_pair_without_enough_homogeneous_tissue_is_not_used():
    volume = _body_volume(_independent_noise(3)[:SLICES])
    result = dg.cross_slice_residual_correlation(volume, distances=(1,), min_pixels=10**9)
    assert result[1]["pairs"] == 0 and np.isnan(result[1]["mean"])


def test_the_in_plane_profile_tells_white_noise_from_smoothed_noise():
    volume = _body_volume(np.zeros((4, SIZE, SIZE)))
    regions = [b2.soft_tissue_region(s) for s in volume]
    white = [b2.hu_noise((SIZE, SIZE), 20.0, "white", seed) for seed in range(4)]
    smooth = [b2.hu_noise((SIZE, SIZE), 20.0, "correlated", seed, correlation_sigma_px=1.0) for seed in range(4)]
    p_white = dg.inplane_residual_autocorrelation(white, regions, shifts=(1, 2))
    p_smooth = dg.inplane_residual_autocorrelation(smooth, regions, shifts=(1, 2))
    assert -0.72 < p_white[1] < -0.62 and 0.10 < p_white[2] < 0.24        # the Immerkaer kernel alone makes white noise anti-correlated at 1 px
    assert p_smooth[1] > 0.0 and p_smooth[2] < -0.4                       # a 1 px smoothing changes the whole profile
    assert p_smooth[1] - p_white[1] > 0.6


@pytest.mark.parametrize("bad", [np.zeros((5, 5)), np.zeros((1, 8, 8))])
def test_volumes_that_are_not_3d_stacks_are_rejected(bad):
    with pytest.raises(ValueError):
        dg.cross_slice_residual_correlation(bad)


def test_non_positive_distances_are_rejected():
    with pytest.raises(ValueError):
        dg.cross_slice_residual_correlation(_body_volume(_independent_noise(4)[:SLICES]), distances=(0,))


def test_the_report_has_the_real_profile_and_every_simulated_one():
    volume = _body_volume(_independent_noise(5)[:SLICES])
    report = dg.noise_texture_report(volume, slices=range(0, SLICES), shifts=(1, 2))
    labels = list(report["in_plane"])
    assert labels[0] == "real series" and "white noise" in labels and any("as in Benchmark V2" in label for label in labels)
    assert set(report["cross_slice"]) == {1, 2, 3, 5}
    assert report["in_plane"]["real series"][1] < -0.5                      # the synthetic series is white noise
    assert report["in_plane"]["real series"][1] == pytest.approx(report["in_plane"]["white noise"][1], abs=0.05)
    half_px = report["in_plane"]["smoothed, sigma 0.5 px"][1]
    shipped_px = report["in_plane"]["smoothed, sigma 1 px (as in Benchmark V2)"][1]
    assert shipped_px - half_px > 0.5                                       # a wider smoothing must give a clearly different profile


def test_bootstrap_coverage_for_eight_values_is_below_nominal_but_close_for_normal_data():
    draw, mean = dg.DISTRIBUTIONS["normal"]
    coverage = dg.bootstrap_coverage(draw, mean, n=8, reps=800, n_boot=500, seed=7)
    assert 0.84 < coverage < 0.94
    assert coverage == dg.bootstrap_coverage(draw, mean, n=8, reps=800, n_boot=500, seed=7)       # same seed, same answer
    skew_draw, skew_mean = dg.DISTRIBUTIONS["skewed (lognormal, sigma 1)"]
    assert dg.bootstrap_coverage(skew_draw, skew_mean, n=8, reps=800, n_boot=500, seed=7) < coverage - 0.05


def test_bootstrap_coverage_improves_with_more_values():
    draw, mean = dg.DISTRIBUTIONS["normal"]
    assert dg.bootstrap_coverage(draw, mean, n=40, reps=600, n_boot=400, seed=3) > dg.bootstrap_coverage(draw, mean, n=4, reps=600, n_boot=400, seed=3)


@pytest.mark.parametrize("kwargs", [{"n": 1}, {"reps": 0}, {"n_boot": 0}])
def test_bootstrap_coverage_rejects_impossible_settings(kwargs):
    draw, mean = dg.DISTRIBUTIONS["normal"]
    with pytest.raises(ValueError):
        dg.bootstrap_coverage(draw, mean, **kwargs)


# ---- the error carried by the edge of the body mask ---------------------------------------------------------------------------------


def _reference_slice() -> np.ndarray:
    return _body_volume(np.zeros((1, SIZE, SIZE)))[0]


def test_a_blurred_edge_puts_nearly_all_of_the_error_in_the_band_along_the_mask_edge():
    from scipy import ndimage
    reference = _reference_slice()
    result = dg.edge_band_error(reference, ndimage.uniform_filter(reference, size=3))
    assert result["band_squared_error_share"] > 0.99                       # the clean disc is flat: only its edge changes
    assert result["band_pixel_share"] < 0.12
    # all the squared error lies in the band, so RMSE_band^2 * share = RMSE_mask^2 (a few per cent are lost where the band meets the image edge)
    assert result["band_rmse_hu"] == pytest.approx(result["mask_rmse_hu"] / np.sqrt(result["band_pixel_share"]), rel=0.02)


def test_a_uniform_error_is_shared_between_the_band_and_the_rest_in_proportion_to_their_area():
    reference = _reference_slice()
    result = dg.edge_band_error(reference, reference + 10.0)
    assert result["band_rmse_hu"] == pytest.approx(10.0) and result["mask_rmse_hu"] == pytest.approx(10.0)
    assert result["band_squared_error_share"] == pytest.approx(result["band_pixel_share"])


def test_an_exact_output_has_no_error_share_and_bad_inputs_are_rejected():
    reference = _reference_slice()
    assert np.isnan(dg.edge_band_error(reference, reference.copy())["band_squared_error_share"])
    with pytest.raises(ValueError):
        dg.edge_band_error(reference, reference, width_px=0)
    with pytest.raises(ValueError):
        dg.edge_band_error(reference, reference[:-1])


def test_the_band_report_orders_a_stronger_smoothing_above_a_lighter_one():
    volume = _body_volume(np.zeros((3, SIZE, SIZE)))
    rows = {row["setting"]: row for row in dg.edge_band_report(volume, [0, 1, 2], noise_hu=25.0)}
    mean3, mean5 = rows["Mean {'kernel_size': 3}"], rows["Mean {'kernel_size': 5}"]
    assert len(rows) == 3 and mean3["slices"] == 3
    assert mean5["band_rmse_hu"][1] > mean3["band_rmse_hu"][1]
    for row in rows.values():
        low, middle, high = row["band_squared_error_share"]
        assert 0.0 < low <= middle <= high <= 1.0
