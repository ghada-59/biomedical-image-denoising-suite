from __future__ import annotations

import numpy as np
import pytest

from evaluate_denoising import derive_run_seed, select_slice_indices, window_ct_slice


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
