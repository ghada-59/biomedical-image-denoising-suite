"""Reproducible denoising benchmark on slices from a local DICOM CT series.

A clinical CT slice is used as a reference only for a controlled experiment:
synthetic noise is added to that slice, and restored outputs are compared
with the same pre-noise slice. This is not a clean-ground-truth clinical
denoising study.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from filters import (
    FREQUENCY_FILTERS,
    add_noise,
    apply_frequency_lowpass,
    apply_spatial_filters,
    calculate_metrics,
)
from src.dicom_volume import load_dicom_volume


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DICOM_ROOT = PROJECT_DIR / "data" / "tcia" / "LIDC-IDRI-0709"
REPORTS_DIR = PROJECT_DIR / "reports"
VISUALS_DIR = REPORTS_DIR / "2D"

SEED = 42
DEFAULT_NOISE_AMOUNT = 0.02
DEFAULT_NOISE_VARIANCE = 0.02
KERNEL_SIZE = 5
GAUSSIAN_SIGMA = 0.0
CUTOFF_RATIO = 0.10
BUTTERWORTH_ORDER = 2
DEFAULT_WINDOW_CENTER = -600.0
DEFAULT_WINDOW_WIDTH = 1500.0

# Speckle noise is simulated mathematically here; it is not evidence that
# speckle noise is specific to CT or that this scan is an ultrasound image.
NOISE_TYPES = ("Gaussian", "Salt & Pepper", "Speckle (synthetic)")
NOISE_SEED_OFFSETS = {"Gaussian": 101, "Salt & Pepper": 211, "Speckle (synthetic)": 307}


def window_ct_slice(
    image_hu: np.ndarray,
    window_center: float = DEFAULT_WINDOW_CENTER,
    window_width: float = DEFAULT_WINDOW_WIDTH,
) -> np.ndarray:
    """Apply a fixed CT window and normalize the displayed slice to [0, 1]."""
    if not isinstance(image_hu, np.ndarray) or image_hu.ndim != 2:
        raise ValueError("image_hu must be a 2D NumPy array.")
    if image_hu.size == 0 or not np.isfinite(image_hu).all():
        raise ValueError("image_hu must be non-empty and finite.")
    if not np.isfinite(window_center):
        raise ValueError("window_center must be finite.")
    if not np.isfinite(window_width) or window_width <= 0:
        raise ValueError("window_width must be finite and greater than 0.")

    if window_width < 1.0:
        raise ValueError("window_width must be at least 1 for DICOM linear windowing.")
    image = image_hu.astype(np.float64)
    if window_width == 1.0:
        return (image > window_center - 0.5).astype(np.float64)
    lower = window_center - 0.5 - (window_width - 1.0) / 2.0
    upper = window_center - 0.5 + (window_width - 1.0) / 2.0
    scaled = (image - (window_center - 0.5)) / (window_width - 1.0) + 0.5
    return np.clip(np.where(image <= lower, 0.0, np.where(image > upper, 1.0, scaled)), 0.0, 1.0)


def select_slice_indices(
    total_slices: int,
    requested_indices: list[int] | None = None,
) -> list[int]:
    """Select five representative slice indices, or validate explicit indices."""
    if isinstance(total_slices, bool) or total_slices < 1:
        raise ValueError("total_slices must be a positive integer.")

    if requested_indices is not None:
        if not requested_indices:
            raise ValueError("At least one slice index must be provided.")
        if any(isinstance(index, bool) or not isinstance(index, int) for index in requested_indices):
            raise ValueError("Slice indices must be integers.")
        if any(index < 0 or index >= total_slices for index in requested_indices):
            raise ValueError(
                f"Slice indices must be between 0 and {total_slices - 1}."
            )
        if len(set(requested_indices)) != len(requested_indices):
            raise ValueError("Slice indices must not contain duplicates.")
        return sorted(requested_indices)

    count = min(5, total_slices)
    positions = np.linspace(
        0.15 * (total_slices - 1),
        0.85 * (total_slices - 1),
        num=count,
    )
    return sorted(set(int(round(position)) for position in positions))


def _find_local_dicom_series() -> Path | None:
    """Auto-detect a single DICOM-containing folder in the default data root."""
    if not DEFAULT_DICOM_ROOT.is_dir():
        return None

    candidates = sorted(
        {path.parent for path in DEFAULT_DICOM_ROOT.rglob("*.dcm") if path.is_file()}
    )
    if len(candidates) == 1:
        return candidates[0]
    return None


def _slug(value: str) -> str:
    """Create a filesystem-friendly token."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def derive_run_seed(base_seed: int, slice_index: int, noise_type: str, repeat_index: int) -> int:
    """Derive a stable, distinct seed for a slice/noise/repeat combination."""
    if noise_type not in NOISE_SEED_OFFSETS:
        raise ValueError(f"Unknown noise type: {noise_type!r}")
    if base_seed < 0 or slice_index < 0 or repeat_index < 0:
        raise ValueError("Seed, slice index, and repeat index must be non-negative.")
    return int((base_seed + slice_index * 100003 + repeat_index * 1009
                + NOISE_SEED_OFFSETS[noise_type]) % (2**32 - 1))


def _add_noise(
    clean_image: np.ndarray,
    noise_type: str,
    noise_variance: float,
    salt_pepper_amount: float,
    seed: int,
) -> tuple[np.ndarray, str]:
    """Return reproducible synthetic noise and describe its parameters."""
    if noise_type == "Salt & Pepper":
        return (
            add_noise(
                clean_image,
                "Salt & Pepper",
                amount=salt_pepper_amount,
                seed=seed,
            ),
            f"amount={salt_pepper_amount:g}",
        )

    implementation_name = FILTER_NOISE_TYPE.get(noise_type, noise_type)
    return (
        add_noise(
            clean_image,
            implementation_name,
            var=noise_variance,
            seed=seed,
        ),
        f"variance={noise_variance:g}",
    )


def _save_figure(fig, path: Path) -> None:
    """Save a figure and close it to release memory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _save_spatial_visualization(
    clean_image: np.ndarray,
    noisy_image: np.ndarray,
    slice_label: str,
    noise_type: str,
) -> None:
    """Save original, noisy, and spatial-filter outputs side by side."""
    mean_img, median_img, gaussian_img = apply_spatial_filters(
        noisy_image,
        kernel_size=KERNEL_SIZE,
        sigma=GAUSSIAN_SIGMA,
    )
    images = [
        ("Original reference", clean_image),
        ("Synthetic noise", noisy_image),
        ("Mean filter", mean_img),
        ("Median filter", median_img),
        ("Gaussian filter", gaussian_img),
    ]

    fig, axes = plt.subplots(1, len(images), figsize=(16, 3.8))
    for axis, (title, image) in zip(axes, images):
        axis.imshow(image, cmap="gray", vmin=0.0, vmax=1.0)
        axis.set_title(title)
        axis.axis("off")

    fig.suptitle(f"{slice_label} — Spatial filtering — {noise_type}")
    fig.tight_layout()
    _save_figure(
        fig,
        VISUALS_DIR / f"{slice_label}_{_slug(noise_type)}_spatial.png",
    )


def _save_frequency_visualization(
    clean_image: np.ndarray,
    noisy_image: np.ndarray,
    slice_label: str,
    noise_type: str,
) -> None:
    """Save original, noisy, and frequency-domain filter outputs side by side."""
    images = [
        ("Original reference", clean_image),
        ("Synthetic noise", noisy_image),
    ]
    for filter_name in FREQUENCY_FILTERS:
        filtered, _, _ = apply_frequency_lowpass(
            noisy_image,
            cutoff_ratio=CUTOFF_RATIO,
            filter_type=filter_name,
            order=BUTTERWORTH_ORDER,
        )
        images.append((filter_name.capitalize(), filtered))

    fig, axes = plt.subplots(1, len(images), figsize=(18, 3.8))
    for axis, (title, image) in zip(axes, images):
        axis.imshow(image, cmap="gray", vmin=0.0, vmax=1.0)
        axis.set_title(title)
        axis.axis("off")

    fig.suptitle(f"{slice_label} — Frequency-domain filtering — {noise_type}")
    fig.tight_layout()
    _save_figure(
        fig,
        VISUALS_DIR / f"{slice_label}_{_slug(noise_type)}_frequency.png",
    )


def _evaluate_one_slice(
    clean_image: np.ndarray,
    series_name: str,
    slice_index: int,
    noise_type: str,
    noise_variance: float,
    salt_pepper_amount: float,
    repeat_index: int,
    seed: int,
    save_visuals: bool,
) -> list[dict]:
    """Evaluate spatial and frequency filters for one CT slice/noise/repeat."""
    noisy_image, noise_parameter = _add_noise(
        clean_image, noise_type, noise_variance, salt_pepper_amount, seed
    )
    slice_label = f"{_slug(series_name)}_slice_{slice_index:03d}"
    if save_visuals:
        _save_spatial_visualization(clean_image, noisy_image, slice_label, noise_type)
        _save_frequency_visualization(clean_image, noisy_image, slice_label, noise_type)

    rows: list[dict] = []
    spatial_filtered = apply_spatial_filters(
        noisy_image,
        kernel_size=KERNEL_SIZE,
        sigma=GAUSSIAN_SIGMA,
    )
    spatial_outputs = [
        ("Noisy (Unfiltered)", noisy_image),
        *list(zip(("Mean", "Median", "Gaussian"), spatial_filtered)),
    ]
    for filter_name, processed in spatial_outputs:
        psnr_value, ssim_value = calculate_metrics(clean_image, processed)
        rows.append(
            {
                "Series": series_name,
                "Slice Index": slice_index,
                "Repeat": repeat_index + 1,
                "Seed": seed,
                "Noise": noise_type,
                "Noise Parameter": noise_parameter,
                "Domain": "Spatial",
                "Filter": filter_name,
                "PSNR (dB)": psnr_value,
                "SSIM": ssim_value,
            }
        )

    frequency_outputs = [("Noisy (Unfiltered)", noisy_image)]
    for filter_name in FREQUENCY_FILTERS:
        processed, _, _ = apply_frequency_lowpass(
            noisy_image,
            cutoff_ratio=CUTOFF_RATIO,
            filter_type=filter_name,
            order=BUTTERWORTH_ORDER,
        )
        frequency_outputs.append((filter_name.capitalize(), processed))

    for filter_name, processed in frequency_outputs:
        psnr_value, ssim_value = calculate_metrics(clean_image, processed)
        rows.append(
            {
                "Series": series_name,
                "Slice Index": slice_index,
                "Noise": noise_type,
                "Noise Parameter": noise_parameter,
                "Domain": "Frequency",
                "Filter": filter_name,
                "PSNR (dB)": psnr_value,
                "SSIM": ssim_value,
            }
        )
    return rows


def main() -> None:
    """Benchmark classical filters on representative slices from a DICOM CT series."""
    parser = argparse.ArgumentParser(
        description=(
            "Run a reproducible 2D filter benchmark on axial slices from a DICOM "
            "CT series. The source slice is the reference for controlled "
            "synthetic-noise experiments, not a clean clinical ground truth."
        )
    )
    parser.add_argument(
        "--dicom-series",
        type=Path,
        default=None,
        help=(
            "Path to one DICOM series directory. Auto-detected from "
            "data/tcia/LIDC-IDRI-0709 when unique."
        ),
    )
    parser.add_argument(
        "--slice-indices",
        type=int,
        nargs="+",
        default=None,
        help=(
            "Optional zero-based axial slice indices. Defaults to up to five "
            "spread-out slices."
        ),
    )
    parser.add_argument("--repeats", type=int, default=3,
                        help="Independent synthetic-noise realizations per slice and noise type.")
    parser.add_argument("--seed", type=int, default=SEED,
                        help="Base seed used to derive reproducible independent noise realizations.")
    parser.add_argument("--window-center", type=float, default=DEFAULT_WINDOW_CENTER)
    parser.add_argument("--window-width", type=float, default=DEFAULT_WINDOW_WIDTH)
    parser.add_argument("--noise-variance", type=float, default=DEFAULT_NOISE_VARIANCE)
    parser.add_argument(
        "--salt-pepper-amount",
        type=float,
        default=DEFAULT_NOISE_AMOUNT,
    )
    args = parser.parse_args()

    series_dir = args.dicom_series or _find_local_dicom_series()
    if series_dir is None:
        parser.error(
            "Could not auto-detect a single local DICOM series. Provide "
            "--dicom-series PATH_TO_ONE_DICOM_SERIES. The PNG images under "
            "samples/ are application demos, not the primary CT benchmark."
        )
    if not series_dir.is_dir():
        parser.error(f"DICOM series directory does not exist: {series_dir}")
    if args.repeats < 1:
        parser.error("--repeats must be at least 1.")
    if args.seed < 0:
        parser.error("--seed must be non-negative.")
    if not np.isfinite(args.noise_variance) or args.noise_variance < 0:
        parser.error("--noise-variance must be finite and non-negative.")
    if (
        not np.isfinite(args.salt_pepper_amount)
        or not 0.0 <= args.salt_pepper_amount <= 1.0
    ):
        parser.error("--salt-pepper-amount must be within [0, 1].")

    print(f"Loading DICOM CT series: {series_dir}")
    volume, spacing, _origin, _direction = load_dicom_volume(series_dir)
    indices = select_slice_indices(volume.shape[0], args.slice_indices)
    print(f"Volume shape (z, y, x): {volume.shape}")
    print(f"Voxel spacing (x, y, z) mm: {spacing}")
    print(f"Selected zero-based axial slice indices: {indices}")
    print(
        "CT display window: "
        f"center={args.window_center:g} HU, width={args.window_width:g} HU"
    )
    print(f"Independent synthetic-noise repetitions per slice/type: {args.repeats}")
    print(f"Base random seed: {args.seed}")
    print("Reference note: source slice before synthetic degradation; not clinical ground truth.")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    VISUALS_DIR.mkdir(parents=True, exist_ok=True)

    all_results: list[dict] = []
    for index in indices:
        clean_image = window_ct_slice(
            volume[index],
            window_center=args.window_center,
            window_width=args.window_width,
        )
        for noise_type in NOISE_TYPES:
            for repeat_index in range(args.repeats):
                run_seed = derive_run_seed(args.seed, index, noise_type, repeat_index)
                print(f"Slice {index} — {noise_type} — repeat {repeat_index + 1}/{args.repeats} (seed={run_seed})")
                all_results.extend(
                    _evaluate_one_slice(
                        clean_image=clean_image,
                        series_name=series_dir.name,
                        slice_index=index,
                        noise_type=noise_type,
                        noise_variance=args.noise_variance,
                        salt_pepper_amount=args.salt_pepper_amount,
                        repeat_index=repeat_index,
                        seed=run_seed,
                        save_visuals=(repeat_index == 0),
                    )
                )

    results_df = pd.DataFrame(all_results)
    baseline = (
        results_df[results_df["Filter"] == "Noisy (Unfiltered)"]
        [["Series", "Slice Index", "Repeat", "Noise", "PSNR (dB)", "SSIM"]]
        .drop_duplicates(["Series", "Slice Index", "Repeat", "Noise"])
        .rename(
            columns={
                "PSNR (dB)": "Baseline PSNR (dB)",
                "SSIM": "Baseline SSIM",
            }
        )
    )
    results_df = results_df.merge(
        baseline,
        on=["Series", "Slice Index", "Repeat", "Noise"],
        how="left",
    )
    results_df["PSNR Gain (dB)"] = (
        results_df["PSNR (dB)"] - results_df["Baseline PSNR (dB)"]
    )
    results_df["SSIM Gain"] = results_df["SSIM"] - results_df["Baseline SSIM"]

    detail_path = REPORTS_DIR / "denoising_benchmark.csv"
    display_results_df = results_df.copy()
    for column in ("PSNR (dB)", "Baseline PSNR (dB)", "PSNR Gain (dB)"):
        display_results_df[column] = display_results_df[column].round(3)
    for column in ("SSIM", "Baseline SSIM", "SSIM Gain"):
        display_results_df[column] = display_results_df[column].round(4)
    display_results_df.to_csv(detail_path, index=False, encoding="utf-8")

    # Aggregate from full-precision values; only round the displayed summary below.
    summary = (
        results_df.groupby(
            ["Noise", "Noise Parameter", "Domain", "Filter"],
            as_index=False,
        )
        .agg(
            Slices_Evaluated=("Slice Index", "nunique"),
            Runs_Evaluated=("Repeat", "size"),
            Mean_PSNR_dB=("PSNR (dB)", "mean"),
            Std_PSNR_dB=("PSNR (dB)", "std"),
            Mean_SSIM=("SSIM", "mean"),
            Std_SSIM=("SSIM", "std"),
            Mean_PSNR_Gain_dB=("PSNR Gain (dB)", "mean"),
            Mean_SSIM_Gain=("SSIM Gain", "mean"),
        )
    )
    summary["Mean_PSNR_dB"] = summary["Mean_PSNR_dB"].round(3)
    summary["Std_PSNR_dB"] = summary["Std_PSNR_dB"].fillna(0).round(3)
    summary["Mean_SSIM"] = summary["Mean_SSIM"].round(4)
    summary["Std_SSIM"] = summary["Std_SSIM"].fillna(0).round(4)
    summary["Mean_PSNR_Gain_dB"] = summary["Mean_PSNR_Gain_dB"].round(3)
    summary["Mean_SSIM_Gain"] = summary["Mean_SSIM_Gain"].round(4)

    summary_path = REPORTS_DIR / "denoising_summary.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8")

    print("\nDICOM CT benchmark completed.")
    print(f"Detailed results: {detail_path}")
    print(f"Mean results by filter/noise: {summary_path}")
    print(f"2D comparison figures: {VISUALS_DIR}")
    print(f"Rows in detailed benchmark: {len(results_df)}")
    print(f"Independent repetitions per slice/noise type: {args.repeats}")
    print(f"Noise labels: {', '.join(NOISE_TYPES)}")
    print("\nMean results:")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
