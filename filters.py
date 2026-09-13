"""Image processing engine for biomedical denoising.

Provides spatial and frequency domain filtering with comprehensive error handling,
type hints, and quantitative metrics (PSNR, SSIM).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO, Union, Optional, Tuple
import logging

import cv2
import numpy as np
import pydicom
from skimage.metrics import peak_signal_noise_ratio as psnr
from skimage.metrics import structural_similarity as ssim
from skimage.util import random_noise

logger = logging.getLogger(__name__)

ImageSource = Union[str, Path, BinaryIO]

NOISE_TYPES = ("Gaussian", "Salt & Pepper", "Speckle (Ultrasound)")
FREQUENCY_FILTERS = ("ideal", "gauss", "butterworth")

__all__ = [
    "load_medical_image",
    "add_noise",
    "calculate_metrics",
    "apply_spatial_filters",
    "apply_frequency_lowpass",
    "NOISE_TYPES",
    "FREQUENCY_FILTERS",
]


def _to_uint8(image: np.ndarray) -> np.ndarray:
    """Convert float [0,1] image to uint8 [0,255]."""
    return np.clip(np.round(image * 255.0), 0, 255).astype(np.uint8)


def _to_float01(image: np.ndarray) -> np.ndarray:
    """Convert uint8 [0,255] image to float [0,1]."""
    return image.astype(np.float64) / 255.0


def _rescale_to_hu(
    pixel_array: np.ndarray, 
    slope: float, 
    intercept: float
) -> np.ndarray:
    """Apply DICOM RescaleSlope and RescaleIntercept (Hounsfield Units)."""
    return pixel_array.astype(np.float64) * slope + intercept


def _extract_dicom_window(value: Any) -> Optional[float]:
    """Extract window level/width from DICOM metadata."""
    if value is None:
        return None
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
        value = list(value)[0]
    return float(value)


def _normalize_dynamic_range(
    image: np.ndarray,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
) -> np.ndarray:
    """Normalize image using DICOM window/level or auto-scale."""
    if window_center is not None and window_width and window_width > 0:
        low = window_center - window_width / 2.0
        high = window_center + window_width / 2.0
        image = np.clip(image, low, high)
        return (image - low) / (high - low + 1e-8)

    lo, hi = float(np.min(image)), float(np.max(image))
    if lo == hi:
        logger.warning("Image has uniform intensity. Returning zeros.")
        return np.zeros_like(image, dtype=np.float64)
    
    return (image - lo) / (hi - lo + 1e-8)


def _read_source_name(source: ImageSource) -> str:
    """Extract filename from file source."""
    name = getattr(source, "name", None)
    return str(name) if name is not None else str(source)


def load_medical_image(source: ImageSource) -> np.ndarray:
    """
    Load medical image from file or stream.
    
    Supports DICOM with proper photometric interpretation, HU conversion,
    and VOI LUT (window/level) application.
    
    Args:
        source: File path, Path object, or file-like object
        
    Returns:
        Normalized float64 image in [0.0, 1.0]
        
    Raises:
        ValueError: If file cannot be read or format unsupported
    """
    filename = _read_source_name(source)
    try:
        if filename.lower().endswith(".dcm"):
            logger.info(f"Loading DICOM: {filename}")
            return _load_dicom(source)
        logger.info(f"Loading standard image: {filename}")
        return _load_standard_image(source)
    except ValueError:
        raise
    except Exception as exc:
        logger.error(f"Unable to read image '{filename}': {exc}")
        raise ValueError(f"Unable to read image '{filename}': {exc}") from exc


def _load_dicom(source: ImageSource) -> np.ndarray:
    """Load DICOM file with proper medical imaging handling."""
    if hasattr(source, "seek"):
        source.seek(0)
    
    try:
        dataset = pydicom.dcmread(source)
    except Exception as e:
        logger.error(f"DICOM read error: {e}")
        raise ValueError(f"Failed to read DICOM: {e}") from e
    
    pixel_array = dataset.pixel_array

    # Handle multi-frame images
    if pixel_array.ndim > 2:
        logger.warning("Multi-frame DICOM detected. Using first frame.")
        pixel_array = pixel_array[0]
    
    pixel_array = pixel_array.astype(np.float64)

    # Photometric Interpretation (MONOCHROME1 = invert)
    photometric = getattr(dataset, "PhotometricInterpretation", "MONOCHROME2")
    if photometric == "MONOCHROME1":
        bits_stored = getattr(dataset, "BitsStored", None)
        ceiling = float((2**bits_stored) - 1) if bits_stored else float(pixel_array.max())
        pixel_array = ceiling - pixel_array
        logger.info("Applied MONOCHROME1 inversion")

    # Modality LUT (HU conversion)
    slope = float(getattr(dataset, "RescaleSlope", 1.0))
    intercept = float(getattr(dataset, "RescaleIntercept", 0.0))
    image = _rescale_to_hu(pixel_array, slope, intercept)

    # VOI LUT (Window/Level)
    window_center = _extract_dicom_window(getattr(dataset, "WindowCenter", None))
    window_width = _extract_dicom_window(getattr(dataset, "WindowWidth", None))
    
    return _normalize_dynamic_range(image, window_center, window_width)


def _load_standard_image(source: ImageSource) -> np.ndarray:
    """Load standard image format (PNG, JPG, etc.)."""
    if hasattr(source, "read"):
        if hasattr(source, "seek"):
            source.seek(0)
        file_bytes = np.frombuffer(source.read(), dtype=np.uint8)
        image = cv2.imdecode(file_bytes, cv2.IMREAD_GRAYSCALE)
    else:
        image = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)

    if image is None:
        raise ValueError("Unrecognized image format or corrupted file.")
    
    return _to_float01(image)


def add_noise(
    image: np.ndarray,
    noise_type: str,
    amount: float = 0.05,
    var: float = 0.01,
    seed: Optional[int] = None,
) -> np.ndarray:
    """
    Add noise to image for degradation testing.
    
    Args:
        image: Normalized image [0.0, 1.0]
        noise_type: "Gaussian", "Salt & Pepper", or "Speckle (Ultrasound)"
        amount: For S&P noise (fraction of pixels)
        var: For Gaussian/Speckle noise (variance)
        seed: Random seed for reproducibility
        
    Returns:
        Noisy image
        
    Raises:
        ValueError: If noise_type invalid
    """
    def _apply_noise(mode: str, **kwargs) -> np.ndarray:
        try:
            return random_noise(image, mode=mode, rng=seed, clip=True, **kwargs)
        except TypeError:
            return random_noise(image, mode=mode, seed=seed, clip=True, **kwargs)

    if noise_type == "Gaussian":
        logger.info(f"Adding Gaussian noise (var={var})")
        return _apply_noise("gaussian", var=var)
    if noise_type == "Salt & Pepper":
        logger.info(f"Adding Salt & Pepper noise (amount={amount})")
        return _apply_noise("s&p", amount=amount)
    if noise_type == "Speckle (Ultrasound)":
        logger.info(f"Adding Speckle noise (var={var})")
        return _apply_noise("speckle", var=var)

    raise ValueError(f"Unknown noise type: {noise_type!r}. Valid choices: {NOISE_TYPES}.")


def calculate_metrics(
    clean_img: np.ndarray, 
    processed_img: np.ndarray
) -> Tuple[float, float]:
    """
    Compute PSNR and SSIM metrics.
    
    Args:
        clean_img: Reference image
        processed_img: Test image
        
    Returns:
        Tuple of (PSNR in dB, SSIM in [-1, 1])
        
    Raises:
        ValueError: If shapes don't match or images invalid
    """
    if clean_img.shape != processed_img.shape:
        raise ValueError(
            f"Image shapes must match: {clean_img.shape} vs {processed_img.shape}"
        )
    
    clean_img = clean_img.astype(np.float64)
    processed_img = processed_img.astype(np.float64)

    try:
        score_ssim = ssim(clean_img, processed_img, data_range=1.0)
        mse = float(np.mean((clean_img - processed_img) ** 2))

        if mse == 0.0:
            score_psnr: float = float("inf")
        else:
            score_psnr = float(psnr(clean_img, processed_img, data_range=1.0))

        rounded_psnr = score_psnr if np.isinf(score_psnr) else round(score_psnr, 2)
        
        logger.info(f"Metrics: PSNR={rounded_psnr}, SSIM={score_ssim:.4f}")
        
        return rounded_psnr, round(float(score_ssim), 4)
    
    except Exception as e:
        logger.error(f"Metrics computation failed: {e}")
        raise ValueError(f"Failed to compute metrics: {e}") from e


def apply_spatial_filters(
    image_noisy: np.ndarray,
    kernel_size: int = 5,
    sigma: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Apply spatial domain filters (Mean, Median, Gaussian).
    
    Args:
        image_noisy: Noisy input image
        kernel_size: Filter kernel size (will be made odd)
        sigma: Gaussian sigma (0 = auto)
        
    Returns:
        Tuple of (mean_filtered, median_filtered, gaussian_filtered)
        
    Raises:
        ValueError: If kernel_size invalid
    """
    k_size = int(kernel_size)
    if k_size < 1:
        raise ValueError("kernel_size must be a positive integer.")
    if k_size % 2 == 0:
        k_size += 1

    try:
        mean_img = cv2.boxFilter(
            image_noisy, -1, (k_size, k_size), 
            borderType=cv2.BORDER_REFLECT101
        )
        median_img = _to_float01(
            cv2.medianBlur(_to_uint8(image_noisy), k_size)
        )
        gaussian_img = cv2.GaussianBlur(
            image_noisy, (k_size, k_size), 
            sigmaX=sigma, borderType=cv2.BORDER_REFLECT101
        )

        # Enforce [0.0, 1.0] bounds
        mean_img = np.clip(mean_img, 0.0, 1.0)
        median_img = np.clip(median_img, 0.0, 1.0)
        gaussian_img = np.clip(gaussian_img, 0.0, 1.0)
        
        logger.info(f"Applied spatial filters (kernel={k_size}, sigma={sigma})")

        return mean_img, median_img, gaussian_img
    
    except Exception as e:
        logger.error(f"Spatial filtering failed: {e}")
        raise ValueError(f"Spatial filtering failed: {e}") from e


def apply_frequency_lowpass(
    image_noisy: np.ndarray,
    cutoff_ratio: float = 0.1,
    filter_type: str = "gauss",
    order: int = 2,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Apply frequency domain low-pass filters.
    
    Args:
        image_noisy: Noisy input image
        cutoff_ratio: Cutoff frequency as fraction of image size
        filter_type: "ideal", "gauss", or "butterworth"
        order: Butterworth filter order
        
    Returns:
        Tuple of (filtered_image, spectrum_original, spectrum_filtered)
        
    Raises:
        ValueError: If filter_type or parameters invalid
    """
    if filter_type not in FREQUENCY_FILTERS:
        raise ValueError(
            f"Unknown frequency filter type: {filter_type!r}. "
            f"Valid choices: {FREQUENCY_FILTERS}."
        )
    
    if not (0 < cutoff_ratio < 1.0):
        raise ValueError(f"cutoff_ratio must be in (0, 1), got {cutoff_ratio}")
    
    if order <= 0:
        raise ValueError(f"order must be positive, got {order}")

    try:
        rows, cols = image_noisy.shape
        crow, ccol = rows // 2, cols // 2

        f = np.fft.fft2(image_noisy)
        fshift = np.fft.fftshift(f)

        y, x = np.ogrid[-crow : rows - crow, -ccol : cols - ccol]
        radius_sq = x**2 + y**2
        cutoff_freq = cutoff_ratio * min(crow, ccol)

        if filter_type == "ideal":
            mask = (radius_sq <= cutoff_freq**2).astype(np.float64)
            logger.info(f"Applied Ideal low-pass filter (cutoff={cutoff_freq:.1f})")
        
        elif filter_type == "gauss":
            mask = np.exp(-radius_sq / (2 * (cutoff_freq**2 + 1e-8)))
            logger.info(f"Applied Gaussian low-pass filter (cutoff={cutoff_freq:.1f})")
        
        else:  # butterworth
            mask = 1.0 / (1.0 + (np.sqrt(radius_sq) / (cutoff_freq + 1e-8)) ** (2 * order))
            logger.info(f"Applied Butterworth low-pass filter (order={order}, cutoff={cutoff_freq:.1f})")

        fshift_filtered = fshift * mask

        f_ishift = np.fft.ifftshift(fshift_filtered)
        img_back = np.fft.ifft2(f_ishift)
        img_back = np.clip(np.abs(img_back), 0.0, 1.0)

        spectrum = np.log1p(np.abs(fshift))
        spectrum_filtered = np.log1p(np.abs(fshift_filtered))

        return img_back, spectrum, spectrum_filtered
    
    except Exception as e:
        logger.error(f"Frequency filtering failed: {e}")
        raise ValueError(f"Frequency filtering failed: {e}") from e
