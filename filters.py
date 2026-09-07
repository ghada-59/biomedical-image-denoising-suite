"""Image processing engine for biomedical denoising."""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO, Union

import cv2
import numpy as np
import pydicom
from skimage.metrics import peak_signal_noise_ratio as psnr
from skimage.metrics import structural_similarity as ssim
from skimage.util import random_noise

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
    return np.clip(np.round(image * 255.0), 0, 255).astype(np.uint8)


def _to_float01(image: np.ndarray) -> np.ndarray:
    return image.astype(np.float64) / 255.0


def _rescale_to_hu(pixel_array: np.ndarray, slope: float, intercept: float) -> np.ndarray:
    return pixel_array.astype(np.float64) * slope + intercept


def _extract_dicom_window(value: Any) -> float | None:
    if value is None:
        return None
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
        value = list(value)[0]
    return float(value)


def _normalize_dynamic_range(
    image: np.ndarray,
    window_center: float | None = None,
    window_width: float | None = None,
) -> np.ndarray:
    if window_center is not None and window_width and window_width > 0:
        low = window_center - window_width / 2.0
        high = window_center + window_width / 2.0
        image = np.clip(image, low, high)
        return (image - low) / (high - low + 1e-8)

    lo, hi = float(np.min(image)), float(np.max(image))
    return (image - lo) / (hi - lo + 1e-8)


def _read_source_name(source: ImageSource) -> str:
    name = getattr(source, "name", None)
    return str(name) if name is not None else str(source)


def load_medical_image(source: ImageSource) -> np.ndarray:
    filename = _read_source_name(source)
    try:
        if filename.lower().endswith(".dcm"):
            return _load_dicom(source)
        return _load_standard_image(source)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Unable to read image '{filename}': {exc}") from exc


def _load_dicom(source: ImageSource) -> np.ndarray:
    if hasattr(source, "seek"):
        source.seek(0)
    dataset = pydicom.dcmread(source)
    pixel_array = dataset.pixel_array

    if pixel_array.ndim > 2:
        pixel_array = pixel_array[0]
    pixel_array = pixel_array.astype(np.float64)

    photometric = getattr(dataset, "PhotometricInterpretation", "MONOCHROME2")
    if photometric == "MONOCHROME1":
        bits_stored = getattr(dataset, "BitsStored", None)
        ceiling = float((2**bits_stored) - 1) if bits_stored else float(pixel_array.max())
        pixel_array = ceiling - pixel_array

    slope = float(getattr(dataset, "RescaleSlope", 1.0))
    intercept = float(getattr(dataset, "RescaleIntercept", 0.0))
    image = _rescale_to_hu(pixel_array, slope, intercept)

    window_center = _extract_dicom_window(getattr(dataset, "WindowCenter", None))
    window_width = _extract_dicom_window(getattr(dataset, "WindowWidth", None))
    return _normalize_dynamic_range(image, window_center, window_width)


def _load_standard_image(source: ImageSource) -> np.ndarray:
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
    seed: int | None = None,
) -> np.ndarray:
    def _apply_noise(mode: str, **kwargs) -> np.ndarray:
        try:
            return random_noise(image, mode=mode, rng=seed, clip=True, **kwargs)
        except TypeError:
            return random_noise(image, mode=mode, seed=seed, clip=True, **kwargs)

    if noise_type == "Gaussian":
        return _apply_noise("gaussian", var=var)
    if noise_type == "Salt & Pepper":
        return _apply_noise("s&p", amount=amount)
    if noise_type == "Speckle (Ultrasound)":
        return _apply_noise("speckle", var=var)

    raise ValueError(f"Unknown noise type: {noise_type!r}. Valid choices: {NOISE_TYPES}.")


def calculate_metrics(clean_img: np.ndarray, processed_img: np.ndarray) -> tuple[float, float]:
    clean_img = clean_img.astype(np.float64)
    processed_img = processed_img.astype(np.float64)

    score_ssim = ssim(clean_img, processed_img, data_range=1.0)
    mse = float(np.mean((clean_img - processed_img) ** 2))

    if mse == 0.0:
        score_psnr: float = float("inf")
    else:
        score_psnr = float(psnr(clean_img, processed_img, data_range=1.0))

    rounded_psnr = score_psnr if np.isinf(score_psnr) else round(score_psnr, 2)
    return rounded_psnr, round(float(score_ssim), 4)


def apply_spatial_filters(
    image_noisy: np.ndarray,
    kernel_size: int = 5,
    sigma: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    k_size = int(kernel_size)
    if k_size < 1:
        raise ValueError("kernel_size must be a positive integer.")
    if k_size % 2 == 0:
        k_size += 1

    mean_img = cv2.boxFilter(image_noisy, -1, (k_size, k_size), borderType=cv2.BORDER_REFLECT101)
    median_img = _to_float01(cv2.medianBlur(_to_uint8(image_noisy), k_size))
    gaussian_img = cv2.GaussianBlur(
        image_noisy, (k_size, k_size), sigmaX=sigma, borderType=cv2.BORDER_REFLECT101
    )

    # Safety check: enforce all values strictly within [0.0, 1.0]
    mean_img = np.clip(mean_img, 0.0, 1.0)
    median_img = np.clip(median_img, 0.0, 1.0)
    gaussian_img = np.clip(gaussian_img, 0.0, 1.0)

    return mean_img, median_img, gaussian_img


def apply_frequency_lowpass(
    image_noisy: np.ndarray,
    cutoff_ratio: float = 0.1,
    filter_type: str = "gauss",
    order: int = 2,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if filter_type not in FREQUENCY_FILTERS:
        raise ValueError(
            f"Unknown frequency filter type: {filter_type!r}. "
            f"Valid choices: {FREQUENCY_FILTERS}."
        )

    rows, cols = image_noisy.shape
    crow, ccol = rows // 2, cols // 2

    f = np.fft.fft2(image_noisy)
    fshift = np.fft.fftshift(f)

    y, x = np.ogrid[-crow : rows - crow, -ccol : cols - ccol]
    radius_sq = x**2 + y**2
    cutoff_freq = cutoff_ratio * min(crow, ccol)

    if filter_type == "ideal":
        mask = (radius_sq <= cutoff_freq**2).astype(np.float64)
    elif filter_type == "gauss":
        mask = np.exp(-radius_sq / (2 * (cutoff_freq**2 + 1e-8)))
    else:
        mask = 1.0 / (1.0 + (np.sqrt(radius_sq) / (cutoff_freq + 1e-8)) ** (2 * order))

    fshift_filtered = fshift * mask

    f_ishift = np.fft.ifftshift(fshift_filtered)
    img_back = np.fft.ifft2(f_ishift)
    img_back = np.clip(np.abs(img_back), 0.0, 1.0)

    spectrum = np.log1p(np.abs(fshift))
    spectrum_filtered = np.log1p(np.abs(fshift_filtered))

    return img_back, spectrum, spectrum_filtered