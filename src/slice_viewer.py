"""Show the middle axial, coronal, and sagittal CT slices."""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt

from src.dicom_volume import load_dicom_volume


def main() -> None:
    parser = argparse.ArgumentParser(description="View three orthogonal CT slices.")
    parser.add_argument("series_dir", help="Path to a DICOM series directory.")
    args = parser.parse_args()

    volume, spacing, _ = load_dicom_volume(args.series_dir)

    axial = volume[volume.shape[0] // 2]
    coronal = volume[:, volume.shape[1] // 2, :]
    sagittal = volume[:, :, volume.shape[2] // 2]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    axes[0].imshow(axial, cmap="gray", aspect=spacing[1] / spacing[0])
    axes[0].set_title("Axial")
    axes[1].imshow(coronal, cmap="gray", aspect=spacing[2] / spacing[0])
    axes[1].set_title("Coronal")
    axes[2].imshow(sagittal, cmap="gray", aspect=spacing[2] / spacing[1])
    axes[2].set_title("Sagittal")

    for axis in axes:
        axis.axis("off")

    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
