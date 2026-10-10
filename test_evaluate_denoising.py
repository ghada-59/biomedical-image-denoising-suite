from __future__ import annotations

import numpy as np
import pytest

from evaluate_denoising import (
    _add_noise,
    _evaluate_one_slice,
    derive_run_seed,
    select_slice_indices,
    window_ct_slice,
)


def test_window_ct_slice_maps_lung_window_limits_to_zero_and_one() -> None:
    image_hu = np.array([[-1350.0, -600.0, 150.0]])
    actual = window_ct_slice(image_hu, window_center=-600.0, window_width=1500.0)
    np.testing.assert_allclose(actual, [[0.0, 0.5003335557, 1.0]], atol=1e-8)


def test_window_ct_slice_clips_outside_window() -> None:
    image_hu = np.array([[-2000.0, 500.0]])
    actual = window_ct_slice(image_hu, window_center=-600.0, window_width=1500.0)
    np.testing.assert_allclose(actual, [[0.0, 1.0]])


@pytest.mark.parametrize(
    "image",
    [
        np.zeros((2, 2, 2)),
        np.array([[np.nan]]),
        np.empty((0, 0)),
    ],
)
def test_window_ct_slice_rejects_invalid_inputs(image: np.ndarray) -> None:
    with pytest.raises(ValueError):
        window_ct_slice(image)


def test_window_ct_slice_rejects_invalid_window_width() -> None:
    with pytest.raises(ValueError):
        window_ct_slice(np.zeros((2, 2)), window_width=0.0)


def test_select_slice_indices_spreads_five_indices_across_volume() -> None:
    indices = select_slice_indices(100)
    assert len(indices) == 5
    assert indices == sorted(set(indices))
    assert all(0 <= index < 100 for index in indices)


def test_select_slice_indices_handles_small_volume() -> None:
    assert select_slice_indices(3) == [0, 1, 2]


def test_select_slice_indices_validates_explicit_indices() -> None:
    assert select_slice_indices(10, [8, 2, 5]) == [2, 5, 8]
    with pytest.raises(ValueError):
        select_slice_indices(10, [1, 1])
    with pytest.raises(ValueError):
        select_slice_indices(10, [10])
    with pytest.raises(ValueError):
        select_slice_indices(10, [])


def test_seed_derivation_is_stable_and_distinct():
    a = derive_run_seed(42, 15, "Gaussian", 0)
    assert a == derive_run_seed(42, 15, "Gaussian", 0)
    assert len({a, derive_run_seed(42, 15, "Gaussian", 1), derive_run_seed(42, 32, "Gaussian", 0)}) == 3



@pytest.mark.parametrize(
    "noise_type",
    ["Gaussian", "Salt & Pepper", "Speckle (synthetic)"],
)
def test_benchmark_noise_labels_are_supported(noise_type: str) -> None:
    image = np.linspace(0.0, 1.0, 256, dtype=np.float64).reshape(16, 16)
    noisy, parameter = _add_noise(
        image,
        noise_type=noise_type,
        noise_variance=0.02,
        salt_pepper_amount=0.02,
        seed=123,
    )
    assert noisy.shape == image.shape
    assert np.isfinite(noisy).all()
    assert float(noisy.min()) >= 0.0
    assert float(noisy.max()) <= 1.0
    assert parameter


def test_all_benchmark_rows_keep_repeat_and_seed_metadata() -> None:
    image = np.linspace(0.0, 1.0, 32 * 32, dtype=np.float64).reshape(32, 32)
    rows = _evaluate_one_slice(
        clean_image=image,
        series_name="synthetic_test",
        slice_index=12,
        noise_type="Gaussian",
        noise_variance=0.02,
        salt_pepper_amount=0.02,
        repeat_index=1,
        seed=456,
        save_visuals=False,
    )
    assert rows
    assert all(row.get("Repeat") == 2 for row in rows)
    assert all(row.get("Seed") == 456 for row in rows)
    assert any(row["Domain"] == "Spatial" for row in rows)
    assert any(row["Domain"] == "Frequency" for row in rows)
