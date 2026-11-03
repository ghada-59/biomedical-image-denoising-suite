from __future__ import annotations

import numpy as np
import pytest

from src.volume_denoising import gaussian_denoise_volume


def test_gaussian_denoise_preserves_volume_shape() -> None:
    volume = np.zeros((8, 10, 12), dtype=np.float32)
    volume[4, 5, 6] = 100.0
    result = gaussian_denoise_volume(volume, sigma=1.0)
    assert result.shape == volume.shape


def test_gaussian_denoise_reduces_peak() -> None:
    volume = np.zeros((8, 10, 12), dtype=np.float32)
    volume[4, 5, 6] = 100.0
    result = gaussian_denoise_volume(volume, sigma=1.0)
    assert 0.0 < result[4, 5, 6] < 100.0


def test_gaussian_denoise_rejects_non_3d_input() -> None:
    with pytest.raises(ValueError):
        gaussian_denoise_volume(np.zeros((10, 10)), sigma=1.0)


def test_gaussian_denoise_rejects_invalid_sigma() -> None:
    volume = np.zeros((4, 4, 4), dtype=np.float32)
    with pytest.raises(ValueError):
        gaussian_denoise_volume(volume, sigma=0.0)
    with pytest.raises(ValueError):
        gaussian_denoise_volume(volume, sigma=np.nan)


def test_gaussian_denoise_rejects_non_finite_volume() -> None:
    volume = np.zeros((4, 4, 4), dtype=np.float32)
    volume[0, 0, 0] = np.nan
    with pytest.raises(ValueError):
        gaussian_denoise_volume(volume, sigma=1.0)

def test_gaussian_uses_physical_spacing(monkeypatch):
    import src.volume_denoising as module
    observed = {}
    def fake_filter(volume, sigma, mode):
        observed["sigma"] = sigma
        observed["mode"] = mode
        return volume
    monkeypatch.setattr(module, "gaussian_filter", fake_filter)
    gaussian_denoise_volume(np.zeros((5, 6, 7)), sigma=1.0, spacing_xyz_mm=(0.5, 0.5, 3.0))
    assert observed["sigma"] == pytest.approx((1/3, 2.0, 2.0))
    assert observed["mode"] == "reflect"


def test_gaussian_rejects_invalid_spacing():
    for spacing in ((1, 1), (1, 0, 1), (1, np.nan, 1)):
        with pytest.raises(ValueError):
            gaussian_denoise_volume(np.zeros((3, 3, 3)), spacing_xyz_mm=spacing)
