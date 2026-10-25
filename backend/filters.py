"""2D image loading, noise simulation, filtering, and metrics."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, BinaryIO, Optional, Tuple, Union

import cv2
import numpy as np
import pydicom

try:  # pydicom 3.x
    from pydicom.pixels import apply_modality_lut
except ImportError:  # pydicom 2.4.x compatibility
    from pydicom.pixel_data_handlers.util import apply_modality_lut
from scipy.ndimage import median_filter
from skimage.metrics import peak_signal_noise_ratio as psnr
from skimage.metrics import structural_similarity as ssim
from skimage.util import random_noise

logger = logging.getLogger(__name__)

ImageSource = Union[str, Path, BinaryIO]

NOISE_TYPES = ("Gaussian", "Salt & Pepper", "Speckle (synthetic)")
FREQUENCY_FILTERS = ("ideal", "gauss", "butterworth")


def _to_uint8(image: np.ndarray) -> np.ndarray:
    """Convert a [0, 1] image to uint8."""
    return np.clip(np.round(image * 255.0), 0, 255).astype(np.uint8)


def _to_float01(image: np.ndarray) -> np.ndarray:
    """Convert a uint8 image to float64 in [0, 1]."""
    return image.astype(np.float64) / 255.0


def _rescale_to_hu(
    pixel_array: np.ndarray,
    slope: float,
    intercept: float,
) -> np.ndarray:
    """Apply the DICOM rescale operation."""
    return pixel_array.astype(np.float64) * slope + intercept


def _extract_dicom_window(value: Any) -> Optional[float]:
    """Return the first numeric value from a DICOM window field."""
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
    """Normalize an image with an optional DICOM window."""
    if window_center is not None or window_width is not None:
        if (
            window_center is None
            or window_width is None
            or not np.isfinite(window_center)
            or not np.isfinite(window_width)
            or window_width <= 0
        ):
            raise ValueError(
                "WindowCenter and WindowWidth must be present and WindowWidth "
                "must be positive."
            )
        if window_width < 1.0:
            raise ValueError("DICOM WindowWidth must be at least 1.")
        if window_width == 1.0:
            return (image > window_center - 0.5).astype(np.float64)
        scaled = (image - (window_center - 0.5)) / (window_width - 1.0) + 0.5
        return np.clip(scaled, 0.0, 1.0)

    low = float(np.min(image))
    high = float(np.max(image))
    if low == high:
        logger.warning("Image has uniform intensity; returning zeros.")
        return np.zeros_like(image, dtype=np.float64)

    return (image - low) / (high - low)


def _read_source_name(source: ImageSource) -> str:
    """Return a readable name for a file path or file-like object."""
    name = getattr(source, "name", None)
    return str(name) if name is not None else str(source)


def load_medical_image(source: ImageSource) -> np.ndarray:
    """Load a grayscale standard image or DICOM image into [0, 1]."""
    filename = _read_source_name(source)
    try:
        if filename.lower().endswith(".dcm"):
            return _load_dicom(source)
        return _load_standard_image(source)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"Unable to read image '{filename}': {exc}"
        ) from exc


def _load_dicom(source: ImageSource) -> np.ndarray:
    """Load a grayscale DICOM image with basic modality handling."""
    if hasattr(source, "seek"):
        source.seek(0)

    try:
        dataset = pydicom.dcmread(source)
    except Exception as exc:
        raise ValueError(f"Failed to read DICOM: {exc}") from exc

    pixel_array = dataset.pixel_array
    samples_per_pixel = int(getattr(dataset, "SamplesPerPixel", 1))

    if samples_per_pixel != 1:
        raise ValueError(
            "Color DICOM images are not supported; expected SamplesPerPixel=1."
        )

    if pixel_array.ndim > 2:
        logger.warning("Multi-frame DICOM detected; using the first frame.")
        pixel_array = pixel_array[0]

    if pixel_array.ndim != 2:
        raise ValueError(
            f"Expected a 2D grayscale DICOM image, got {pixel_array.shape}."
        )

    # Apply a modality LUT when present; otherwise use the standard rescale tags.
    try:
        image = np.asarray(apply_modality_lut(pixel_array, dataset), dtype=np.float64)
    except (TypeError, AttributeError):
        slope = float(getattr(dataset, "RescaleSlope", 1.0))
        intercept = float(getattr(dataset, "RescaleIntercept", 0.0))
        image = pixel_array.astype(np.float64) * slope + intercept

    window_center = _extract_dicom_window(
        getattr(dataset, "WindowCenter", None)
    )
    window_width = _extract_dicom_window(
        getattr(dataset, "WindowWidth", None)
    )
    normalized = _normalize_dynamic_range(image, window_center, window_width)

    # MONOCHROME1 describes display polarity, not quantitative modality values.
    # Apply the inversion only after modality transformation and normalization.
    if getattr(dataset, "PhotometricInterpretation", "MONOCHROME2") == "MONOCHROME1":
        normalized = 1.0 - normalized
    return np.clip(normalized, 0.0, 1.0)


def _load_standard_image(source: ImageSource) -> np.ndarray:
    """Load a standard image as grayscale."""
    if hasattr(source, "read"):
        if hasattr(source, "seek"):
            source.seek(0)
        data = np.frombuffer(source.read(), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
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
    """Add reproducible synthetic noise to a normalized image."""
    if not isinstance(image, np.ndarray) or image.ndim != 2:
        raise ValueError("image must be a 2D grayscale NumPy array.")
    if not np.isfinite(image).all():
        raise ValueError("image must contain only finite values.")
    if float(image.min()) < 0.0 or float(image.max()) > 1.0:
        raise ValueError("image must be normalized to [0, 1].")
    if not np.isfinite(amount) or not 0.0 <= amount <= 1.0:
        raise ValueError(f"amount must be in [0, 1], got {amount}")
    if not np.isfinite(var) or var < 0.0:
        raise ValueError(f"var must be non-negative, got {var}")

    def apply_noise(mode: str, **kwargs: Any) -> np.ndarray:
        try:
            return random_noise(image, mode=mode, rng=seed, clip=True, **kwargs)
        except TypeError:
            return random_noise(image, mode=mode, seed=seed, clip=True, **kwargs)

    if noise_type == "Gaussian":
        return apply_noise("gaussian", var=var)
    if noise_type == "Salt & Pepper":
        return apply_noise("s&p", amount=amount)
    if noise_type == "Speckle (synthetic)":
        return apply_noise("speckle", var=var)

    raise ValueError(
        f"Unknown noise type: {noise_type!r}. Valid choices: {NOISE_TYPES}."
    )


def calculate_metrics(
    clean_img: np.ndarray,
    processed_img: np.ndarray,
) -> Tuple[float, float]:
    """Return PSNR and SSIM without rounding the numerical results."""
    if clean_img.shape != processed_img.shape:
        raise ValueError(
            f"Image shapes must match: {clean_img.shape} vs {processed_img.shape}"
        )
    if clean_img.ndim != 2:
        raise ValueError("Expected 2D grayscale images.")
    if not (
        np.isfinite(clean_img).all()
        and np.isfinite(processed_img).all()
    ):
        raise ValueError("Images must contain only finite values.")
    if (
        float(clean_img.min()) < 0.0
        or float(clean_img.max()) > 1.0
        or float(processed_img.min()) < 0.0
        or float(processed_img.max()) > 1.0
    ):
        raise ValueError("Images must be normalized to [0, 1].")

    clean_img = clean_img.astype(np.float64)
    processed_img = processed_img.astype(np.float64)

    try:
        score_ssim = float(ssim(clean_img, processed_img, data_range=1.0))
        if np.array_equal(clean_img, processed_img):
            score_psnr = float("inf")
        else:
            score_psnr = float(psnr(clean_img, processed_img, data_range=1.0))
        return score_psnr, score_ssim
    except Exception as exc:
        raise ValueError(f"Failed to compute metrics: {exc}") from exc


def apply_spatial_filters(
    image_noisy: np.ndarray,
    kernel_size: int = 5,
    sigma: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply mean, median, and Gaussian spatial filters."""
    if isinstance(kernel_size, bool) or not isinstance(
        kernel_size, (int, np.integer)
    ):
        raise ValueError("kernel_size must be a positive integer.")

    k_size = int(kernel_size)
    if k_size < 1:
        raise ValueError("kernel_size must be a positive integer.")
    if k_size % 2 == 0:
        k_size += 1
    if image_noisy.ndim != 2 or not np.isfinite(image_noisy).all():
        raise ValueError("image_noisy must be a finite 2D array.")
    if float(image_noisy.min()) < 0.0 or float(image_noisy.max()) > 1.0:
        raise ValueError("image_noisy must be normalized to [0, 1].")
    if not np.isfinite(sigma) or sigma < 0.0:
        raise ValueError(f"sigma must be non-negative, got {sigma}")

    try:
        mean_img = cv2.boxFilter(
            image_noisy,
            -1,
            (k_size, k_size),
            borderType=cv2.BORDER_REFLECT101,
        )
        # Preserve floating-point intensities instead of quantizing to uint8.
        median_img = median_filter(
            image_noisy.astype(np.float64), size=k_size, mode="reflect"
        )
        gaussian_img = cv2.GaussianBlur(
            image_noisy,
            (k_size, k_size),
            sigmaX=sigma,
            borderType=cv2.BORDER_REFLECT101,
        )
        return tuple(
            np.clip(img, 0.0, 1.0)
            for img in (mean_img, median_img, gaussian_img)
        )
    except Exception as exc:
        raise ValueError(f"Spatial filtering failed: {exc}") from exc


def apply_frequency_lowpass(
    image_noisy: np.ndarray,
    cutoff_ratio: float = 0.15,
    filter_type: str = "gauss",
    order: int = 2,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply an Ideal, Gaussian, or Butterworth 2D FFT low-pass filter."""
    if filter_type not in FREQUENCY_FILTERS:
        raise ValueError(
            f"Unknown frequency filter type: {filter_type!r}. "
            f"Valid choices: {FREQUENCY_FILTERS}."
        )
    if not np.isfinite(cutoff_ratio) or not 0 < cutoff_ratio < 1.0:
        raise ValueError(
            f"cutoff_ratio must be in (0, 1), got {cutoff_ratio}"
        )
    if image_noisy.ndim != 2 or not np.isfinite(image_noisy).all():
        raise ValueError("image_noisy must be a finite 2D array.")
    if float(image_noisy.min()) < 0.0 or float(image_noisy.max()) > 1.0:
        raise ValueError("image_noisy must be normalized to [0, 1].")
    if not isinstance(order, (int, np.integer)) or order <= 0:
        raise ValueError(f"order must be a positive integer, got {order}")

    rows, cols = image_noisy.shape
    crow, ccol = rows // 2, cols // 2
    fshift = np.fft.fftshift(np.fft.fft2(image_noisy))
    y, x = np.ogrid[-crow : rows - crow, -ccol : cols - ccol]
    radius = np.sqrt(x**2 + y**2)
    cutoff = cutoff_ratio * min(crow, ccol)

    if filter_type == "ideal":
        mask = (radius <= cutoff).astype(np.float64)
    elif filter_type == "gauss":
        mask = np.exp(-(radius**2) / (2.0 * cutoff**2))
    else:
        mask = 1.0 / (1.0 + (radius / cutoff) ** (2 * order))

    filtered_shift = fshift * mask
    image_back = np.real(np.fft.ifft2(np.fft.ifftshift(filtered_shift)))
    image_back = np.clip(image_back, 0.0, 1.0)

    spectrum = np.log1p(np.abs(fshift))
    spectrum_filtered = np.log1p(np.abs(filtered_shift))
    return image_back, spectrum, spectrum_filtered


# --- edge-preserving and wavelet denoisers ------------------------------------------------
#
# These three functions work on any finite 2D float image and are expressed in the image's own
# intensity units: ``sigma_color``, ``h`` and ``sigma`` must be given in those units (for a
# [0, 1] image, a fraction of the full range; the HU benchmark converts HU to this scale).
# They do not clip; callers that need [0, 1] clip afterwards.

WAVELETS = ("haar", "db2", "db4", "sym4", "sym8", "coif2")
BILATERAL_MAX_SIGMA_SPACE = 10.0
MIN_ADVANCED_SIZE = 8


def _check_float_image(image: np.ndarray, name: str = "image") -> None:
    if not isinstance(image, np.ndarray) or image.ndim != 2:
        raise ValueError(f"{name} must be a 2D grayscale NumPy array.")
    if min(image.shape) < MIN_ADVANCED_SIZE:
        raise ValueError(f"{name} must be at least {MIN_ADVANCED_SIZE} x {MIN_ADVANCED_SIZE} pixels.")
    if not np.isfinite(image).all():
        raise ValueError(f"{name} must contain only finite values.")


def _positive(value: float, name: str, upper: float | None = None) -> float:
    if isinstance(value, bool) or not np.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be positive and finite, got {value}")
    if upper is not None and value > upper:
        raise ValueError(f"{name} must not exceed {upper:g}, got {value}")
    return float(value)


def bilateral_filter(image: np.ndarray, sigma_color: float, sigma_space: float) -> np.ndarray:
    """Bilateral filter (Tomasi and Manduchi, 1998) with OpenCV, reflected borders.

    ``sigma_color`` is the intensity-similarity scale in the image's units and ``sigma_space``
    the spatial scale in pixels; the window diameter is ``2 * ceil(3 * sigma_space) + 1``.
    OpenCV filters in float32, so the result differs from a float64 evaluation by rounding
    only. Two pixels of very different intensity barely influence each other, which is why
    strong edges are kept; a small ``sigma_color`` approaches the identity.
    """
    _check_float_image(image)
    sigma_color = _positive(sigma_color, "sigma_color")
    sigma_space = _positive(sigma_space, "sigma_space", BILATERAL_MAX_SIGMA_SPACE)
    diameter = 2 * int(np.ceil(3.0 * sigma_space)) + 1
    out = cv2.bilateralFilter(
        np.ascontiguousarray(image, dtype=np.float32),
        diameter,
        sigma_color,
        sigma_space,
        borderType=cv2.BORDER_REFLECT101,
    )
    return out.astype(np.float64)


def non_local_means_filter(
    image: np.ndarray,
    h: float,
    patch_size: int = 5,
    patch_distance: int = 6,
) -> np.ndarray:
    """Non-local means (Buades, Coll and Morel, 2005) as implemented in scikit-image.

    Fast mode, no noise-variance correction (``sigma=0``): the true noise level is not an
    input, only ``h`` (the filtering strength, in the image's units) is. ``patch_size`` and
    ``patch_distance`` (pixels) fix the patch and the search window.
    """
    from skimage.restoration import denoise_nl_means

    _check_float_image(image)
    h = _positive(h, "h")
    for name, value in (("patch_size", patch_size), ("patch_distance", patch_distance)):
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not 1 <= value <= 15:
            raise ValueError(f"{name} must be an integer between 1 and 15.")
    if patch_size % 2 == 0:
        raise ValueError("patch_size must be odd.")
    return np.asarray(
        denoise_nl_means(
            image.astype(np.float64),
            patch_size=int(patch_size),
            patch_distance=int(patch_distance),
            h=h,
            fast_mode=True,
            sigma=0.0,
            preserve_range=True,
        ),
        dtype=np.float64,
    )


def wavelet_max_level(shape: Tuple[int, int], wavelet: str = "sym4") -> int:
    """Deepest decomposition level that does not run into boundary effects for an image of ``shape``."""
    import pywt

    if wavelet not in WAVELETS:
        raise ValueError(f"Unknown wavelet {wavelet!r}. Valid choices: {WAVELETS}.")
    return int(pywt.dwt_max_level(min(shape), pywt.Wavelet(wavelet).dec_len))


def wavelet_shrinkage_filter(
    image: np.ndarray,
    sigma: float,
    wavelet: str = "sym4",
    levels: int = 3,
    max_shifts: int = 3,
) -> np.ndarray:
    """Soft-threshold wavelet shrinkage with BayesShrink thresholds, made shift-invariant.

    ``sigma`` is the noise standard deviation *assumed* by BayesShrink (Chang, Yu and
    Vetterli, 2000) in the image's units; it is a strength control, not a measured value.
    A decimated wavelet transform is not shift invariant and leaves blocky artefacts, so the
    result is averaged over ``(max_shifts + 1) ** 2`` circular shifts (cycle spinning,
    Coifman and Donoho, 1995); ``max_shifts=0`` gives the plain decimated transform.
    """
    from skimage.restoration import denoise_wavelet

    _check_float_image(image)
    sigma = _positive(sigma, "sigma")
    if wavelet not in WAVELETS:
        raise ValueError(f"Unknown wavelet {wavelet!r}. Valid choices: {WAVELETS}.")
    if isinstance(levels, bool) or not isinstance(levels, (int, np.integer)) or not 1 <= levels <= 6:
        raise ValueError("levels must be an integer between 1 and 6.")
    if isinstance(max_shifts, bool) or not isinstance(max_shifts, (int, np.integer)) or not 0 <= max_shifts <= 7:
        raise ValueError("max_shifts must be an integer between 0 and 7.")
    deepest = wavelet_max_level(image.shape, wavelet)
    if levels > deepest:
        raise ValueError(f"levels={int(levels)} is too deep for a {image.shape[0]} x {image.shape[1]} image with "
                         f"{wavelet} (at most {deepest}).")
    data = image.astype(np.float64)
    options = dict(
        sigma=sigma, wavelet=wavelet, mode="soft", wavelet_levels=int(levels),
        method="BayesShrink", rescale_sigma=True,
    )
    total = np.zeros_like(data)
    shifts = [(dy, dx) for dy in range(int(max_shifts) + 1) for dx in range(int(max_shifts) + 1)]
    for dy, dx in shifts:
        shifted = np.roll(data, (dy, dx), axis=(0, 1))
        total += np.roll(denoise_wavelet(shifted, **options), (-dy, -dx), axis=(0, 1))
    return total / len(shifts)
