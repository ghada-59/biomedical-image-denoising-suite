"""Compare one CT slice before and after 3D Gaussian smoothing."""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt

from src.dicom_volume import load_dicom_volume
from src.volume_denoising import gaussian_denoise_volume


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare a CT slice before and after denoising."
    )
    parser.add_argument("series_dir", help="Path to a DICOM series directory.")
    parser.add_argument("--sigma", type=float, default=1.0)
    parser.add_argument("--slice", type=int, default=None, dest="slice_index")
    args = parser.parse_args()

    volume, _, _ = load_dicom_volume(args.series_dir)
    denoised = gaussian_denoise_volume(volume, sigma=args.sigma)

    index = (
        volume.shape[0] // 2
        if args.slice_index is None
        else args.slice_index
    )
    if not 0 <= index < volume.shape[0]:
        raise ValueError(f"slice index must be in [0, {volume.shape[0] - 1}]")

    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    axes[0].imshow(volume[index], cmap="gray")
    axes[0].set_title("Original")
    axes[1].imshow(denoised[index], cmap="gray")
    axes[1].set_title(f"Gaussian, sigma={args.sigma:g}")

    for axis in axes:
        axis.axis("off")

    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
