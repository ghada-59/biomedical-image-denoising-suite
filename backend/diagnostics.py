"""Measurements that qualify the assumptions of the benchmarks. They are diagnostics, not benchmarks: nothing is written and no run is recorded.

``noise-texture``       How correlated is the REAL noise of a CT series, between neighbouring slices and inside a slice?
                        Benchmark 3D adds noise that is independent between slices, and the "correlated" scenario of Benchmark V2
                        smooths white noise with a 1 px Gaussian; this measures what the series itself shows.
``edge-band``           How much of the RMSE over the body mask comes from a 3-pixel band along its edge? Benchmark V2 tunes on that RMSE,
                        and a smoothing filter puts a large error on the few pixels of a sharp edge (here: fixed 3x3 and 5x5 mean and a Gaussian of
                        sigma 1 px, applied to white noise of 25 HU).
``bootstrap-coverage``  How often does the 95 % percentile-bootstrap interval that the benchmarks report, computed from 8 values
                        (8 test slices), contain the true mean? Run on simulated data whose mean is known.

    python diagnostics.py noise-texture --dicom-series "path/to/one_dicom_series"
    python diagnostics.py edge-band --dicom-series "path/to/one_dicom_series"
    python diagnostics.py bootstrap-coverage

Method of ``noise-texture``: every slice is high-pass filtered with the Immerkaer (1996) kernel, which removes smooth anatomy and keeps
mostly noise, inside homogeneous soft tissue (0 to 100 HU, away from edges). The Pearson correlation of the residual of slice k with
that of slice k + d is computed over the pixels both slices share. Anatomy that survives the filter contributes at every distance and
fades slowly; noise shared by neighbouring slices adds a step at d = 1. A volume of independent noise gives about 0 at every distance.
This is a rough, descriptive estimator of noise correlation, not a measurement of the noise power spectrum.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from scipy import ndimage

import benchmark_v2 as b2

MIN_PIXELS = 3000          # a slice, or a pair of slices, needs at least this many homogeneous soft-tissue pixels to be used


def highpass_residual(slice_hu: np.ndarray) -> np.ndarray:
    """Response of the Immerkaer (1996) kernel: zero for a plane, and 6 times the noise SD for white noise."""
    if slice_hu.ndim != 2:
        raise ValueError("slice_hu must be a 2D array.")
    return ndimage.correlate(slice_hu.astype(np.float64), b2.NOISE_KERNEL, mode="nearest")


def _regions_and_residuals(volume: np.ndarray) -> tuple[list[np.ndarray], list[np.ndarray]]:
    if volume.ndim != 3 or volume.shape[0] < 2:
        raise ValueError("volume must be a 3D array (slices, rows, columns) with at least 2 slices.")
    return [b2.soft_tissue_region(s.astype(np.float64)) for s in volume], [highpass_residual(s) for s in volume]


def cross_slice_residual_correlation(volume: np.ndarray, distances: Iterable[int] = (1, 2, 3, 5), min_pixels: int = MIN_PIXELS) -> dict[int, dict[str, float]]:
    """Mean, minimum and maximum over slice pairs of the correlation of the residuals of slices k and k + d, for each distance d."""
    distances = tuple(int(d) for d in distances)
    if not distances or min(distances) < 1:
        raise ValueError("distances must be positive integers.")
    regions, residuals = _regions_and_residuals(volume)
    usable = [k for k, region in enumerate(regions) if int(region.sum()) > min_pixels]
    result = {}
    for d in distances:
        values = []
        for k in usable:
            if k + d >= len(volume):
                continue
            shared = regions[k] & regions[k + d]
            if int(shared.sum()) < min_pixels:
                continue
            values.append(float(np.corrcoef(residuals[k][shared], residuals[k + d][shared])[0, 1]))
        result[d] = ({"mean": float(np.mean(values)), "min": float(np.min(values)), "max": float(np.max(values)), "pairs": len(values)} if values
                     else {"mean": math.nan, "min": math.nan, "max": math.nan, "pairs": 0})
    return result


def inplane_residual_autocorrelation(images: list[np.ndarray], regions: list[np.ndarray], shifts: Iterable[int] = (1, 2, 3, 4)) -> dict[int, float]:
    """Mean over images of the correlation between the high-pass residual and itself shifted by ``shift`` pixels along x, inside the region.

    For white noise the Immerkaer kernel itself makes the value at shift 1 strongly negative (about -2/3); smoother (more correlated) noise
    moves it towards 0 and above, so the profile over the shifts tells noise textures apart.
    """
    if len(images) != len(regions) or not images:
        raise ValueError("images and regions must be non-empty lists of the same length.")
    out = {}
    for shift in (int(s) for s in shifts):
        values = []
        for image, region in zip(images, regions, strict=True):
            residual = highpass_residual(image)
            shared = region & np.roll(region, shift, axis=1)
            values.append(float(np.corrcoef(residual[shared], np.roll(residual, shift, axis=1)[shared])[0, 1]))
        out[shift] = float(np.mean(values))
    return out


def noise_texture_report(volume: np.ndarray, slices: Iterable[int] = range(10, 90, 4), shifts: Iterable[int] = (1, 2, 3, 4), seed: int = 100,
                         construction_sigmas_px: Iterable[float] = (0.5, 0.7, b2.CORRELATION_SIGMA_PX, 1.5)) -> dict:
    """Cross-slice correlation of the real residual, and in-plane profile of the real residual next to simulated white and smoothed noise."""
    indices = [i for i in slices if 0 <= i < volume.shape[0]]
    images = [volume[i].astype(np.float64) for i in indices]
    regions = [b2.soft_tissue_region(image) for image in images]
    profiles = {"real series": inplane_residual_autocorrelation(images, regions, shifts)}
    shape = volume.shape[1:]
    simulated = [("white noise", "white", b2.CORRELATION_SIGMA_PX)]
    for sigma in construction_sigmas_px:
        shipped = " (as in Benchmark V2)" if sigma == b2.CORRELATION_SIGMA_PX else ""
        simulated.append((f"smoothed, sigma {sigma:g} px{shipped}", "correlated", sigma))
    for label, kind, sigma in simulated:
        noises = [b2.hu_noise(shape, 20.0, kind, seed + n, correlation_sigma_px=sigma) for n in range(len(images))]
        profiles[label] = inplane_residual_autocorrelation(noises, regions, shifts)
    return {"cross_slice": cross_slice_residual_correlation(volume), "in_plane": profiles}


# ---- error carried by the edge of the body mask ----------------------------------------------------------------------------------

BAND_WIDTH_PX = 3
BAND_SETTINGS: tuple[tuple[str, dict], ...] = (("Mean", {"kernel_size": 3}), ("Mean", {"kernel_size": 5}), ("Gaussian", {"kernel_size": 7, "sigma": 1.0}))


def edge_band_error(reference_hu: np.ndarray, output_hu: np.ndarray, width_px: int = BAND_WIDTH_PX) -> dict[str, float]:
    """Error of ``output_hu`` inside a band of ``width_px`` pixels (city-block distance) along the inner edge of the principal mask.

    Returns the share of the mask that the band covers, the RMSE in the band and in the whole mask (HU), and the share of the squared error
    of the whole mask that comes from the band. A sharp edge smoothed by any filter puts a large error on a few pixels, so the share of the
    squared error can be far larger than the share of the pixels.
    """
    if width_px < 1:
        raise ValueError("width_px must be at least 1.")
    if reference_hu.ndim != 2 or reference_hu.shape != output_hu.shape:
        raise ValueError("reference_hu and output_hu must be 2D arrays of the same shape.")
    main = b2.reference_masks(reference_hu)["main"]
    band = main & ~ndimage.binary_erosion(main, structure=ndimage.generate_binary_structure(2, 1), iterations=int(width_px))
    error = output_hu.astype(np.float64) - reference_hu.astype(np.float64)
    total = float(np.sum(error[main] ** 2))
    return {"band_pixel_share": float(band.sum() / main.sum()),
            "band_rmse_hu": float(np.sqrt(np.mean(error[band] ** 2))) if band.any() else math.nan,
            "mask_rmse_hu": float(np.sqrt(np.mean(error[main] ** 2))),
            "band_squared_error_share": float(np.sum(error[band] ** 2) / total) if total > 0 else math.nan}


def edge_band_report(volume: np.ndarray, slices: Iterable[int], noise_hu: float = 25.0, seed: int = 42, width_px: int = BAND_WIDTH_PX,
                     settings: Iterable[tuple[str, dict]] = BAND_SETTINGS) -> list[dict]:
    """For each fixed smoothing setting: min, median and max over ``slices`` of the quantities of ``edge_band_error`` after white noise of ``noise_hu``."""
    condition = b2.Condition("white_diagnostic", "White Gaussian noise of the diagnostic", "white", "main", sigma_hu=float(noise_hu))
    rows = []
    for family, params in settings:
        per_slice = []
        for index in slices:
            reference = volume[index].astype(np.float64)
            case = b2.make_case(reference, condition, b2.condition_seed(seed, int(index), 0, 1))
            per_slice.append(edge_band_error(reference, b2.filter_hu(case.noisy_hu, family, params), width_px))
        row = {"setting": f"{family} {params}", "slices": len(per_slice)}
        for key in ("band_pixel_share", "band_rmse_hu", "mask_rmse_hu", "band_squared_error_share"):
            values = [r[key] for r in per_slice]
            row[key] = (float(np.min(values)), float(np.median(values)), float(np.max(values)))
        rows.append(row)
    return rows


# ---- coverage of the bootstrap interval ------------------------------------------------------------------------------------------

Draw = Callable[[np.random.Generator, int], np.ndarray]
DISTRIBUTIONS: dict[str, tuple[Draw, float]] = {
    "normal": (lambda rng, n: rng.standard_normal(n), 0.0),
    "heavy-tailed (Student t, 3 df)": (lambda rng, n: rng.standard_t(3, n), 0.0),
    "two-level mixture (a few hard slices)": (lambda rng, n: np.where(rng.random(n) < 0.2, 3.0, 0.0) + 0.3 * rng.standard_normal(n), 0.6),
    "skewed (lognormal, sigma 1)": (lambda rng, n: rng.lognormal(0.0, 1.0, n), math.exp(0.5)),
}


def bootstrap_coverage(draw: Draw, true_mean: float, n: int = 8, reps: int = 4000, n_boot: int = 2000, seed: int = 2026) -> float:
    """Share of replications in which the project's 95 % percentile-bootstrap interval of the mean of ``n`` values contains ``true_mean``."""
    if n < 2 or reps < 1 or n_boot < 1:
        raise ValueError("n must be at least 2, reps and n_boot at least 1.")
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(reps):
        low, high = b2.bootstrap_ci(draw(rng, n), n_boot=n_boot, seed=int(rng.integers(1, 2**31 - 1)))
        hits += low <= true_mean <= high
    return hits / reps


# ---- command line --------------------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    texture = sub.add_parser("noise-texture", help="correlation of the real noise of a DICOM series (between slices and in plane)")
    texture.add_argument("--dicom-series", type=Path, required=True, help="folder with one CT series")
    band = sub.add_parser("edge-band", help="share of the body-mask error that comes from a band along the mask edge")
    band.add_argument("--dicom-series", type=Path, required=True, help="folder with one CT series")
    band.add_argument("--slices", type=int, nargs="+", default=[16, 25, 39, 48, 61, 70, 84, 93], help="zero-based slice indices (default: the 8 test slices of the recorded Benchmark V2)")
    band.add_argument("--noise-hu", type=float, default=25.0)
    coverage = sub.add_parser("bootstrap-coverage", help="coverage of the 95 %% bootstrap interval from 8 values, on simulated data")
    coverage.add_argument("--reps", type=int, default=4000)
    coverage.add_argument("--n-boot", type=int, default=2000)
    coverage.add_argument("--n", type=int, default=8)
    args = parser.parse_args(argv)

    if args.command == "noise-texture":
        from src.dicom_volume import load_dicom_volume
        volume, spacing, _origin, _direction = load_dicom_volume(args.dicom_series)
        report = noise_texture_report(volume)
        print(f"volume {volume.shape}, spacing (x, y, z) {tuple(round(float(s), 3) for s in spacing)} mm")
        print("correlation of the high-pass residual between slice k and slice k + d (soft tissue; mean [min, max] over slice pairs):")
        for d, v in report["cross_slice"].items():
            print(f"   d = {d}: {v['mean']:+.3f} [{v['min']:+.3f}, {v['max']:+.3f}]   {v['pairs']} pairs")
        print("in-plane autocorrelation of the residual at x-shifts 1, 2, 3, 4 pixels:")
        for label, profile in report["in_plane"].items():
            print(f"   {label:34s}", " ".join(f"{v:+.3f}" for v in profile.values()))
    elif args.command == "edge-band":
        from src.dicom_volume import load_dicom_volume
        volume, _spacing, _origin, _direction = load_dicom_volume(args.dicom_series)
        print(f"white noise of {args.noise_hu:g} HU, fixed smoothing, band of {BAND_WIDTH_PX} px along the inner edge of the principal mask; min / median / max over slices {args.slices}")
        for row in edge_band_report(volume, args.slices, args.noise_hu):
            share, rmse, whole, sq = row["band_pixel_share"], row["band_rmse_hu"], row["mask_rmse_hu"], row["band_squared_error_share"]
            print(f"   {row['setting']:46s} band = {100 * share[1]:.1f} % of the mask | RMSE_HU in the band {rmse[0]:.0f} / {rmse[1]:.0f} / {rmse[2]:.0f},"
                  f" in the mask {whole[0]:.0f} / {whole[1]:.0f} / {whole[2]:.0f} | share of the squared error from the band {100 * sq[0]:.0f} / {100 * sq[1]:.0f} / {100 * sq[2]:.0f} %")
    else:
        print(f"{args.n} values per interval, nominal 95 %, {args.reps} replications, {args.n_boot} resamples each")
        for name, (draw, mean) in DISTRIBUTIONS.items():
            print(f"   {name:42s} coverage {100 * bootstrap_coverage(draw, mean, args.n, args.reps, args.n_boot):5.1f} %")


if __name__ == "__main__":
    main()
