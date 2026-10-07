"""Simple 3D denoising methods for reconstructed medical volumes."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter


def gaussian_denoise_volume(
    volume: np.ndarray,
    sigma: float = 1.0,
) -> np.ndarray:
    """Apply Gaussian smoothing with the same sigma in voxel units along all three axes."""
    if not isinstance(volume, np.ndarray) or volume.ndim != 3:
        raise ValueError("volume must be a 3D NumPy array.")
    if not np.isfinite(volume).all():
        raise ValueError("volume must contain only finite values.")
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError("sigma must be finite and greater than 0.")

    return gaussian_filter(volume.astype(np.float32), sigma=float(sigma))
