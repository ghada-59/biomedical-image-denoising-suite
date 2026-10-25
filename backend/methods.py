"""Catalogue of the denoising methods offered by the interactive 2D lab.

One registry describes every method (label, family, parameters with their limits and defaults, a one-line
statement of what it assumes) and runs it. The API serves this catalogue to the dashboard and uses the same
objects to process an image, so the controls a user sees, the limits the server enforces and the code that runs
cannot drift apart.

All methods take a grayscale image in [0, 1] and return an image clipped to [0, 1]; the benchmark in
``benchmark_v2`` uses the unclipped functions of ``filters`` directly.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np
from scipy.ndimage import median_filter

from filters import (
    NLM_PATCH_DISTANCE,
    NLM_PATCH_SIZE,
    WAVELET_LEVELS,
    WAVELET_MAX_SHIFTS,
    WAVELET_NAME,
    apply_frequency_lowpass,
    bilateral_filter,
    non_local_means_filter,
    wavelet_max_level,
    wavelet_shrinkage_filter,
)



@dataclass(frozen=True)
class Param:
    """One numeric control. ``name`` is the request field and ``default`` the value used when it is omitted."""

    name: str
    label: str
    minimum: float
    maximum: float
    step: float
    default: float
    integer: bool = False
    unit: str = ""
    help: str = ""
    exclusive_minimum: bool = False
    exclusive_maximum: bool = False

    def as_dict(self) -> dict:
        return {
            "name": self.name, "label": self.label, "minimum": self.minimum, "maximum": self.maximum, "step": self.step,
            "default": self.default, "integer": self.integer, "unit": self.unit, "help": self.help,
            "exclusive_minimum": self.exclusive_minimum, "exclusive_maximum": self.exclusive_maximum,
        }


# Defaults of the three adaptive methods suit the lab's default noise (Gaussian, variance 0.02, standard deviation 0.14):
# they were read off a PSNR sweep on the three bundled samples. They are demo defaults, not tuned per image.
KERNEL_SIZE = Param("kernel_size", "Kernel size", 1, 51, 2, 5, integer=True, unit="px",
                    help="Window side in pixels. Even values are raised to the next odd value.")
SIGMA = Param("sigma", "Gaussian sigma", 0.0, 50.0, 0.1, 0.0, unit="px",
              help="Standard deviation of the Gaussian kernel in pixels. 0 lets OpenCV derive it from the kernel size.")
CUTOFF = Param("cutoff_ratio", "FFT cutoff", 0.0, 1.0, 0.01, 0.15, exclusive_minimum=True, exclusive_maximum=True,
               help="Cutoff radius as a fraction of the smaller half-dimension of the spectrum (1 = Nyquist). Must be in (0, 1).")
BILATERAL_COLOR = Param("bilateral_sigma_color", "Intensity scale", 0.0, 1.0, 0.01, 0.40, exclusive_minimum=True,
                        unit="of full range",
                        help="Pixels whose intensity differs by much more than this barely influence each other (edges survive).")
BILATERAL_SPACE = Param("bilateral_sigma_space", "Spatial scale", 0.0, 5.0, 0.1, 1.5, exclusive_minimum=True, unit="px",
                        help="Spatial standard deviation in pixels; the window diameter is 2*ceil(3*scale)+1.")
NLM_H = Param("nlm_h", "Filtering strength h", 0.0, 1.0, 0.01, 0.15, exclusive_minimum=True, unit="of full range",
              help="Patch-similarity tolerance. Too small leaves noise, too large erases texture. Patch 5x5, search window 13x13 are fixed.")
WAVELET_SIGMA = Param("wavelet_sigma", "Assumed noise level", 0.0, 1.0, 0.01, 0.15, exclusive_minimum=True, unit="of full range",
                      help="Noise standard deviation assumed by the BayesShrink thresholds. A strength control, not a measurement.")

Runner = Callable[[np.ndarray, dict], "tuple[np.ndarray, dict]"]


@dataclass(frozen=True)
class Method:
    id: str
    label: str
    family: str
    summary: str
    assumption: str
    params: tuple[Param, ...]
    run: Runner
    reference: str
    heavy: bool = False          # limited to MAX_ADVANCED_PIXELS by the API
    requires: tuple[tuple[str, str], ...] = ()      # (importable module, pip package name) this method cannot run without

    def missing_packages(self) -> list[str]:
        return [package for module, package in self.requires if not package_available(module)]

    def unavailable_reason(self) -> str | None:
        missing = self.missing_packages()
        if not missing:
            return None
        return (f"{self.label} needs the Python package {', '.join(missing)}, which is not installed in this environment. "
                f"Install it with: python -m pip install -r requirements-api.txt")

    def as_dict(self) -> dict:
        reason = self.unavailable_reason()
        return {"id": self.id, "label": self.label, "family": self.family, "summary": self.summary, "assumption": self.assumption,
                "reference": self.reference, "heavy": self.heavy, "parameters": [p.as_dict() for p in self.params],
                "available": reason is None, "unavailable_reason": reason}


def package_available(module: str) -> bool:
    """True when ``module`` can be imported here (checked without importing it)."""
    return importlib.util.find_spec(module) is not None


def _odd(kernel_size: int) -> int:
    k = int(kernel_size)
    return k + 1 if k % 2 == 0 else k


def _clip(image: np.ndarray) -> np.ndarray:
    return np.clip(image, 0.0, 1.0)


def _mean(image: np.ndarray, values: dict):
    k = _odd(values["kernel_size"])
    return _clip(cv2.boxFilter(image, -1, (k, k), borderType=cv2.BORDER_REFLECT101)), {"kernel_size": k}


def _median(image: np.ndarray, values: dict):
    k = _odd(values["kernel_size"])
    return _clip(median_filter(image.astype(np.float64), size=k, mode="reflect")), {"kernel_size": k}


def _gaussian(image: np.ndarray, values: dict):
    k, sigma = _odd(values["kernel_size"]), float(values["sigma"])
    out = cv2.GaussianBlur(image, (k, k), sigmaX=sigma, borderType=cv2.BORDER_REFLECT101)
    return _clip(out), {"kernel_size": k, "sigma": sigma if sigma > 0 else "auto (set by OpenCV from the kernel size)"}


def _frequency(kind: str) -> Runner:
    def run(image: np.ndarray, values: dict):
        cutoff = float(values["cutoff_ratio"])
        filtered, _, _ = apply_frequency_lowpass(image, cutoff_ratio=cutoff, filter_type=kind)
        return filtered, {"cutoff_ratio": cutoff, **({"order": 2} if kind == "butterworth" else {})}
    return run


def _bilateral(image: np.ndarray, values: dict):
    color, space = float(values["bilateral_sigma_color"]), float(values["bilateral_sigma_space"])
    return _clip(bilateral_filter(image, color, space)), {"sigma_color": color, "sigma_space": space}


def _nlm(image: np.ndarray, values: dict):
    h = float(values["nlm_h"])
    out = non_local_means_filter(image, h, NLM_PATCH_SIZE, NLM_PATCH_DISTANCE)
    return _clip(out), {"h": h, "patch_size": NLM_PATCH_SIZE, "patch_distance": NLM_PATCH_DISTANCE}


def _wavelet(image: np.ndarray, values: dict):
    sigma = float(values["wavelet_sigma"])
    deepest = wavelet_max_level(image.shape, WAVELET_NAME)
    if deepest < 1:
        raise ValueError("The image is too small for wavelet shrinkage.")
    levels = min(WAVELET_LEVELS, deepest)
    out = wavelet_shrinkage_filter(image, sigma, WAVELET_NAME, levels, WAVELET_MAX_SHIFTS)
    return _clip(out), {"assumed_noise_sd": sigma, "wavelet": WAVELET_NAME, "levels": levels, "shifts_averaged": (WAVELET_MAX_SHIFTS + 1) ** 2}


METHODS: tuple[Method, ...] = (
    Method("mean", "Mean", "Spatial", "Box average over a square window.",
           "Noise is independent between pixels and the image is smooth at the window scale; edges and small structures are blurred.",
           (KERNEL_SIZE,), _mean, "Textbook definition; see docs/methods_and_decisions.md"),
    Method("median", "Median", "Spatial", "Median of a square window.",
           "Suited to impulse (salt-and-pepper) noise; non-linear and can flatten thin structures.",
           (KERNEL_SIZE,), _median, "Textbook definition; see docs/methods_and_decisions.md"),
    Method("gaussian", "Gaussian", "Spatial", "Gaussian-weighted average.",
           "Like the mean filter but with smoother weights; edges are blurred in proportion to sigma.",
           (KERNEL_SIZE, SIGMA), _gaussian, "Textbook definition; see docs/methods_and_decisions.md"),
    Method("fft_ideal", "Frequency ideal", "Frequency", "Hard cutoff low-pass in the Fourier domain.",
           "High frequencies are noise. The sharp cutoff rings near edges and the transform assumes periodic borders.",
           (CUTOFF,), _frequency("ideal"), "Textbook definition; formulas in docs/methods_and_decisions.md"),
    Method("fft_gauss", "Frequency Gaussian", "Frequency", "Gaussian low-pass in the Fourier domain.",
           "Smooth roll-off, no ringing; blurs like a spatial Gaussian under periodic borders.",
           (CUTOFF,), _frequency("gauss"), "Textbook definition; formulas in docs/methods_and_decisions.md"),
    Method("fft_butterworth", "Frequency Butterworth", "Frequency", "Order-2 Butterworth low-pass in the Fourier domain.",
           "Intermediate roll-off between the ideal and Gaussian filters.",
           (CUTOFF,), _frequency("butterworth"), "Textbook definition; formulas in docs/methods_and_decisions.md"),
    Method("bilateral", "Bilateral", "Edge-preserving", "Averages only pixels that are close in space and similar in intensity.",
           "Noise is small compared with the edges to keep; flat regions are smoothed, but noise on an edge is not.",
           (BILATERAL_COLOR, BILATERAL_SPACE), _bilateral, "Tomasi and Manduchi, ICCV 1998, doi:10.1109/ICCV.1998.710815", heavy=True),
    Method("nlm", "Non-local means", "Edge-preserving", "Averages pixels whose surrounding patches look alike, wherever they are.",
           "Image structures repeat; noise is independent and roughly Gaussian. The noise level is not supplied, only the strength h.",
           (NLM_H,), _nlm, "Buades, Coll and Morel, CVPR 2005, doi:10.1109/CVPR.2005.38", heavy=True),
    Method("wavelet", "Wavelet (BayesShrink)", "Wavelet", "Soft-thresholds wavelet coefficients, averaged over circular shifts.",
           "Noise is Gaussian and white; the image is sparse in the wavelet basis. Correlated noise is only partly removed.",
           (WAVELET_SIGMA,), _wavelet, "Chang, Yu and Vetterli, IEEE TIP 2000, doi:10.1109/83.862633", heavy=True,
           requires=(("pywt", "PyWavelets"),)),
)

BY_ID = {method.id: method for method in METHODS}
DEFAULT_METHOD_IDS = ("mean", "median", "gaussian", "fft_ideal", "fft_gauss", "fft_butterworth")
PARAMS = {p.name: p for method in METHODS for p in method.params}


def parse_method_ids(text: str) -> list[str]:
    """Comma-separated method ids, in request order without duplicates; unknown or empty selections raise ValueError."""
    ids: list[str] = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if part not in BY_ID:
            raise ValueError(f"Unknown method {part!r}. Valid methods: {', '.join(BY_ID)}.")
        if part not in ids:
            ids.append(part)
    if not ids:
        raise ValueError("Select at least one method.")
    return ids


def catalogue() -> list[dict]:
    return [method.as_dict() for method in METHODS]
