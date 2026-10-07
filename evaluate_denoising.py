"""Reproducible quantitative benchmark and visualization report for 2D denoising filters."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from filters import (
    FREQUENCY_FILTERS,
    NOISE_TYPES,
    add_noise,
    apply_frequency_lowpass,
    apply_spatial_filters,
    calculate_metrics,
    load_medical_image,
)


PROJECT_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = PROJECT_DIR / "samples"
REPORTS_DIR = PROJECT_DIR / "reports"
VISUALS_DIR = REPORTS_DIR / "2D"

REFERENCE_IMAGES = [
    SAMPLES_DIR / "brain_mri.png",
    SAMPLES_DIR / "cells_tissue.png",
]

SEED = 42
NOISE_AMOUNT = 0.02
NOISE_VARIANCE = 0.02
KERNEL_SIZE = 5
GAUSSIAN_SIGMA = 0.0
CUTOFF_RATIO = 0.10
BUTTERWORTH_ORDER = 2


def _add_noise(clean_image, noise_type: str):
    """Create the deterministic noisy image used by both evaluation and plots."""
    if noise_type == "Salt & Pepper":
        return add_noise(
            clean_image, noise_type, amount=NOISE_AMOUNT, seed=SEED
        )
    return add_noise(
        clean_image, noise_type, var=NOISE_VARIANCE, seed=SEED
    )


def _save_figure(fig, path: Path) -> None:
    """Save a publication-style figure and release its Matplotlib resources."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _save_spatial_visualization(clean_image, noisy_image, image_name: str, noise_type: str):
    """Save original/noisy/spatial-filter comparison."""
    mean_img, median_img, gaussian_img = apply_spatial_filters(
        noisy_image,
        kernel_size=KERNEL_SIZE,
        sigma=GAUSSIAN_SIGMA,
    )
    images = [
        ("Original", clean_image),
        ("Noisy", noisy_image),
        ("Mean", mean_img),
        ("Median", median_img),
        ("Gaussian", gaussian_img),
    ]

    fig, axes = plt.subplots(1, len(images), figsize=(16, 3.6))
    for axis, (title, image) in zip(axes, images):
        axis.imshow(image, cmap="gray", vmin=0.0, vmax=1.0)
        axis.set_title(title)
        axis.axis("off")

    fig.suptitle(f"{image_name} — Spatial filtering — {noise_type}")
    fig.tight_layout()
    filename = f"{Path(image_name).stem}_{noise_type.lower().replace(' ', '_').replace('&', 'and')}_spatial.png"
    _save_figure(fig, VISUALS_DIR / filename)


def _save_frequency_visualization(clean_image, noisy_image, image_name: str, noise_type: str):
    """Save original/noisy/frequency-filter comparison."""
    filtered_images = []
    for filter_name in FREQUENCY_FILTERS:
        filtered_image, _, _ = apply_frequency_lowpass(
            noisy_image,
            cutoff_ratio=CUTOFF_RATIO,
            filter_type=filter_name,
            order=BUTTERWORTH_ORDER,
        )
        filtered_images.append((filter_name.capitalize(), filtered_image))

    images = [("Original", clean_image), ("Noisy", noisy_image), *filtered_images]
    fig, axes = plt.subplots(1, len(images), figsize=(18, 3.6))
    for axis, (title, image) in zip(axes, images):
        axis.imshow(image, cmap="gray", vmin=0.0, vmax=1.0)
        axis.set_title(title)
        axis.axis("off")

    fig.suptitle(f"{image_name} — Frequency-domain filtering — {noise_type}")
    fig.tight_layout()
    filename = f"{Path(image_name).stem}_{noise_type.lower().replace(' ', '_').replace('&', 'and')}_frequency.png"
    _save_figure(fig, VISUALS_DIR / filename)


def evaluate_spatial_filters(clean_image, image_name: str, noise_type: str) -> list[dict]:
    """Evaluate noisy baseline and spatial filters for one noise type."""
    noisy_image = _add_noise(clean_image, noise_type)
    mean_img, median_img, gaussian_img = apply_spatial_filters(
        noisy_image, kernel_size=KERNEL_SIZE, sigma=GAUSSIAN_SIGMA
    )

    results = []
    images = [
        ("Noisy (Unfiltered)", noisy_image),
        ("Mean", mean_img),
        ("Median", median_img),
        ("Gaussian", gaussian_img),
    ]
    for filter_name, processed_image in images:
        psnr_value, ssim_value = calculate_metrics(clean_image, processed_image)
        results.append(
            {
                "Image": image_name,
                "Noise": noise_type,
                "Domain": "Spatial",
                "Filter": filter_name,
                "PSNR (dB)": psnr_value,
                "SSIM": ssim_value,
            }
        )
    return results


def evaluate_frequency_filters(clean_image, image_name: str, noise_type: str) -> list[dict]:
    """Evaluate noisy baseline and frequency-domain filters."""
    noisy_image = _add_noise(clean_image, noise_type)
    results = []

    baseline_psnr, baseline_ssim = calculate_metrics(clean_image, noisy_image)
    results.append(
        {
            "Image": image_name,
            "Noise": noise_type,
            "Domain": "Frequency",
            "Filter": "Noisy (Unfiltered)",
            "PSNR (dB)": baseline_psnr,
            "SSIM": baseline_ssim,
        }
    )

    for filter_name in FREQUENCY_FILTERS:
        filtered_image, _, _ = apply_frequency_lowpass(
            noisy_image,
            cutoff_ratio=CUTOFF_RATIO,
            filter_type=filter_name,
            order=BUTTERWORTH_ORDER,
        )
        psnr_value, ssim_value = calculate_metrics(clean_image, filtered_image)
        results.append(
            {
                "Image": image_name,
                "Noise": noise_type,
                "Domain": "Frequency",
                "Filter": filter_name.capitalize(),
                "PSNR (dB)": psnr_value,
                "SSIM": ssim_value,
            }
        )
    return results


def main() -> None:
    """Run the benchmark and generate all reproducible 2D visual reports."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    VISUALS_DIR.mkdir(parents=True, exist_ok=True)
    all_results: list[dict] = []

    for image_path in REFERENCE_IMAGES:
        if not image_path.exists():
            print(f"Warning: missing reference image: {image_path}")
            continue

        print(f"\nEvaluating: {image_path.name}")
        clean_image = load_medical_image(image_path)

        for noise_type in NOISE_TYPES:
            print(f"  Noise: {noise_type}")
            noisy_image = _add_noise(clean_image, noise_type)
            _save_spatial_visualization(
                clean_image, noisy_image, image_path.name, noise_type
            )
            _save_frequency_visualization(
                clean_image, noisy_image, image_path.name, noise_type
            )
            all_results.extend(
                evaluate_spatial_filters(clean_image, image_path.name, noise_type)
            )
            all_results.extend(
                evaluate_frequency_filters(clean_image, image_path.name, noise_type)
            )

    if not all_results:
        raise RuntimeError("No reference images were available for evaluation.")

    results_df = pd.DataFrame(all_results)
    baseline = (
        results_df[results_df["Filter"] == "Noisy (Unfiltered)"]
        [["Image", "Noise", "PSNR (dB)", "SSIM"]]
        .drop_duplicates(["Image", "Noise"])
        .rename(
            columns={
                "PSNR (dB)": "Baseline PSNR (dB)",
                "SSIM": "Baseline SSIM",
            }
        )
    )
    results_df = results_df.merge(baseline, on=["Image", "Noise"], how="left")
    results_df["PSNR Gain (dB)"] = (
        results_df["PSNR (dB)"] - results_df["Baseline PSNR (dB)"]
    )
    results_df["SSIM Gain"] = results_df["SSIM"] - results_df["Baseline SSIM"]

    for column in ("PSNR (dB)", "Baseline PSNR (dB)", "PSNR Gain (dB)"):
        results_df[column] = results_df[column].round(2)
    for column in ("SSIM", "Baseline SSIM", "SSIM Gain"):
        results_df[column] = results_df[column].round(4)

    csv_path = REPORTS_DIR / "denoising_benchmark.csv"
    results_df.to_csv(csv_path, index=False, encoding="utf-8")

    print("\nBenchmark completed successfully.")
    print(f"Results saved to: {csv_path}")
    print(f"Visualizations saved to: {VISUALS_DIR}")
    print(f"Number of evaluated cases: {len(results_df)}")
    print("\nResults:")
    print(results_df.to_string(index=False))


if __name__ == "__main__":
    main()
