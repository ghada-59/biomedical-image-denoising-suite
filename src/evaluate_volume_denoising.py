"""Summarize how 3D Gaussian smoothing changes a CT volume.

This script does not claim objective denoising accuracy because no clean
ground-truth CT volume is available. The report describes intensity and
difference statistics instead.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from src.dicom_volume import load_dicom_volume
from src.volume_denoising import gaussian_denoise_volume


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report descriptive statistics for 3D CT smoothing."
    )
    parser.add_argument("series_dir", help="Path to a DICOM series directory.")
    parser.add_argument("--sigma", type=float, default=1.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/volume_denoising_report.txt"),
    )
    args = parser.parse_args()

    volume, spacing, _ = load_dicom_volume(args.series_dir)
    denoised = gaussian_denoise_volume(volume, sigma=args.sigma)
    difference = denoised - volume.astype(np.float32)

    report = f"""3D CT smoothing analysis

Series directory: {args.series_dir}
Volume shape: {volume.shape}
Voxel spacing (mm): {spacing[0]:.3f} x {spacing[1]:.3f} x {spacing[2]:.3f}

Method: 3D Gaussian smoothing
Sigma: {args.sigma:g}

Original volume
Mean: {float(volume.mean()):.4f}
Std: {float(volume.std()):.4f}
Min: {float(volume.min()):.4f}
Max: {float(volume.max()):.4f}

Smoothed volume
Mean: {float(denoised.mean()):.4f}
Std: {float(denoised.std()):.4f}
Min: {float(denoised.min()):.4f}
Max: {float(denoised.max()):.4f}

Change after smoothing
Mean absolute difference: {float(np.mean(np.abs(difference))):.4f}
Difference std: {float(np.std(difference)):.4f}

Interpretation
This is a descriptive analysis, not a denoising accuracy score.
A clean reference volume would be required for PSNR/SSIM-based 3D
restoration evaluation.
"""

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report saved to: {args.output}")


if __name__ == "__main__":
    main()
