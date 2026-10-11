"""Descriptive 3D CT smoothing report and orthogonal comparison figure."""
from __future__ import annotations
import argparse
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
from src.dicom_volume import load_dicom_volume
from src.volume_denoising import gaussian_denoise_volume


def _save_slice_figure(volume, smoothed, output_path: Path, spacing_xyz_mm):
    z, y, x = (n // 2 for n in volume.shape)
    original = [volume[z, :, :], volume[:, y, :], volume[:, :, x]]
    filtered = [smoothed[z, :, :], smoothed[:, y, :], smoothed[:, :, x]]
    titles = ["Axial", "Coronal", "Sagittal"]
    # Use physical pixel aspect ratios so thick-slice CT is not stretched.
    sx, sy, sz = spacing_xyz_mm
    aspects = [sy / sx, sz / sx, sz / sy]
    fig, axes = plt.subplots(3, 3, figsize=(13, 12))
    for col, title in enumerate(titles):
        diff = np.abs(filtered[col] - original[col])
        axes[0, col].imshow(original[col], cmap="gray", aspect=aspects[col])
        axes[0, col].set_title(f"Original — {title}")
        axes[1, col].imshow(filtered[col], cmap="gray", aspect=aspects[col])
        axes[1, col].set_title("Gaussian-smoothed")
        axes[2, col].imshow(diff, cmap="magma", aspect=aspects[col], vmin=0, vmax=max(float(np.percentile(diff, 99)), 1e-6))
        axes[2, col].set_title("Absolute difference")
    for ax in axes.ravel():
        ax.axis("off")
    fig.suptitle("3D CT smoothing — descriptive comparison, not clinical validation")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Report physical-unit 3D CT smoothing.")
    parser.add_argument("series_dir", help="Path to one DICOM series directory.")
    parser.add_argument("--sigma-mm", "--sigma", dest="sigma_mm", type=float, default=1.0,
                        help="Gaussian sigma in millimetres.")
    parser.add_argument("--output", type=Path, default=Path("reports/3D/volume_denoising_report.txt"))
    parser.add_argument("--figure-output", type=Path, default=Path("reports/3D/volume_denoising_slices.png"))
    args = parser.parse_args()
    if not np.isfinite(args.sigma_mm) or args.sigma_mm <= 0:
        parser.error("--sigma-mm must be finite and greater than zero.")
    volume, spacing, origin, direction = load_dicom_volume(args.series_dir)
    smoothed = gaussian_denoise_volume(volume, sigma=args.sigma_mm, spacing_xyz_mm=spacing)
    delta = smoothed - volume.astype(np.float32)
    sigma_zyx = (args.sigma_mm / spacing[2], args.sigma_mm / spacing[1], args.sigma_mm / spacing[0])
    report = f"""3D CT smoothing analysis
Series: {args.series_dir}
Shape (z,y,x): {volume.shape}
Spacing (x,y,z) mm: {spacing}
Origin (patient x,y,z mm): {origin}
Direction matrix: {direction}
Gaussian sigma (mm): {args.sigma_mm:g}
Equivalent sigma (z,y,x voxels): {sigma_zyx}

Original mean/std/min/max: {volume.mean():.4f} / {volume.std():.4f} / {volume.min():.4f} / {volume.max():.4f}
Smoothed mean/std/min/max: {smoothed.mean():.4f} / {smoothed.std():.4f} / {smoothed.min():.4f} / {smoothed.max():.4f}
Mean absolute change: {np.mean(np.abs(delta)):.4f}
99th percentile absolute change: {np.percentile(np.abs(delta), 99):.4f}

Interpretation: this is a descriptive comparison, not a restoration accuracy metric.
There is no independent clean ground-truth volume, so clinical PSNR/SSIM
claims are not supported. Smoothing can blur small anatomical structures.
"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    _save_slice_figure(volume, smoothed, args.figure_output, spacing)
    print(report)
    print(f"Report saved to: {args.output}")
    print(f"Figure saved to: {args.figure_output}")


if __name__ == "__main__":
    main()
