"""Physical-unit Gaussian smoothing for 3D medical volumes."""
from __future__ import annotations
import numpy as np
from scipy.ndimage import gaussian_filter


def gaussian_denoise_volume(
    volume: np.ndarray,
    sigma: float = 1.0,
    spacing_xyz_mm: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """Smooth a (z,y,x) volume with Gaussian sigma in millimetres."""
    if not isinstance(volume, np.ndarray) or volume.ndim != 3 or volume.size == 0:
        raise ValueError("volume must be a non-empty 3D NumPy array.")
    if not np.isfinite(volume).all():
        raise ValueError("volume must contain only finite values.")
    if isinstance(sigma, (bool, np.bool_)) or not np.isfinite(sigma) or sigma <= 0:
        raise ValueError("sigma (mm) must be finite and greater than 0.")
    spacing = np.asarray(spacing_xyz_mm, dtype=float)
    if spacing.shape != (3,) or not np.isfinite(spacing).all() or np.any(spacing <= 0):
        raise ValueError("spacing_xyz_mm must contain three positive finite values.")
    sigma_zyx = (float(sigma) / spacing[2], float(sigma) / spacing[1], float(sigma) / spacing[0])
    return gaussian_filter(volume.astype(np.float32), sigma=sigma_zyx, mode="reflect")
