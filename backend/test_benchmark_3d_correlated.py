"""Benchmark 3D with noise correlated between adjacent slices (benchmark_3d_correlated.py): the statistics of the noise it claims to generate,
the way it plugs into benchmark_3d, and its guards."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import benchmark_3d as b3
import benchmark_3d_correlated as b3c
import benchmark_v2 as b2

SPACING = (0.7, 0.7, 3.0)
SHAPE = (30, 96, 96)


def _lag_correlation(noise: np.ndarray, axis: int, lag: int) -> float:
    a = np.moveaxis(noise, axis, 0)
    return float(np.corrcoef(a[:-lag].ravel(), a[lag:].ravel())[0, 1])


@pytest.mark.parametrize("correlation", [0.0, 0.1, 0.3, 0.5])
def test_the_mixing_weight_solves_the_correlation_equation(correlation):
    c = b3c.mixing_weight(correlation)
    assert c / (1.0 + c * c) == pytest.approx(correlation, abs=1e-12)
    assert 0.0 <= c <= 1.0


@pytest.mark.parametrize("bad", [-0.01, 0.51, float("nan"), 1.0])
def test_a_correlation_that_the_construction_cannot_give_is_refused(bad):
    with pytest.raises(ValueError):
        b3c.mixing_weight(bad)
    with pytest.raises(ValueError):
        with b3c.correlated_noise(bad):
            pass


def test_the_noise_has_the_requested_sd_the_requested_slice_correlation_and_nothing_else():
    noise = b3c.slice_correlated_noise(SHAPE, 20.0, seed=3, correlation=0.3)
    assert noise.shape == SHAPE and noise.dtype == np.float64
    assert noise.std() == pytest.approx(20.0, rel=0.02) and abs(noise.mean()) < 0.5
    for k in (0, 14, SHAPE[0] - 1):                                              # every slice, the first and the last included, has the same SD
        assert noise[k].std() == pytest.approx(20.0, rel=0.03)
    assert _lag_correlation(noise, 0, 1) == pytest.approx(0.3, abs=0.02)         # adjacent slices
    assert abs(_lag_correlation(noise, 0, 2)) < 0.02 and abs(_lag_correlation(noise, 0, 3)) < 0.02
    assert abs(_lag_correlation(noise, 1, 1)) < 0.02 and abs(_lag_correlation(noise, 2, 1)) < 0.02   # white inside a slice


def test_without_correlation_the_noise_is_independent_between_slices():
    noise = b3c.slice_correlated_noise(SHAPE, 20.0, seed=4, correlation=0.0)
    assert noise.std() == pytest.approx(20.0, rel=0.02) and abs(_lag_correlation(noise, 0, 1)) < 0.02


def test_the_noise_is_reproducible_and_depends_on_the_seed():
    a = b3c.slice_correlated_noise((6, 16, 16), 10.0, 9)
    assert np.array_equal(a, b3c.slice_correlated_noise((6, 16, 16), 10.0, 9)) and not np.array_equal(a, b3c.slice_correlated_noise((6, 16, 16), 10.0, 10))


@pytest.mark.parametrize("shape, sigma", [((16, 16), 5.0), ((0, 4, 4), 5.0), ((4, 4, 4), -1.0), ((4, 4, 4), float("nan"))])
def test_invalid_noise_requests_are_rejected(shape, sigma):
    with pytest.raises(ValueError):
        b3c.slice_correlated_noise(shape, sigma, 1)


def test_the_noise_generator_of_benchmark_3d_is_replaced_inside_the_block_and_restored_after_it():
    original = b3.white_noise
    with b3c.correlated_noise(0.3):
        assert b3.white_noise is not original
        assert np.array_equal(b3.white_noise((5, 8, 8), 10.0, 2), b3c.slice_correlated_noise((5, 8, 8), 10.0, 2, 0.3))
    assert b3.white_noise is original
    with pytest.raises(RuntimeError):
        with b3c.correlated_noise(0.3):
            raise RuntimeError("boom")
    assert b3.white_noise is original                                            # also restored when the block fails


def test_smoothing_across_slices_leaves_more_noise_when_the_noise_is_correlated_by_the_expected_factor():
    """Variance of a weighted average of correlated values: sum(w^2) + 2 * rho * sum(w[i] * w[i+1])."""
    params = {"sigma_xy_mm": 0.0, "sigma_z_mm": 3.0}                             # one voxel of sigma along z
    sigma_voxels = b3.sigma_voxels(0.0, 3.0, SPACING)[0]
    radius = b3.kernel_radius(sigma_voxels)
    x = np.arange(-radius, radius + 1)
    w = np.exp(-0.5 * (x / sigma_voxels) ** 2)
    w /= w.sum()
    rho = 0.3
    expected_ratio = (np.sum(w**2) + 2 * rho * np.sum(w[:-1] * w[1:])) / np.sum(w**2)
    shape = (17, 128, 128)
    white = b3.smooth(b3.white_noise(shape, 20.0, 5), params, SPACING)[8]
    correlated = b3.smooth(b3c.slice_correlated_noise(shape, 20.0, 5, rho), params, SPACING)[8]
    assert (np.var(correlated) / np.var(white)) == pytest.approx(expected_ratio, rel=0.04)
    assert expected_ratio > 1.3                                                  # the effect is not negligible


def _phantom(slices: int = 45, size: int = 128) -> np.ndarray:
    yy, xx = np.mgrid[0:size, 0:size]
    centre = size / 2 - 0.5
    radius = np.hypot(yy - centre, xx - centre)
    one = np.full((size, size), -1000.0)
    one[radius < 40] = 40.0
    one[np.hypot(yy - centre, xx - centre - 12) < 20] = -800.0
    one[radius >= 62] = -2048.0
    return np.repeat(one[None], slices, axis=0)


def test_the_benchmark_runs_end_to_end_with_correlated_noise_and_keeps_the_protocol():
    volume = _phantom()
    tune, test = b3.plan_slices(volume, n_tune=2, n_test=2)
    tables = b3c.run_experiment(volume, SPACING, tune, test, tune_repeats=1, test_repeats=1, n_boot=50, correlation=0.3)
    assert set(tables) == {"tuning_grid", "selected_parameters", "test_per_run", "test_per_slice", "test_summary", "test_pairwise"}
    per_run = tables["test_per_run"]
    baseline = per_run[(per_run["method"] == b3.BASELINE) & (per_run["mask"] == "main")]
    sigma = baseline["condition"].map(lambda c: float(c.split("_")[1].removesuffix("HU")))
    assert (baseline["RMSE_HU"] / sigma).between(0.95, 1.05).all()                # the unfiltered error is the requested noise level, whatever the correlation
    assert set(tune).isdisjoint(test) and b3.white_noise.__name__ == "white_noise"                             # the original generator is back after the run


def test_the_command_line_refuses_to_write_inside_the_repository(tmp_path):
    repo = Path(b3c.__file__).resolve().parent.parent
    with pytest.raises(SystemExit, match="Refusing to write inside the repository"):
        b3c.main(["--dicom-series", str(tmp_path), "--out", str(repo / "must_not_exist")])
    assert not (repo / "must_not_exist").exists()


def test_the_command_line_rejects_an_impossible_correlation_before_reading_any_data(tmp_path):
    with pytest.raises(ValueError):
        b3c.main(["--dicom-series", str(tmp_path), "--out", str(tmp_path / "out"), "--correlation", "0.9"])


def test_the_shipped_correlated_run_matches_the_hashes_in_its_metadata():
    shipped = sorted((Path(b3c.__file__).resolve().parent / "docs" / "results").glob("benchmark_3d_correlated_*"))
    if not shipped:
        pytest.skip("no recorded correlated-noise run is shipped")
    for run_dir in shipped:
        meta = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
        for name, digest in {**meta["files_sha256"], **meta["figures_sha256"]}.items():
            assert b2.sha256_of(run_dir / name) == digest, name
        noise = meta["parameters"]["noise_model"]
        assert noise["adjacent_slice_correlation"] == pytest.approx(noise["mixing_weight"] / (1 + noise["mixing_weight"] ** 2))
        assert set(meta["parameters"]["tune_slices"]).isdisjoint(meta["parameters"]["test_slices"])
        assert "benchmark_3d_correlated.py" in meta["source_files_sha256"]
