import numpy as np
from scipy.ndimage import gaussian_filter


def gaussian_denoise_volume(
    volume: np.ndarray,
    sigma: float = 1.0,
) -> np.ndarray:
    if volume.ndim != 3:
        raise ValueError("Expected a 3D volume.")

    if sigma <= 0:
        raise ValueError("Sigma must be greater than 0.")
    
    denoised = gaussian_filter(
        volume.astype(np.float32),
        sigma=sigma,
        )
    return denoised