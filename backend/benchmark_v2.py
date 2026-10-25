"""Benchmark V2: classical filters on one clinical CT series with HU-defined synthetic noise.

Scope and limits (read before quoting any number):

* The clinical slice is a *noisy reference*, not a noise-free ground truth. Every error is
  an error relative to that reference.
* Noise levels (10, 25, 50 HU) are experimental scenarios, not validated clinical levels.
  The correlated-noise scenario is a simple construction (white noise smoothed by a
  Gaussian kernel and renormalised to the same standard deviation); it has not been
  validated against a measured CT noise power spectrum.
* Salt-and-pepper and speckle are separate robustness tests, not CT noise models.
* One patient series, a handful of slices: conclusions are limited to this series and
  these slices. Slices of one patient are not independent patients.
* Parameters of every filter are chosen on *tuning* slices only and then frozen; all
  reported numbers come from disjoint *test* slices and different noise realisations.

Evaluation mask (one rule, fixed before any noise exists):
  ``evaluation_mask(reference_hu)`` = largest connected region of the *clean reference*
  slice above -500 HU with its holes filled (body, including lungs and airways). It is
  computed once per slice from the reference only, so it is identical for every noise
  level, noise realisation, filter and parameter, and it is the same mask for the noisy
  image and for every filtered output. No pixel is dropped because of its HU value,
  its noise, or the display window.

Sensitivity to the CT field-of-view boundary:
  The principal mask touches the artificial padding (-2048 HU) where the body is truncated by
  the field of view. Smoothing filters are heavily penalised there (a ~2000 HU artificial step).
  ``inner_mask`` removes a band of ``INNER_MARGIN_PX`` pixels around the padding (an experimental
  choice) and every test output is scored on both masks; parameters are tuned on the principal mask.

SSIM:
  The primary SSIM averages the map only over pixels whose whole window lies inside the mask, so no
  pixel outside the mask can influence a score. The earlier definition (all mask pixels) is kept in
  the ``*_allpixels`` columns for sensitivity only.

Two intensity domains, kept apart on purpose:
  * HU metrics (RMSE_HU, MAE_HU, the tuning criterion): noise is added in HU and filters
    run on a *linear normalisation* of the HU image over the fixed range
    ``NORMALISATION_RANGE_HU``. This is not a display window and never clips: a value
    outside the range raises an error. Mean, median, Gaussian and FFT low-pass filters
    commute with such an affine map, so this is exact, not an approximation.
  * Windowed metrics (PSNR, SSIM, windowed RMSE/MAE): the reference and every output are
    displayed with the same fixed window (``DISPLAY_WINDOW_*``) *after* filtering, and
    the metrics are averaged over the same mask. Saturation at the window limits is part
    of the display definition and applies identically to reference and outputs.
    These are NOT comparable with the historical benchmark, where noise and filtering
    were applied after clipping to the lung window.

Outputs are written to ``--out``; the script refuses to write inside the repository
unless explicitly allowed, so historical results can never be overwritten by accident.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import cv2
import numpy as np
import pandas as pd
from scipy import ndimage
from skimage.metrics import structural_similarity

from evaluate_denoising import window_ct_slice
from filters import (NLM_PATCH_DISTANCE, NLM_PATCH_SIZE, WAVELET_LEVELS, WAVELET_MAX_SHIFTS, WAVELET_NAME, bilateral_filter,
                     non_local_means_filter, wavelet_shrinkage_filter)

SCHEMA_VERSION = 2
BODY_THRESHOLD_HU = -500.0
LUNG_THRESHOLD_HU = -400.0
MIN_LUNG_FRACTION = 0.10
# Display window used only for the "windowed" metrics. Conventional lung-window values
# (centre -600 HU, width 1500 HU), kept equal to the historical benchmark so the images
# are displayed the same way; it is not claimed to be clinically optimal.
DISPLAY_WINDOW_CENTER = -600.0
DISPLAY_WINDOW_WIDTH = 1500.0
# Linear normalisation range for filtering in the HU domain (not a display window).
# Chosen to contain every value that can occur: stored CT values reach -2048 (padding
# outside the field of view) and about +3800; noise adds a few hundred HU at most.
NORMALISATION_RANGE_HU = (-4096.0, 8192.0)
CORRELATION_SIGMA_PX = 1.0
SPECKLE_OFFSET_HU = 1000.0  # speckle is applied to (HU + 1000), so air (-1000 HU) stays unchanged
BUTTERWORTH_ORDER = 2
BASELINE = "Noisy (no filter)"


# --- conditions -------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    name: str
    description: str
    kind: str  # "white", "correlated", "salt_pepper" or "speckle"; all are defined in HU
    group: str  # "main" or "robustness"
    sigma_hu: float | None = None
    amount: float | None = None
    variance: float | None = None


CONDITIONS: tuple[Condition, ...] = (
    Condition("white_10HU", "White Gaussian noise, sigma 10 HU (scenario)", "white", "main", sigma_hu=10.0),
    Condition("white_25HU", "White Gaussian noise, sigma 25 HU (scenario)", "white", "main", sigma_hu=25.0),
    Condition("white_50HU", "White Gaussian noise, sigma 50 HU (scenario)", "white", "main", sigma_hu=50.0),
    Condition("correlated_10HU", "Gaussian-smoothed noise, sigma 10 HU, 1 px correlation (unvalidated construction)",
              "correlated", "main", sigma_hu=10.0),
    Condition("correlated_25HU", "Gaussian-smoothed noise, sigma 25 HU, 1 px correlation (unvalidated construction)",
              "correlated", "main", sigma_hu=25.0),
    Condition("correlated_50HU", "Gaussian-smoothed noise, sigma 50 HU, 1 px correlation (unvalidated construction)",
              "correlated", "main", sigma_hu=50.0),
    Condition("robustness_salt_pepper",
              "Impulse noise, 2 % of pixels set to the display-window limits (not a CT noise model)",
              "salt_pepper", "robustness", amount=0.02),
    Condition("robustness_speckle",
              "Multiplicative speckle on (HU + 1000), variance 0.02 (not a CT noise model)",
              "speckle", "robustness", variance=0.02),
)


# --- geometry: body mask, slice eligibility and split ------------------------------------


def body_mask(hu: np.ndarray, threshold: float = BODY_THRESHOLD_HU) -> np.ndarray:
    """Largest connected tissue region above ``threshold`` HU, holes (lungs, airways) filled."""
    if hu.ndim != 2:
        raise ValueError("hu must be a 2D array.")
    labels, count = ndimage.label(hu > threshold)
    if count == 0:
        return np.zeros(hu.shape, dtype=bool)
    sizes = ndimage.sum(np.ones_like(labels), labels, index=np.arange(1, count + 1))
    largest = labels == (int(np.argmax(sizes)) + 1)
    return ndimage.binary_fill_holes(largest)


def lung_fraction(hu: np.ndarray) -> float:
    """Fraction of the body area occupied by low-attenuation (lung-like) pixels."""
    body = body_mask(hu)
    if not body.any():
        return 0.0
    return float(np.count_nonzero(body & (hu < LUNG_THRESHOLD_HU)) / np.count_nonzero(body))


def eligible_slices(volume: np.ndarray, min_lung_fraction: float = MIN_LUNG_FRACTION) -> list[int]:
    """Indices of slices that contain enough lung parenchyma (excludes apex and base)."""
    return [i for i in range(volume.shape[0]) if lung_fraction(volume[i].astype(np.float64)) >= min_lung_fraction]


def split_slices(eligible: list[int], n_tune: int = 3, n_test: int = 8, min_gap: int = 3) -> tuple[list[int], list[int]]:
    """Choose tuning and test slices that are disjoint and at least ``min_gap`` slices apart.

    Neighbouring slices are strongly correlated, so a test slice may not sit next to a
    tuning slice. Both sets are spread evenly over the eligible range.
    """
    eligible = sorted(set(int(i) for i in eligible))
    if n_tune < 1 or n_test < 1 or min_gap < 1:
        raise ValueError("n_tune, n_test and min_gap must be positive.")
    if len(eligible) < n_tune:
        raise ValueError("Not enough eligible slices for tuning.")
    positions = np.linspace(0.25, 0.75, n_tune) if n_tune > 1 else np.array([0.5])
    tune = sorted({eligible[int(round(p * (len(eligible) - 1)))] for p in positions})
    candidates = [i for i in eligible if min(abs(i - t) for t in tune) >= min_gap]
    if len(candidates) < n_test:
        raise ValueError(f"Only {len(candidates)} eligible slices remain for testing; {n_test} requested.")
    picks = np.unique(np.round(np.linspace(0, len(candidates) - 1, n_test)).astype(int))
    test = [candidates[i] for i in picks]
    if len(test) < n_test:
        raise ValueError("Could not pick distinct test slices.")
    return tune, sorted(test)


# --- noise ----------------------------------------------------------------------------


def condition_seed(base_seed: int, slice_index: int, condition_index: int, repeat: int) -> int:
    """Stable, collision-resistant 32-bit seed for one slice/condition/repeat."""
    return int(np.random.SeedSequence([base_seed, slice_index, condition_index, repeat]).generate_state(1)[0])


def hu_noise(shape: tuple[int, int], sigma_hu: float, kind: str, seed: int,
             correlation_sigma_px: float = CORRELATION_SIGMA_PX) -> np.ndarray:
    """Zero-mean noise with standard deviation ``sigma_hu`` (white or Gaussian-smoothed)."""
    if sigma_hu <= 0 or not np.isfinite(sigma_hu):
        raise ValueError("sigma_hu must be positive and finite.")
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(shape)
    if kind == "white":
        return sigma_hu * white
    if kind == "correlated":
        impulse = np.zeros((int(8 * correlation_sigma_px) | 1,) * 2)
        impulse[impulse.shape[0] // 2, impulse.shape[1] // 2] = 1.0
        kernel = ndimage.gaussian_filter(impulse, correlation_sigma_px, mode="constant")
        gain = math.sqrt(float(np.sum(kernel**2)))  # std of the smoothed unit-variance white noise
        smoothed = ndimage.gaussian_filter(white, correlation_sigma_px, mode="wrap")
        return sigma_hu * smoothed / gain
    raise ValueError(f"Unknown HU noise kind: {kind!r}")


def window_bounds(center: float = DISPLAY_WINDOW_CENTER, width: float = DISPLAY_WINDOW_WIDTH) -> tuple[float, float]:
    """Lower and upper HU limits of the DICOM linear window (values at or beyond saturate)."""
    return center - 0.5 - (width - 1.0) / 2.0, center - 0.5 + (width - 1.0) / 2.0


def display(hu: np.ndarray) -> np.ndarray:
    """Display an HU image with the fixed V2 window, giving values in [0, 1]. Used for windowed metrics only."""
    return window_ct_slice(hu, DISPLAY_WINDOW_CENTER, DISPLAY_WINDOW_WIDTH)


def hu_span() -> float:
    """Width of the normalisation range: one HU is ``1 / hu_span()`` in the normalised image."""
    low, high = NORMALISATION_RANGE_HU
    return high - low


def hu_to_unit(hu: np.ndarray) -> np.ndarray:
    """Linear normalisation of HU to (0, 1) over ``NORMALISATION_RANGE_HU``; refuses to clip."""
    low, high = NORMALISATION_RANGE_HU
    if hu.size and (float(hu.min()) < low or float(hu.max()) > high):
        raise ValueError(f"HU values [{float(hu.min()):.0f}, {float(hu.max()):.0f}] fall outside the "
                         f"normalisation range [{low:.0f}, {high:.0f}]; refusing to clip.")
    return (hu - low) / (high - low)


def unit_to_hu(unit: np.ndarray) -> np.ndarray:
    low, high = NORMALISATION_RANGE_HU
    return unit * (high - low) + low


def evaluation_mask(reference_hu: np.ndarray) -> np.ndarray:
    """The principal evaluation mask: the body of the *clean reference* slice.

    Depends only on the reference image, never on the noise, the noise level, the filter
    or its parameters, and never on the display window.
    """
    return body_mask(reference_hu)


PADDING_HU = -1500.0        # at or below this value a pixel is the artificial padding outside the field of view
INNER_MARGIN_PX = 10        # EXPERIMENTAL choice (about 5.4 mm here); not clinically validated
MIN_INNER_FRACTION = 0.5    # protocol guard: the inner mask must keep at least half of the principal mask
MASK_NAMES = ("main", "inner")


def padding_mask(reference_hu: np.ndarray) -> np.ndarray:
    return reference_hu <= PADDING_HU


def inner_mask(reference_hu: np.ndarray, margin_px: float = INNER_MARGIN_PX, main: np.ndarray | None = None) -> np.ndarray:
    """Sensitivity mask: the principal mask without a band around the artificial padding.

    Removes every pixel whose Euclidean distance to the nearest padding pixel
    (``HU <= PADDING_HU``) is at most ``margin_px``. Computed from the clean reference only.
    Without padding it equals the principal mask.
    """
    main = evaluation_mask(reference_hu) if main is None else main
    padding = padding_mask(reference_hu)
    if not padding.any():
        return main.copy()
    distance = ndimage.distance_transform_edt(~padding)
    return main & (distance > margin_px)


def reference_masks(reference_hu: np.ndarray) -> dict[str, np.ndarray]:
    """Both masks of one slice, computed once from the clean reference."""
    main = evaluation_mask(reference_hu)
    return {"main": main, "inner": inner_mask(reference_hu, main=main)}


def impulse_noise(hu: np.ndarray, amount: float, seed: int) -> np.ndarray:
    """Replace a fraction ``amount`` of pixels by the lower or upper display-window limit (50/50)."""
    if not (0.0 <= amount <= 1.0):
        raise ValueError("amount must be within [0, 1].")
    rng = np.random.default_rng(seed)
    affected = rng.random(hu.shape) < amount
    salt = rng.random(hu.shape) < 0.5
    lower, upper = window_bounds()
    noisy = hu.copy()
    noisy[affected & salt] = upper
    noisy[affected & ~salt] = lower
    return noisy


def speckle_noise(hu: np.ndarray, variance: float, seed: int) -> np.ndarray:
    """Multiplicative noise on ``HU + 1000`` (air = 0 stays unchanged): x + x * N(0, variance)."""
    if variance < 0 or not np.isfinite(variance):
        raise ValueError("variance must be non-negative and finite.")
    rng = np.random.default_rng(seed)
    return hu + (hu + SPECKLE_OFFSET_HU) * math.sqrt(variance) * rng.standard_normal(hu.shape)


@dataclass(frozen=True)
class Case:
    """One slice under one noise realisation.

    ``mask`` (principal) and ``inner_mask`` (sensitivity) come from the clean reference and
    are shared by the noisy image and by every filtered output evaluated on this case.
    """

    reference_hu: np.ndarray
    noisy_hu: np.ndarray
    mask: np.ndarray
    inner_mask: np.ndarray | None = None

    def masks(self) -> dict[str, np.ndarray]:
        return {"main": self.mask, "inner": self.mask if self.inner_mask is None else self.inner_mask}


def make_case(hu: np.ndarray, condition: Condition, seed: int, masks: dict[str, np.ndarray] | None = None) -> Case:
    """Build the noisy image in HU; masks come from the clean reference (pass ``masks`` to reuse them)."""
    reference = hu.astype(np.float64)
    if condition.kind in ("white", "correlated"):
        noisy = reference + hu_noise(reference.shape, condition.sigma_hu, condition.kind, seed)
    elif condition.kind == "salt_pepper":
        noisy = impulse_noise(reference, condition.amount, seed)
    elif condition.kind == "speckle":
        noisy = speckle_noise(reference, condition.variance, seed)
    else:
        raise ValueError(f"Unknown condition kind: {condition.kind!r}")
    masks = reference_masks(reference) if masks is None else masks
    return Case(reference, noisy, masks["main"], masks["inner"])


# --- filters and parameter grids ------------------------------------------------------


FREQUENCY_FAMILIES = {"FFT ideal": "ideal", "FFT Gaussian": "gauss", "FFT Butterworth": "butterworth"}
FAMILIES = ("Mean", "Median", "Gaussian", *FREQUENCY_FAMILIES)   # the six families of the "v1" and "expanded" grids
# Three further denoisers, added in the "methods" grid. Each has ONE tuned strength parameter, in HU, so every family
# is tuned with the same budget of one scalar; the other hyper-parameters are fixed and recorded in the parameters of
# each selected configuration. ``None`` for the strength parameter is the identity.
#   Bilateral (Tomasi and Manduchi, 1998)      strength: intensity scale sigma_color_hu; spatial scale fixed
#   Non-local means (Buades et al., 2005)      strength: filtering parameter h_hu; patch and search window fixed
#   Wavelet BayesShrink (Chang et al., 2000)   strength: ASSUMED noise level sigma_hu (a strength control, not a
#                                              measurement); sym4, 3 levels, soft thresholds, 16 circular shifts
ADVANCED_FAMILIES = {"Bilateral": "sigma_color_hu", "Non-local means": "h_hu", "Wavelet BayesShrink": "sigma_hu"}
ALL_FAMILIES = (*FAMILIES, *ADVANCED_FAMILIES)       # every family any grid version can contain
BILATERAL_SIGMA_SPACE_PX = 1.5
# NLM_PATCH_SIZE, NLM_PATCH_DISTANCE and the WAVELET_* settings are shared with the lab (imported from filters).
# Strength grids in HU, fixed from sweeps on the three TUNING slices only (no test slice was scored). Ascending
# strength after the identity, so an exact tie goes to the weaker smoothing.
BILATERAL_SIGMA_COLOR_GRID_HU = (5, 8, 12, 16, 20, 25, 32, 40, 50, 65, 80, 100, 130, 160, 200, 260, 320, 500, 800)
NLM_H_GRID_HU = (3, 5, 8, 12, 16, 20, 25, 32, 40, 50, 65, 80, 100, 130, 160, 200, 260)
WAVELET_SIGMA_GRID_HU = (5, 8, 12, 16, 20, 30, 40, 50, 65, 80, 100, 130, 160, 200, 260, 320, 400, 500)
# Grid of the first V2 run ("v1"). Kept unchanged so that run stays reproducible.
KERNEL_GRID_V1 = (3, 5, 7, 9, 11)
GAUSSIAN_SIGMA_GRID_V1 = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
CUTOFF_GRID_V1 = (0.05, 0.08, 0.10, 0.15, 0.20, 0.30, 0.40)

# Expanded grid. The first run selected the WEAKEST smoothing of the grid in 43 of 48 cases (none at the
# strongest end), so the grid is extended only towards weaker smoothing, plus an explicit identity:
#   Mean / Median : kernel_size 1 is the identity (odd kernels only, so 1 -> 3 is the finest step).
#   Gaussian      : sigma 0 is the identity (kernel 1); 0.2-0.4 fill the steep region below 0.5 where the
#                   tuning RMSE rises quickly. Kernel size is 2*ceil(3*sigma)+1 as before.
#   FFT           : the cutoff is a fraction of Nyquist, and a LARGER cutoff means LESS smoothing. Values up to 4
#                   are added; cutoff None (null in JSON) is the identity. The ideal mask is exactly the identity
#                   from sqrt(2) on (the corner of the spectrum); Gaussian and Butterworth only approach it.
KERNEL_GRID = (1, 3, 5, 7, 9, 11)
GAUSSIAN_SIGMA_GRID = (0.0, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
CUTOFF_GRID = (0.05, 0.08, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.80, 1.0, 1.5, 2.0, 3.0, 4.0)
GRID_VERSIONS = ("v1", "expanded", "methods")


def advanced_configs(family: str) -> list[dict]:
    """Configurations of one added denoiser, from the identity to the strongest setting."""
    if family == "Bilateral":
        return [{"sigma_color_hu": s, "sigma_space_px": BILATERAL_SIGMA_SPACE_PX} for s in (None, *BILATERAL_SIGMA_COLOR_GRID_HU)]
    if family == "Non-local means":
        return [{"h_hu": h, "patch_size": NLM_PATCH_SIZE, "patch_distance": NLM_PATCH_DISTANCE} for h in (None, *NLM_H_GRID_HU)]
    if family == "Wavelet BayesShrink":
        return [{"sigma_hu": s, "wavelet": WAVELET_NAME, "levels": WAVELET_LEVELS, "max_shifts": WAVELET_MAX_SHIFTS}
                for s in (None, *WAVELET_SIGMA_GRID_HU)]
    raise ValueError(f"Unknown denoiser family: {family!r}")


def parameter_grid(grid_version: str = "expanded") -> dict[str, list[dict]]:
    """Filter configurations to tune, per family.

    ``"expanded"`` lists every family from the WEAKEST smoothing (identity) to the strongest, so an exact
    tie in the tuning score goes to the weaker smoothing. ``"v1"`` is the first run's grid, unchanged.
    ``"methods"`` is the expanded grid plus the bilateral, non-local-means and wavelet families; the six
    original families keep exactly their expanded configurations.
    """
    if grid_version == "v1":
        grid: dict[str, list[dict]] = {
            "Mean": [{"kernel_size": k} for k in KERNEL_GRID_V1],
            "Median": [{"kernel_size": k} for k in KERNEL_GRID_V1],
            "Gaussian": [{"sigma": s, "kernel_size": 2 * math.ceil(3 * s) + 1} for s in GAUSSIAN_SIGMA_GRID_V1],
        }
        for family in FREQUENCY_FAMILIES:
            grid[family] = [{"cutoff_ratio": c} for c in CUTOFF_GRID_V1]
        return grid
    if grid_version not in ("expanded", "methods"):
        raise ValueError(f"grid_version must be one of {GRID_VERSIONS}.")
    grid = {
        "Mean": [{"kernel_size": k} for k in KERNEL_GRID],
        "Median": [{"kernel_size": k} for k in KERNEL_GRID],
        "Gaussian": [{"sigma": s, "kernel_size": 1 if s == 0 else 2 * math.ceil(3 * s) + 1} for s in GAUSSIAN_SIGMA_GRID],
    }
    for family in FREQUENCY_FAMILIES:
        grid[family] = [{"cutoff_ratio": None}] + [{"cutoff_ratio": c} for c in sorted(CUTOFF_GRID, reverse=True)]
    if grid_version == "methods":
        for family in ADVANCED_FAMILIES:
            grid[family] = advanced_configs(family)
    return grid


def is_identity(family: str, params: dict) -> bool:
    """True for the configuration that leaves the image unchanged."""
    if family in ("Mean", "Median"):
        return int(params["kernel_size"]) == 1
    if family == "Gaussian":
        return float(params["sigma"]) == 0.0
    if family in ADVANCED_FAMILIES:
        return params[ADVANCED_FAMILIES[family]] is None
    return params["cutoff_ratio"] is None


def smoothing_strength(family: str, params: dict) -> float:
    """Increases with the amount of smoothing (0 = identity), whatever the parameter's own direction."""
    if is_identity(family, params):
        return 0.0
    if family in ("Mean", "Median"):
        return float(params["kernel_size"])
    if family == "Gaussian":
        return float(params["sigma"])
    if family in ADVANCED_FAMILIES:
        return float(params[ADVANCED_FAMILIES[family]])    # a larger tolerance or assumed noise level smooths more
    return 1.0 / float(params["cutoff_ratio"])             # a larger FFT cutoff keeps more frequencies


def fft_lowpass(image: np.ndarray, cutoff_ratio: float, kind: str, order: int = BUTTERWORTH_ORDER) -> np.ndarray:
    """Ideal / Gaussian / Butterworth low-pass of a 2D image, without clipping.

    Same formulas as ``filters.apply_frequency_lowpass`` (the cutoff radius is ``cutoff_ratio`` times the
    smaller half-dimension, in frequency bins), but the cutoff may exceed 1 so that the filter can approach
    the identity, and nothing is clipped. Equal to the shared implementation, up to its final clip, for
    cutoffs in (0, 1).
    """
    if kind not in FREQUENCY_FAMILIES.values():
        raise ValueError(f"Unknown frequency filter kind: {kind!r}")
    if not np.isfinite(cutoff_ratio) or cutoff_ratio <= 0:
        raise ValueError("cutoff_ratio must be positive and finite.")
    rows, cols = image.shape
    crow, ccol = rows // 2, cols // 2
    shifted = np.fft.fftshift(np.fft.fft2(image))
    y, x = np.ogrid[-crow:rows - crow, -ccol:cols - ccol]
    radius = np.sqrt(x**2 + y**2)
    cutoff = cutoff_ratio * min(crow, ccol)
    if kind == "ideal":
        mask = (radius <= cutoff).astype(np.float64)
    elif kind == "gauss":
        mask = np.exp(-(radius**2) / (2.0 * cutoff**2))
    else:
        mask = 1.0 / (1.0 + (radius / cutoff) ** (2 * order))
    return np.real(np.fft.ifft2(np.fft.ifftshift(shifted * mask)))


def apply_filter(image: np.ndarray, family: str, params: dict, clip: bool = True) -> np.ndarray:
    """Apply one filter configuration to a [0, 1] image (same library calls as filters.py)."""
    if family == "Mean":
        k = int(params["kernel_size"])
        out = cv2.boxFilter(image, -1, (k, k), borderType=cv2.BORDER_REFLECT101)
    elif family == "Median":
        out = ndimage.median_filter(image.astype(np.float64), size=int(params["kernel_size"]), mode="reflect")
    elif family == "Gaussian":
        k = int(params["kernel_size"])
        if float(params["sigma"]) == 0.0:       # cv2 would read sigma 0 as "derive it from the kernel"; here it means identity
            out = image
        else:
            out = cv2.GaussianBlur(image, (k, k), sigmaX=float(params["sigma"]), borderType=cv2.BORDER_REFLECT101)
    elif family in FREQUENCY_FAMILIES:
        if params["cutoff_ratio"] is None:
            out = image
        else:
            out = fft_lowpass(image, float(params["cutoff_ratio"]), FREQUENCY_FAMILIES[family])
    elif family in ADVANCED_FAMILIES:
        strength = params[ADVANCED_FAMILIES[family]]
        if strength is None:
            out = image
        elif family == "Bilateral":
            out = bilateral_filter(image, float(strength) / hu_span(), float(params["sigma_space_px"]))
        elif family == "Non-local means":
            out = non_local_means_filter(image, float(strength) / hu_span(), int(params["patch_size"]), int(params["patch_distance"]))
        else:
            out = wavelet_shrinkage_filter(image, float(strength) / hu_span(), str(params["wavelet"]),
                                           int(params["levels"]), int(params["max_shifts"]))
    elif family == BASELINE:
        out = image
    else:
        raise ValueError(f"Unknown filter family: {family!r}")
    return np.clip(out, 0.0, 1.0) if clip else out


def filter_hu(noisy_hu: np.ndarray, family: str, params: dict) -> np.ndarray:
    """Filter an HU image without any clipping and return the result in HU.

    The image is mapped linearly into (0, 1) over the fixed normalisation range, filtered,
    and mapped back. If an output touches 0 or 1 (which would mean a filter clipped it,
    since the FFT filter clips internally) the run stops instead of continuing silently.
    """
    if family == BASELINE:
        return noisy_hu
    out = apply_filter(hu_to_unit(noisy_hu), family, params, clip=False)
    if float(out.min()) <= 0.0 or float(out.max()) >= 1.0:
        raise RuntimeError("A filtered output reached the normalisation range limit; possible clipping.")
    return unit_to_hu(out)


# --- metrics ---------------------------------------------------------------------------


def check_image_pair(reference: np.ndarray, output: np.ndarray, mask: np.ndarray | None = None) -> None:
    """Reject inputs that would silently give a wrong metric: other shapes, other dimensions, NaN or Inf.

    Broadcasting a (1, N) array against an (N, N) image, or a NaN in one pixel, would otherwise give a
    plausible-looking number or a NaN that propagates into the aggregation.
    """
    if reference.ndim != 2 or reference.shape != output.shape:
        raise ValueError(f"reference and output must be 2D arrays of the same shape, got {reference.shape} and {output.shape}")
    if mask is not None and mask.shape != reference.shape:
        raise ValueError(f"the mask shape {mask.shape} differs from the image shape {reference.shape}")
    if not (np.isfinite(reference).all() and np.isfinite(output).all()):
        raise ValueError("the images must contain only finite values (no NaN or Inf)")


def hu_errors(reference_hu: np.ndarray, output_hu: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    """RMSE and MAE in HU between ``output_hu`` and ``reference_hu`` over the mask."""
    check_image_pair(reference_hu, output_hu, mask)
    if not mask.any():
        return float("nan"), float("nan")
    diff = (output_hu - reference_hu)[mask]
    return float(np.sqrt(np.mean(diff**2))), float(np.mean(np.abs(diff)))


def windowed_errors(reference_display: np.ndarray, output_display: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    """RMSE and MAE on the displayed [0, 1] images over the mask."""
    return hu_errors(reference_display, output_display, mask)


def masked_psnr(reference_display: np.ndarray, output_display: np.ndarray, mask: np.ndarray) -> float:
    """PSNR (peak 1) over the mask; infinite for a perfect reconstruction."""
    check_image_pair(reference_display, output_display, mask)
    mse = float(np.mean((output_display - reference_display)[mask] ** 2))
    return float("inf") if mse == 0.0 else float(10.0 * np.log10(1.0 / mse))


SSIM_RADIUS_DEFAULT = 3   # 7x7 uniform window of scikit-image: a pixel's score reads pixels up to 3 px away
SSIM_RADIUS_WANG = 5      # 11x11 Gaussian window (sigma 1.5, truncated at 3.5 sigma): up to 5 px away
SSIM_OPTIONS = {False: {}, True: dict(gaussian_weights=True, sigma=1.5, use_sample_covariance=False)}


def ssim_interior_mask(mask: np.ndarray, wang: bool = False) -> np.ndarray:
    """Pixels of ``mask`` whose whole SSIM window lies inside ``mask`` (and inside the image)."""
    radius = SSIM_RADIUS_WANG if wang else SSIM_RADIUS_DEFAULT
    return ndimage.binary_erosion(mask, structure=np.ones((2 * radius + 1, 2 * radius + 1), dtype=bool), border_value=0)


def ssim_map(reference_display: np.ndarray, output_display: np.ndarray, wang: bool = False) -> np.ndarray:
    return structural_similarity(reference_display, output_display, data_range=1.0, full=True, **SSIM_OPTIONS[wang])[1]


def masked_ssim(reference_display: np.ndarray, output_display: np.ndarray, mask: np.ndarray, wang: bool = False,
                fully_inside: bool = True) -> float:
    """Mean of the SSIM map over the mask. ``wang`` uses the 11x11 Gaussian window of Wang et al. (2004).

    PRIMARY definition (``fully_inside=True``, the default): only pixels whose whole window
    lies inside the mask are scored, so nothing outside the mask can influence the score
    (``nan`` if no such pixel exists). ``fully_inside=False`` is the earlier definition kept
    for the sensitivity analysis: every mask pixel is scored, so pixels near the boundary use
    windows that also read pixels outside the mask.
    """
    selected = ssim_interior_mask(mask, wang) if fully_inside else mask
    return float(ssim_map(reference_display, output_display, wang)[selected].mean()) if selected.any() else float("nan")


def evaluate_masks(case: Case, output_hu: np.ndarray, mask_names: tuple[str, ...] = MASK_NAMES) -> dict[str, dict[str, float]]:
    """Full metrics of one output for each requested mask; the display and the SSIM maps are computed once.

    Primary SSIM columns (``SSIM_skimage_default``, ``SSIM_Wang2004``) use windows fully inside the
    mask; ``*_allpixels`` columns hold the earlier definition (sensitivity only).
    """
    check_image_pair(case.reference_hu, output_hu)
    reference_display, output_display = display(case.reference_hu), display(output_hu)
    maps = {wang: ssim_map(reference_display, output_display, wang) for wang in (False, True)}
    results = {}
    for name in mask_names:
        mask = case.masks()[name]
        rmse_hu, mae_hu = hu_errors(case.reference_hu, output_hu, mask)
        result = {"RMSE_HU": rmse_hu, "MAE_HU": mae_hu}
        result["RMSE_windowed"], result["MAE_windowed"] = windowed_errors(reference_display, output_display, mask)
        result["PSNR_dB"] = masked_psnr(reference_display, output_display, mask)
        for wang, label in ((False, "SSIM_skimage_default"), (True, "SSIM_Wang2004")):
            interior = ssim_interior_mask(mask, wang)
            result[label] = float(maps[wang][interior].mean()) if interior.any() else float("nan")
            result[label + "_allpixels"] = float(maps[wang][mask].mean()) if mask.any() else float("nan")
            result["ssim_pixels_wang" if wang else "ssim_pixels_default"] = int(interior.sum())
        results[name] = result
    return results


def evaluate_output(case: Case, output_hu: np.ndarray, full: bool = True, mask_name: str = "main") -> dict[str, float]:
    """Metrics of one output against the reference over the chosen mask (principal by default).

    ``full=False`` returns only the HU errors (what tuning needs).
    """
    if not full:
        rmse_hu, mae_hu = hu_errors(case.reference_hu, output_hu, case.masks()[mask_name])
        return {"RMSE_HU": rmse_hu, "MAE_HU": mae_hu}
    return evaluate_masks(case, output_hu, (mask_name,))[mask_name]


# --- statistics ------------------------------------------------------------------------


def bootstrap_ci(values: Iterable[float], n_boot: int = 10000, alpha: float = 0.05, seed: int = 12345) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for the mean, resampling *slices*."""
    data = np.asarray(list(values), dtype=np.float64)
    data = data[np.isfinite(data)]
    if data.size == 0:
        return float("nan"), float("nan")
    if data.size == 1:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = data[rng.integers(0, data.size, size=(n_boot, data.size))].mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


# --- tuning and testing ----------------------------------------------------------------


TUNING_CRITERION = "RMSE_HU"      # the selection criterion; it was not changed when the grid was expanded


def tuning_secondary_metrics(case: Case, output_hu: np.ndarray) -> tuple[float, float]:
    """PSNR and primary Wang SSIM on the principal mask. Recorded on tuning cases for information only:
    they never select a parameter, they only show where the criteria disagree."""
    reference_display, output_display = display(case.reference_hu), display(output_hu)
    return (masked_psnr(reference_display, output_display, case.mask),
            masked_ssim(reference_display, output_display, case.mask, wang=True))


def tune_condition(cases: list[Case], condition: Condition,
                   grid: dict[str, list[dict]] | None = None) -> tuple[pd.DataFrame, dict[str, dict]]:
    """Score every grid configuration on the tuning cases and pick the best per family.

    ``cases`` are built from tuning slices only. The criterion is the mean RMSE in HU over
    the fixed evaluation mask; ties go to the first configuration in the grid.
    """
    grid = grid or parameter_grid()
    rows = []
    for family, configs in grid.items():
        for params in configs:
            outputs = [filter_hu(case.noisy_hu, family, params) for case in cases]
            scores = [evaluate_output(case, output, full=False)[TUNING_CRITERION] for case, output in zip(cases, outputs)]
            secondary = [tuning_secondary_metrics(case, output) for case, output in zip(cases, outputs)]
            rows.append({"condition": condition.name, "family": family, "params": json.dumps(params, sort_keys=True),
                         "criterion": TUNING_CRITERION, "mean_score": float(np.mean(scores)),
                         "mean_PSNR_dB": float(np.mean([s[0] for s in secondary])),
                         "mean_SSIM_Wang2004": float(np.mean([s[1] for s in secondary])),
                         "n_tuning_cases": len(cases)})
    table = pd.DataFrame(rows)
    selected = {}
    for family, group in table.groupby("family", sort=False):
        best = group.loc[group["mean_score"].idxmin()]
        selected[family] = json.loads(best["params"])
    return table, selected


def grid_bracketing(selected: pd.DataFrame, tuning_grid: pd.DataFrame) -> pd.DataFrame:
    """Where does each selected configuration sit in its family's grid, ordered from weakest to strongest smoothing?

    * ``identity``: no filtering has the lowest tuning RMSE; the identity is the natural weakest bound,
      so this says that smoothing with this family does not help on the tuning slices.
    * ``interior``: both a weaker and a stronger neighbour exist and score worse, so the minimum is bracketed.
    * ``weakest_end`` / ``strongest_end``: the minimum is at an end of the grid and is NOT bracketed.
    """
    rows = []
    for r in selected.itertuples():
        g = tuning_grid[(tuning_grid.condition == r.condition) & (tuning_grid.family == r.family)].copy()
        g["parameters"] = g["params"].map(json.loads)
        g["strength"] = [smoothing_strength(r.family, p) for p in g["parameters"]]
        g = g.sort_values("strength", kind="stable").reset_index(drop=True)
        position = int(g.index[g["params"] == r.params][0])
        last = len(g) - 1
        if is_identity(r.family, json.loads(r.params)):
            status = "identity"
        elif position == 0:
            status = "weakest_end"
        elif position == last:
            status = "strongest_end"
        else:
            status = "interior"
        weaker = float(g.loc[position - 1, "mean_score"]) if position > 0 else float("nan")
        stronger = float(g.loc[position + 1, "mean_score"]) if position < last else float("nan")
        rows.append({"condition": r.condition, "family": r.family, "selected": r.params, "position": position + 1, "grid_size": last + 1,
                     "status": status, "bracketed": status in ("interior", "identity"), "score": float(g.loc[position, "mean_score"]),
                     "weaker_neighbour_score": weaker, "stronger_neighbour_score": stronger})
    return pd.DataFrame(rows)


def tuning_criteria_comparison(tuning_grid: pd.DataFrame) -> pd.DataFrame:
    """Parameter each criterion would pick on the tuning slices. Only RMSE_HU is used to select; the rest is informative."""
    rows = []
    for (condition, family), g in tuning_grid.groupby(["condition", "family"], sort=False):
        rmse = g.loc[g["mean_score"].idxmin(), "params"]
        psnr = g.loc[g["mean_PSNR_dB"].idxmax(), "params"]
        ssim = g.loc[g["mean_SSIM_Wang2004"].idxmax(), "params"]
        rows.append({"condition": condition, "family": family, "selected_by_RMSE_HU": rmse, "best_by_PSNR": psnr, "best_by_SSIM_Wang2004": ssim,
                     "PSNR_agrees": psnr == rmse, "SSIM_agrees": ssim == rmse})
    return pd.DataFrame(rows)


# --- full run --------------------------------------------------------------------------


@dataclass
class Config:
    tune_slices: list[int]
    test_slices: list[int]
    tune_repeats: int = 2
    test_repeats: int = 5
    tune_base_seed: int = 1_000
    test_base_seed: int = 2_000_000
    n_boot: int = 10000
    grid_version: str = "expanded"


def mask_fingerprint(mask: np.ndarray) -> str:
    return hashlib.sha256(np.packbits(mask).tobytes() + str(mask.shape).encode()).hexdigest()


def mask_summary_table(masks_by_slice: dict[int, dict[str, np.ndarray]], config: Config, reference_hu_by_slice: dict[int, np.ndarray]) -> pd.DataFrame:
    """One row per slice: pixel counts of both masks, the band removed by the inner mask, and the SSIM-evaluated counts."""
    rows = []
    for index, masks in sorted(masks_by_slice.items()):
        main, inner = masks["main"], masks["inner"]
        rows.append({
            "slice": index, "role": "test" if index in config.test_slices else "tuning",
            "main_pixels": int(main.sum()), "inner_pixels": int(inner.sum()),
            "inner_fraction_of_main": float(inner.sum() / main.sum()), "band_removed_pixels": int(main.sum() - inner.sum()),
            "padding_pixels": int(padding_mask(reference_hu_by_slice[index]).sum()),
            "ssim_pixels_default_main": int(ssim_interior_mask(main, False).sum()), "ssim_pixels_wang_main": int(ssim_interior_mask(main, True).sum()),
            "ssim_pixels_default_inner": int(ssim_interior_mask(inner, False).sum()), "ssim_pixels_wang_inner": int(ssim_interior_mask(inner, True).sum()),
            "main_mask_sha256": mask_fingerprint(main), "inner_mask_sha256": mask_fingerprint(inner),
        })
    return pd.DataFrame(rows)


def run_benchmark(volume: np.ndarray, config: Config, conditions: tuple[Condition, ...] = CONDITIONS,
                  log: Callable[[str], None] = lambda message: None) -> dict[str, pd.DataFrame]:
    """Tune on ``config.tune_slices`` and evaluate the frozen parameters on ``config.test_slices``.

    Parameters are tuned on the principal mask only. Every test output is scored on BOTH masks.
    Both masks of a slice are computed once, from the clean reference, before any noise exists.
    """
    if set(config.tune_slices) & set(config.test_slices):
        raise ValueError("Tuning and test slices must be disjoint.")
    references = {i: volume[i].astype(np.float64) for i in sorted(set(config.tune_slices) | set(config.test_slices))}
    masks_by_slice = {i: reference_masks(reference) for i, reference in references.items()}
    for index in config.test_slices:
        fraction = masks_by_slice[index]["inner"].sum() / masks_by_slice[index]["main"].sum()
        if fraction < MIN_INNER_FRACTION:
            raise ValueError(f"The inner mask keeps only {fraction:.0%} of the principal mask on slice {index} (minimum {MIN_INNER_FRACTION:.0%}).")
    tuning_tables, selection_rows, test_rows = [], [], []
    for condition_index, condition in enumerate(conditions):
        # 1. tuning: tuning slices and tuning seeds only, principal mask
        cases = []
        for index in config.tune_slices:
            for repeat in range(config.tune_repeats):
                seed = condition_seed(config.tune_base_seed, index, condition_index, repeat)
                cases.append(make_case(volume[index], condition, seed, masks=masks_by_slice[index]))
        table, selected = tune_condition(cases, condition, parameter_grid(config.grid_version))
        tuning_tables.append(table)
        for family, params in selected.items():
            best = table[(table.family == family) & (table.params == json.dumps(params, sort_keys=True))].iloc[0]
            selection_rows.append({"condition": condition.name, "family": family, "params": json.dumps(params, sort_keys=True),
                                   "tuning_criterion": best["criterion"], "tuning_score": best["mean_score"]})
        log(f"[{condition.name}] tuned on slices {config.tune_slices}")
        # 2. test: frozen parameters, disjoint slices, different seeds, both masks
        for index in config.test_slices:
            for repeat in range(config.test_repeats):
                seed = condition_seed(config.test_base_seed, index, condition_index, repeat)
                case = make_case(volume[index], condition, seed, masks=masks_by_slice[index])
                outputs = {BASELINE: case.noisy_hu, **{f: filter_hu(case.noisy_hu, f, p) for f, p in selected.items()}}
                for family, output in outputs.items():
                    for mask_name, metrics in evaluate_masks(case, output).items():
                        test_rows.append({"condition": condition.name, "group": condition.group, "mask": mask_name, "slice": index,
                                          "repeat": repeat + 1, "seed": seed, "family": family,
                                          "mask_pixels": int(case.masks()[mask_name].sum()),
                                          "params": json.dumps(selected.get(family, {}), sort_keys=True), **metrics})
        log(f"[{condition.name}] evaluated on slices {config.test_slices}")

    tuning = pd.concat(tuning_tables, ignore_index=True)
    selection = pd.DataFrame(selection_rows)
    per_run = pd.DataFrame(test_rows)
    per_slice = (per_run.groupby(["condition", "group", "mask", "slice", "family"], as_index=False, sort=False)
                 .agg(**{c: (c, "mean") for c in METRIC_COLUMNS}, mask_pixels=("mask_pixels", "first"),
                      ssim_pixels_default=("ssim_pixels_default", "first"), ssim_pixels_wang=("ssim_pixels_wang", "first"),
                      n_repeats=("repeat", "size")))
    return {"tuning_grid": tuning, "selected_parameters": selection, "grid_bracketing": grid_bracketing(selection, tuning),
            "tuning_criteria_comparison": tuning_criteria_comparison(tuning), "mask_summary": mask_summary_table(masks_by_slice, config, references),
            "test_per_run": per_run, "test_per_slice": per_slice, "test_summary": summarise(per_slice, config.n_boot),
            "test_pairwise": pairwise_differences(per_slice, config.n_boot),
            "mask_sensitivity": mask_sensitivity(per_slice, config.n_boot), "mask_ranking": mask_ranking(per_slice),
            "ssim_sensitivity": ssim_sensitivity(per_slice, config.n_boot)}


METRIC_COLUMNS = ["RMSE_HU", "MAE_HU", "RMSE_windowed", "MAE_windowed", "PSNR_dB", "SSIM_skimage_default", "SSIM_Wang2004",
                  "SSIM_skimage_default_allpixels", "SSIM_Wang2004_allpixels"]


def _mean_or_nan(values: np.ndarray) -> float:
    return float(np.nanmean(values)) if np.isfinite(values).any() else float("nan")


def summarise(per_slice: pd.DataFrame, n_boot: int) -> pd.DataFrame:
    """Mean over slices with bootstrap CI, plus the paired gain over the unfiltered image (per mask)."""
    rows = []
    for (condition, mask, family), group in per_slice.groupby(["condition", "mask", "family"], sort=False):
        baseline = per_slice[(per_slice.condition == condition) & (per_slice["mask"] == mask) & (per_slice.family == BASELINE)].set_index("slice")
        group = group.set_index("slice")
        row = {"condition": condition, "group": group["group"].iloc[0], "mask": mask, "family": family, "n_slices": int(group.shape[0])}
        for metric in METRIC_COLUMNS:
            values = group[metric].to_numpy()
            low, high = bootstrap_ci(values, n_boot)
            row[f"{metric}_mean"], row[f"{metric}_ci_low"], row[f"{metric}_ci_high"] = _mean_or_nan(values), low, high
            if family != BASELINE:
                diff = (group[metric] - baseline[metric].reindex(group.index)).to_numpy()
                dlow, dhigh = bootstrap_ci(diff, n_boot)
                row[f"{metric}_gain_mean"] = _mean_or_nan(diff)
                row[f"{metric}_gain_ci_low"], row[f"{metric}_gain_ci_high"] = dlow, dhigh
        rows.append(row)
    return pd.DataFrame(rows)


def pairwise_differences(per_slice: pd.DataFrame, n_boot: int, metrics: tuple[str, ...] = ("RMSE_HU", "RMSE_windowed", "SSIM_Wang2004")) -> pd.DataFrame:
    """Paired (same slice) differences A - B between filter families with bootstrap CIs (per mask)."""
    rows = []
    for (condition, mask), cond_group in per_slice.groupby(["condition", "mask"], sort=False):
        wide = {m: cond_group.pivot(index="slice", columns="family", values=m) for m in metrics}
        families = [f for f in ALL_FAMILIES if f in cond_group["family"].unique()]
        for i, a in enumerate(families):
            for b in families[i + 1:]:
                for metric in metrics:
                    diff = (wide[metric][a] - wide[metric][b]).to_numpy()
                    low, high = bootstrap_ci(diff, n_boot)
                    rows.append({"condition": condition, "mask": mask, "metric": metric, "A": a, "B": b,
                                 "mean_A_minus_B": _mean_or_nan(diff), "ci_low": low, "ci_high": high, "n_slices": int(np.isfinite(diff).sum())})
    return pd.DataFrame(rows)


SENSITIVITY_METRICS = ("RMSE_HU", "MAE_HU", "PSNR_dB", "SSIM_skimage_default", "SSIM_Wang2004")


def mask_sensitivity(per_slice: pd.DataFrame, n_boot: int, metrics: tuple[str, ...] = SENSITIVITY_METRICS) -> pd.DataFrame:
    """Inner-mask value minus principal-mask value, per slice, with a bootstrap CI over slices."""
    rows = []
    for (condition, family), group in per_slice.groupby(["condition", "family"], sort=False):
        main = group[group["mask"] == "main"].set_index("slice")
        inner = group[group["mask"] == "inner"].set_index("slice").reindex(main.index)
        for metric in metrics:
            diff = (inner[metric] - main[metric]).to_numpy()
            low, high = bootstrap_ci(diff, n_boot)
            rows.append({"condition": condition, "family": family, "metric": metric, "main_mean": _mean_or_nan(main[metric].to_numpy()),
                         "inner_mean": _mean_or_nan(inner[metric].to_numpy()), "inner_minus_main_mean": _mean_or_nan(diff),
                         "ci_low": low, "ci_high": high, "n_slices": int(np.isfinite(diff).sum())})
    return pd.DataFrame(rows)


def mask_ranking(per_slice: pd.DataFrame, metric: str = "RMSE_HU") -> pd.DataFrame:
    """Rank of the filter families (1 = lowest error) on each mask, and whether the ranking changes."""
    rows = []
    filtered = per_slice[per_slice.family != BASELINE]
    for condition, group in filtered.groupby("condition", sort=False):
        means = group.groupby(["family", "mask"])[metric].mean().unstack("mask")
        ranks = means.rank(method="min")
        for family in means.index:
            rows.append({"condition": condition, "family": family, f"{metric}_main": means.loc[family, "main"], f"{metric}_inner": means.loc[family, "inner"],
                         "rank_main": int(ranks.loc[family, "main"]), "rank_inner": int(ranks.loc[family, "inner"]),
                         "rank_change": int(ranks.loc[family, "inner"] - ranks.loc[family, "main"])})
    return pd.DataFrame(rows)


def ssim_sensitivity(per_slice: pd.DataFrame, n_boot: int) -> pd.DataFrame:
    """Earlier SSIM definition (all mask pixels) minus the primary one (windows fully inside), per slice."""
    rows = []
    for (condition, mask, family), group in per_slice.groupby(["condition", "mask", "family"], sort=False):
        for label in ("SSIM_skimage_default", "SSIM_Wang2004"):
            diff = (group[label + "_allpixels"] - group[label]).to_numpy()
            low, high = bootstrap_ci(diff, n_boot)
            rows.append({"condition": condition, "mask": mask, "family": family, "ssim": label, "primary_mean": _mean_or_nan(group[label].to_numpy()),
                         "allpixels_mean": _mean_or_nan(group[label + "_allpixels"].to_numpy()), "allpixels_minus_primary_mean": _mean_or_nan(diff),
                         "ci_low": low, "ci_high": high, "n_slices": int(np.isfinite(diff).sum())})
    return pd.DataFrame(rows)


# --- output ----------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_safe(value):
    """Copy of ``value`` in which NaN and infinities are ``None``: they are not valid JSON and a browser cannot parse them."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def write_outputs(tables: dict[str, pd.DataFrame], out_dir: Path, metadata: dict) -> dict[str, Path]:
    """Write every table as CSV (full precision) plus ``run_metadata.json`` with file hashes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, table in tables.items():
        path = out_dir / f"{name}.csv"
        table.to_csv(path, index=False, encoding="utf-8")
        paths[name] = path
    metadata = dict(metadata)
    metadata["files_sha256"] = {path.name: sha256_of(path) for path in paths.values()}
    (out_dir / "run_metadata.json").write_text(json.dumps(json_safe(metadata), indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    return paths


SOURCE_FILES = ("benchmark_v2.py", "filters.py", "evaluate_denoising.py", "src/dicom_volume.py",
                "requirements.txt", "requirements-api.txt")


SOURCE_HASH_RULE = "SHA-256 of the file bytes with CRLF replaced by LF (the form Git stores), so the value does not depend on the checkout's line endings"


def sha256_lf_normalised(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def source_file_hashes(root: Path, names: Iterable[str] = SOURCE_FILES) -> dict[str, str]:
    """Line-ending-independent SHA-256 of the source files that define a run, so a result can be tied to the exact code."""
    return {name: sha256_lf_normalised(root / name) for name in names if (root / name).is_file()}


def series_input_record(series_dir: Path) -> dict:
    """Identity of the input series: instance UID, file count and a SHA-256 manifest of every file.

    The manifest is the text ``<sha256>  <path relative to the series directory>`` per file, sorted by path
    and joined with LF; ``manifest_sha256`` hashes that text. No patient identifiers are recorded.
    """
    import pydicom
    from src.dicom_volume import discover_dicom_files

    root = Path(series_dir)
    instances = discover_dicom_files(root)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    hashes = {p.relative_to(root).as_posix(): sha256_of(p) for p in files}
    manifest = "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items()))
    header = pydicom.dcmread(instances[0], stop_before_pixels=True)
    return {"series_instance_uid": str(getattr(header, "SeriesInstanceUID", "")), "dicom_instances": len(instances),
            "files_in_directory": len(files), "manifest_format": "<sha256>  <relative path>\\n per file, sorted by path, LF",
            "manifest_sha256": hashlib.sha256(manifest.encode("utf-8")).hexdigest(), "files_sha256": hashes}


NOISE_KERNEL = np.array([[1.0, -2.0, 1.0], [-2.0, 4.0, -2.0], [1.0, -2.0, 1.0]])   # Immerkaer (1996); noise gain 6
SOFT_TISSUE_HU = (0.0, 100.0)
SOFT_TISSUE_EROSION_PX = 3


def estimate_noise_hu(hu: np.ndarray, region: np.ndarray, min_pixels: int = 1000) -> float:
    """White-noise-equivalent standard deviation (HU) of ``hu`` inside ``region``.

    The image is filtered with the Laplacian-like mask of Immerkaer (1996), whose response to white noise of
    standard deviation s has standard deviation 6 s, and the scale is taken from the median absolute response
    (1.4826 times the median is the robust standard deviation), so isolated structures barely matter. Real CT
    noise is correlated and the region still holds some anatomy, so this is a rough, white-noise-equivalent
    figure for the reference slice, not a measurement of its true noise power. ``nan`` if too few pixels qualify.
    """
    if hu.ndim != 2 or region.shape != hu.shape:
        raise ValueError("hu and region must be 2D arrays of the same shape.")
    response = ndimage.correlate(hu.astype(np.float64), NOISE_KERNEL, mode="nearest")
    valid = ndimage.binary_erosion(region, structure=np.ones((3, 3), dtype=bool))   # the whole 3x3 window lies inside
    if int(valid.sum()) < min_pixels:
        return float("nan")
    return float(1.4826 * np.median(np.abs(response[valid])) / 6.0)


def soft_tissue_region(hu: np.ndarray) -> np.ndarray:
    """Body pixels between 0 and 100 HU, away from the body edge, lungs and bone (eroded)."""
    tissue = body_mask(hu) & (hu >= SOFT_TISSUE_HU[0]) & (hu <= SOFT_TISSUE_HU[1])
    side = 2 * SOFT_TISSUE_EROSION_PX + 1
    return ndimage.binary_erosion(tissue, structure=np.ones((side, side), dtype=bool))


def reference_noise_context(volume: np.ndarray, slices: Iterable[int]) -> dict:
    """Rough noise level of the clinical reference slices, to put the synthetic levels in context."""
    rows = []
    for index in sorted(set(int(i) for i in slices)):
        hu = volume[index].astype(np.float64)
        region = soft_tissue_region(hu)
        estimate = estimate_noise_hu(hu, region)
        rows.append({"slice": index, "soft_tissue_pixels": int(region.sum()),
                     "white_noise_equivalent_sd_hu": estimate if math.isfinite(estimate) else None})   # None: too few soft-tissue pixels
    values = [r["white_noise_equivalent_sd_hu"] for r in rows if r["white_noise_equivalent_sd_hu"] is not None]
    return {
        "method": ("median-based Immerkaer (1996) estimate on soft tissue (0 to 100 HU, body interior, eroded by "
                   f"{SOFT_TISSUE_EROSION_PX} px) of the clean reference slices"),
        "interpretation": ("white-noise-equivalent, rough: real CT noise is correlated and the region contains anatomy; "
                           "the synthetic noise below is ADDED to this existing noise"),
        "per_slice": rows, "median_hu": float(np.median(values)) if values else None,
        "range_hu": [float(min(values)), float(max(values))] if values else None,
    }


def git_state(cwd: Path) -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return commit + ("+dirty" if dirty else "")


def package_versions() -> dict[str, str]:
    import cv2 as _cv2
    import numpy
    import pandas
    import pydicom
    import scipy
    import skimage

    versions = {"python": sys.version.split()[0], "numpy": numpy.__version__, "scipy": scipy.__version__,
                "scikit-image": skimage.__version__, "opencv": _cv2.__version__, "pandas": pandas.__version__,
                "pydicom": pydicom.__version__}
    try:                        # only the wavelet family needs it; the distribution's version, because pywt.__version__ lags behind
        from importlib.metadata import PackageNotFoundError, version
        versions["pywavelets"] = version("PyWavelets")
    except PackageNotFoundError:
        pass
    return versions


def added_denoisers_description() -> dict:
    """What the three added families are, which hyper-parameters are fixed and which one is tuned."""
    return {
        "status": "classical, non-learned; one tuned strength parameter per family, chosen on the tuning slices only",
        "Bilateral": {"implementation": "cv2.bilateralFilter (float32), reflected borders", "tuned": "sigma_color_hu (HU)",
                      "fixed": {"sigma_space_px": BILATERAL_SIGMA_SPACE_PX, "window_diameter_px": 2 * math.ceil(3 * BILATERAL_SIGMA_SPACE_PX) + 1},
                      "fixed_choice": "sigma_space fixed on sweeps over the tuning slices only; the best value differs between noise types"},
        "Non-local means": {"implementation": "skimage.restoration.denoise_nl_means, fast_mode=True, sigma=0 (noise level not supplied)",
                            "tuned": "h_hu (HU)", "fixed": {"patch_size": NLM_PATCH_SIZE, "patch_distance": NLM_PATCH_DISTANCE}},
        "Wavelet BayesShrink": {"implementation": "skimage.restoration.denoise_wavelet, soft thresholds, averaged over circular shifts (cycle spinning)",
                                "tuned": "sigma_hu (HU): the noise level ASSUMED by BayesShrink, used as a strength control, not a measurement",
                                "fixed": {"wavelet": WAVELET_NAME, "levels": WAVELET_LEVELS, "max_shifts": WAVELET_MAX_SHIFTS,
                                          "shifts_averaged": (WAVELET_MAX_SHIFTS + 1) ** 2}},
        "grids_hu": {"Bilateral": list(BILATERAL_SIGMA_COLOR_GRID_HU), "Non-local means": list(NLM_H_GRID_HU),
                     "Wavelet BayesShrink": list(WAVELET_SIGMA_GRID_HU)},
        "grid_design": "fixed from sweeps on the three tuning slices only; no test slice was scored before the run; the run was executed once",
        "not_included": {"BM3D": "assumes white Gaussian noise of known variance and needs an extra compiled dependency; not tested here",
                         "learned_denoisers": "see docs/methods_and_decisions.md"},
    }


def protocol_description(grid_version: str = "expanded") -> dict:
    """Machine-readable statement of the mask, the windows and what is (not) comparable."""
    lower, upper = window_bounds()
    extra = {"added_denoisers": added_denoisers_description()} if grid_version == "methods" else {}
    return {
        **extra,
        "evaluation_mask": {
            "rule": (f"largest connected region of the CLEAN reference slice above {BODY_THRESHOLD_HU:g} HU, holes filled; "
                     "computed once per slice from the reference only"),
            "independent_of": ["noise realisation", "noise level", "noise type", "filter", "filter parameters", "display window"],
            "applied_to": "HU metrics and windowed metrics, for the noisy image and every filtered output",
            "pixels_dropped_by_hu_value_or_window": 0,
        },
        "inner_mask": {
            "role": "SENSITIVITY analysis of the CT field-of-view boundary; the principal mask above stays the reference for conclusions",
            "rule": (f"principal mask minus every pixel within {INNER_MARGIN_PX} px (Euclidean distance) of the artificial padding "
                     f"(HU <= {PADDING_HU:g}); computed once per slice from the clean reference and reused for the noisy image and all outputs"),
            "margin_px": INNER_MARGIN_PX, "padding_threshold_hu": PADDING_HU, "minimum_fraction_of_principal_mask": MIN_INNER_FRACTION,
            "status": "the 10 px margin is an EXPERIMENTAL choice, not clinically validated",
            "parameters_are_tuned_on": "the principal mask only; every test output is scored on both masks",
        },
        "ssim": {
            "library": "skimage.metrics.structural_similarity, data_range=1.0, applied to the displayed (windowed) images",
            "primary_definition": ("mean of the SSIM map over the pixels whose whole window lies inside the mask (fully_inside=True); "
                                   "no pixel outside the mask can influence a primary score"),
            "windows": {"SSIM_skimage_default": "7x7 uniform window (pixel radius 3), use_sample_covariance=True",
                        "SSIM_Wang2004": "11x11 Gaussian window, sigma 1.5, truncated at 3.5 sigma (pixel radius 5), use_sample_covariance=False"},
            "rule_identical_for": "every filter, slice, noise condition and repeat",
            "sensitivity_definition": "columns *_allpixels: earlier definition, mean over all mask pixels (windows may read pixels outside the mask)",
            "evaluated_pixels": "columns ssim_pixels_default / ssim_pixels_wang in test_per_run.csv and test_per_slice.csv, and mask_summary.csv",
        },
        "display_window": {
            "center_hu": DISPLAY_WINDOW_CENTER, "width_hu": DISPLAY_WINDOW_WIDTH, "lower_hu": lower, "upper_hu": upper,
            "formula": "DICOM PS3.3 C.11.2.1.2 linear window, applied after filtering to the reference and to every output",
            "used_for": "PSNR, SSIM, RMSE_windowed, MAE_windowed only",
            "justification": ("conventional lung-window values, identical to the historical benchmark's display window; "
                              "chosen for continuity and not claimed to be clinically optimal"),
        },
        "normalisation_range_hu": {
            "low": NORMALISATION_RANGE_HU[0], "high": NORMALISATION_RANGE_HU[1],
            "role": "linear map used so filters can run on (0, 1) images; not a display window; never clips (an out-of-range value raises an error)",
        },
        "comparability_with_historical_results": (
            "NOT comparable: the historical benchmark added noise and filtered AFTER clipping to the -600/1500 window, "
            "on the whole image, with different noise levels, fixed filter settings and no tuning/test split. V2 adds "
            "noise in HU, filters without clipping, windows afterwards, and averages over a fixed body mask."),
    }


def grid_physical_equivalents(pixel_spacing_mm: float, image_size: int = 512) -> dict:
    """Physical meaning of the pixel-based filter parameters for a square image of ``image_size`` px.

    Kernel sizes and sigmas are in pixels. A cutoff ratio ``c`` puts the mask radius at
    ``c`` times the Nyquist frequency, i.e. ``c / (2 * spacing)`` cycles/mm; an FFT Gaussian
    low-pass with that cutoff equals a periodic spatial Gaussian of ``spacing / (pi * c)`` mm.
    """
    nyquist = 1.0 / (2.0 * pixel_spacing_mm)
    return {
        "pixel_spacing_mm": pixel_spacing_mm,
        "kernel_size_mm": {k: round(k * pixel_spacing_mm, 3) for k in KERNEL_GRID},          # 1 px = identity
        "gaussian_sigma_mm": {s: round(s * pixel_spacing_mm, 3) for s in GAUSSIAN_SIGMA_GRID},  # 0 = identity
        "fft_cutoff": {c: {"cycles_per_mm": round(c * nyquist, 4), "equivalent_gaussian_sigma_mm": round(pixel_spacing_mm / (math.pi * c), 3)}
                       for c in CUTOFF_GRID},
        "nyquist_cycles_per_mm": round(nyquist, 4),
        "note": ("parameters are defined in pixels / fractions of Nyquist; they are unaffected by the HU normalisation. "
                 "A cutoff above 1 lies beyond the Nyquist frequency along the axes: the ideal mask is the identity from sqrt(2), "
                 "Gaussian and Butterworth only approach it. The identity configurations are kernel 1, sigma 0 and cutoff null."),
    }


def dicom_conversion_facts(series_dir: Path) -> dict:
    """Header facts that define the DICOM-to-HU conversion (no patient identifiers)."""
    import pydicom
    from src.dicom_volume import discover_dicom_files

    header = pydicom.dcmread(discover_dicom_files(series_dir)[0], stop_before_pixels=True)
    keys = ("Modality", "RescaleSlope", "RescaleIntercept", "BitsStored", "PixelRepresentation", "PhotometricInterpretation",
            "WindowCenter", "WindowWidth", "ConvolutionKernel")
    return {"hu = stored * RescaleSlope + RescaleIntercept (pydicom apply_modality_lut)": True,
            **{key: str(getattr(header, key, "absent")) for key in keys},
            "note": "the WindowCenter/WindowWidth tags are NOT used by benchmark V2"}


def require_hounsfield_series(series_dir: Path) -> None:
    """Refuse a series whose stored values cannot be read as Hounsfield units.

    The benchmark defines noise, masks (-500 HU body threshold, -1500 HU padding) and the display
    window in HU. That is only meaningful for a CT series with an explicit modality rescale.
    """
    import pydicom
    from src.dicom_volume import discover_dicom_files

    header = pydicom.dcmread(discover_dicom_files(series_dir)[0], stop_before_pixels=True)
    modality = str(getattr(header, "Modality", "absent"))
    if modality != "CT":
        raise ValueError(f"Benchmark V2 needs a CT series (Hounsfield units); the DICOM Modality is {modality!r}.")
    for tag in ("RescaleSlope", "RescaleIntercept"):
        if not hasattr(header, tag):
            raise ValueError(f"The series has no {tag}, so its values cannot be interpreted as Hounsfield units.")
    slope = float(header.RescaleSlope)
    if not math.isfinite(slope) or slope <= 0 or not math.isfinite(float(header.RescaleIntercept)):
        raise ValueError("RescaleSlope must be positive and finite and RescaleIntercept finite.")


def ensure_outside_repository(out_dir: Path, repository_root: Path, allow: bool) -> None:
    out, root = out_dir.resolve(), repository_root.resolve()
    if not allow and (out == root or root in out.parents):
        raise SystemExit(f"Refusing to write inside the repository ({root}). Choose another --out or pass --allow-inside-repo.")


def main(argv: list[str] | None = None) -> None:
    from src.dicom_volume import load_dicom_volume

    parser = argparse.ArgumentParser(description="Run benchmark V2 (HU-defined noise, tuning/test split, bootstrap CIs).")
    parser.add_argument("--dicom-series", type=Path, required=True, help="Directory of ONE DICOM series (local data only).")
    parser.add_argument("--out", type=Path, required=True, help="Output directory, e.g. D:/biomed_runs/benchmark_v2_<date>.")
    parser.add_argument("--n-tune", type=int, default=3)
    parser.add_argument("--n-test", type=int, default=8)
    parser.add_argument("--min-gap", type=int, default=3)
    parser.add_argument("--tune-repeats", type=int, default=2)
    parser.add_argument("--test-repeats", type=int, default=5)
    parser.add_argument("--n-boot", type=int, default=10000)
    parser.add_argument("--grid-version", choices=GRID_VERSIONS, default="expanded",
                        help="Tuning grid: 'expanded' (default, down to the identity) or 'v1' (the first run's grid).")
    parser.add_argument("--allow-inside-repo", action="store_true")
    parser.add_argument("--plan-only", action="store_true", help="Print the slice selection and exit without computing anything.")
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parent.parent
    ensure_outside_repository(args.out, repo, args.allow_inside_repo)
    require_hounsfield_series(args.dicom_series)
    volume, spacing, _, _ = load_dicom_volume(args.dicom_series)
    eligible = eligible_slices(volume)
    tune, test = split_slices(eligible, args.n_tune, args.n_test, args.min_gap)
    print(f"series: {args.dicom_series.name} | volume {volume.shape} | spacing (x,y,z) mm {spacing}")
    print(f"eligible slices (lung fraction >= {MIN_LUNG_FRACTION}): {len(eligible)} [{eligible[0]}..{eligible[-1]}]")
    print(f"tuning slices: {tune} | test slices: {test}")
    if args.plan_only:
        return
    config = Config(tune, test, args.tune_repeats, args.test_repeats, n_boot=args.n_boot, grid_version=args.grid_version)
    tables = run_benchmark(volume, config, log=print)
    metadata = {
        "schema_version": SCHEMA_VERSION, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_state(repo), "benchmark": "V2", "series_directory_name": args.dicom_series.name,
        "voxel_spacing_xyz_mm": list(spacing), "volume_shape_zyx": list(volume.shape),
        "protocol": protocol_description(args.grid_version),
        "mask_pixel_counts_by_slice": tables["mask_summary"].drop(columns=["main_mask_sha256", "inner_mask_sha256"]).to_dict(orient="records"),
        "mask_sha256_by_slice": {int(r["slice"]): {"main": r["main_mask_sha256"], "inner": r["inner_mask_sha256"]}
                                 for r in tables["mask_summary"].to_dict(orient="records")},
        "filter_physical_equivalents": grid_physical_equivalents(float(spacing[0]), int(volume.shape[1])),
        "dicom_conversion": dicom_conversion_facts(args.dicom_series),
        "parameters": {
            "display_window_center": DISPLAY_WINDOW_CENTER, "display_window_width": DISPLAY_WINDOW_WIDTH,
            "normalisation_range_hu": list(NORMALISATION_RANGE_HU), "tuning_criterion": TUNING_CRITERION,
            "body_threshold_hu": BODY_THRESHOLD_HU, "lung_threshold_hu": LUNG_THRESHOLD_HU, "min_lung_fraction": MIN_LUNG_FRACTION,
            "inner_margin_px": INNER_MARGIN_PX, "padding_hu": PADDING_HU, "ssim_primary_fully_inside": True,
            "ssim_radius_default_px": SSIM_RADIUS_DEFAULT, "ssim_radius_wang_px": SSIM_RADIUS_WANG,
            "speckle_offset_hu": SPECKLE_OFFSET_HU, "correlation_sigma_px": CORRELATION_SIGMA_PX, "butterworth_order": BUTTERWORTH_ORDER,
            "eligible_slices": eligible, "tune_slices": tune, "test_slices": test, "min_gap": args.min_gap,
            "tune_repeats": args.tune_repeats, "test_repeats": args.test_repeats, "tune_base_seed": config.tune_base_seed,
            "test_base_seed": config.test_base_seed, "n_boot": args.n_boot, "bootstrap_seed": 12345,
            "conditions": [c.__dict__ for c in CONDITIONS], "grid_version": args.grid_version,
            "grid": parameter_grid(args.grid_version), "selection_criterion": TUNING_CRITERION,
        },
        "grid_bracketing_summary": tables["grid_bracketing"]["status"].value_counts().to_dict(),
        "grid_note": ("Selection uses RMSE_HU on the tuning slices only. 'identity' means no filtering scored best; 'interior' means the "
                      "minimum is bracketed by weaker and stronger neighbours; 'weakest_end'/'strongest_end' mean the minimum is NOT "
                      "bracketed. PSNR and SSIM on the tuning slices are recorded in tuning_grid.csv and compared in "
                      "tuning_criteria_comparison.csv but never select a parameter."),
        "packages": package_versions(),
        "source_files_sha256": source_file_hashes(Path(__file__).resolve().parent),
        "source_files_hash_rule": SOURCE_HASH_RULE,
        "input_series": series_input_record(args.dicom_series),
        "reference_noise_context": reference_noise_context(volume, [*tune, *test]),
        "limitations": ("Synthetic-noise experiment on one clinical series; the reference is a noisy clinical slice, not ground "
                        "truth; noise levels are scenarios; correlated noise is unvalidated; no clinical validation."),
    }
    paths = write_outputs(tables, args.out, metadata)
    print("written:", ", ".join(sorted(p.name for p in paths.values())), "+ run_metadata.json ->", args.out)


if __name__ == "__main__":
    main()
