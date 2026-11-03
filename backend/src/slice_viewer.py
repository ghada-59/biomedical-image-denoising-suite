"""Save and/or show the middle axial, coronal, and sagittal CT slices."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from src.dicom_volume import load_dicom_volume
from src.volume_views import orthogonal_views


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

    volume, spacing, _origin, direction = load_dicom_volume(args.series_dir)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for axis, view in zip(axes, orthogonal_views(volume, spacing, direction)):
        axis.imshow(view.image, cmap="gray", aspect=view.aspect)
        axis.set_title(f"{view.name} ({view.note})")

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
