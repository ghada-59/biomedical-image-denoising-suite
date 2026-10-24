"""Save and/or show the middle axial, coronal, and sagittal CT slices."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from src.dicom_volume import load_dicom_volume


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View three orthogonal CT slices."
    )
    parser.add_argument("series_dir", help="Path to a DICOM series directory.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional PNG path for saving the orthogonal-slice figure.",
    )
    args = parser.parse_args()

    volume, spacing, _origin, _direction = load_dicom_volume(args.series_dir)

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

    fig.suptitle("DICOM CT — Orthogonal middle slices")
    fig.tight_layout()

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.output, dpi=160, bbox_inches="tight")
        print(f"Figure saved to: {args.output}")

    plt.show()


if __name__ == "__main__":
    main()
