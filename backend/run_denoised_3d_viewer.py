"""Render and compare original and Gaussian-smoothed CT volumes in 3D."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import vtk

from src.dicom_volume import load_dicom_volume
from src.volume_denoising import gaussian_denoise_volume
from src.vtk_viewer import (
    add_orientation_marker,
    add_text_overlay,
    create_ct_volume_actor,
    numpy_to_vtk_volume,
    save_render_window_png,
)


def main():
    parser = argparse.ArgumentParser(
        description="Compare original and Gaussian-smoothed DICOM CT volumes in 3D."
    )
    parser.add_argument("series_dir", help="Directory containing one DICOM series.")
    parser.add_argument(
        "--sigma-mm",
        "--sigma",
        dest="sigma_mm",
        type=float,
        default=1.0,
        help="Gaussian standard deviation in physical millimetres (default: 1.0).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/3D/original_vs_smoothed_ct.png"),
    )
    parser.add_argument(
        "--color-mode",
        choices=("grayscale", "hu-pseudocolor"),
        default="grayscale",
        help="Use the same intensity transfer function for both volumes.",
    )
    args = parser.parse_args()
    if not np.isfinite(args.sigma_mm) or args.sigma_mm <= 0:
        parser.error("--sigma-mm must be finite and greater than zero.")

    volume, spacing, origin, direction = load_dicom_volume(args.series_dir)
    smoothed = gaussian_denoise_volume(
        volume, sigma=args.sigma_mm, spacing_xyz_mm=spacing
    )

    left = vtk.vtkRenderer()
    right = vtk.vtkRenderer()
    left.SetViewport(0, 0, 0.5, 1)
    right.SetViewport(0.5, 0, 1, 1)
    left.SetBackground(0.025, 0.03, 0.045)
    right.SetBackground(0.025, 0.03, 0.045)

    left.AddVolume(
        create_ct_volume_actor(
            numpy_to_vtk_volume(volume, spacing, origin, direction),
            color_mode=args.color_mode,
        )
    )
    right.AddVolume(
        create_ct_volume_actor(
            numpy_to_vtk_volume(smoothed, spacing, origin, direction),
            color_mode=args.color_mode,
        )
    )

    window = vtk.vtkRenderWindow()
    window.AddRenderer(left)
    window.AddRenderer(right)
    window.SetSize(1600, 900)
    window.SetWindowName(
        f"CT Original vs 3D Gaussian Smoothed — sigma {args.sigma_mm:g} mm"
    )

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    orientation_widget = add_orientation_marker(interactor)

    left.ResetCamera()
    camera = left.GetActiveCamera()
    camera.Azimuth(20)
    camera.Elevation(10)
    right.SetActiveCamera(camera)
    left.ResetCameraClippingRange()
    right.ResetCameraClippingRange()

    add_text_overlay(left, "ORIGINAL CT", (22, 855), 21)
    add_text_overlay(right, "3D GAUSSIAN-SMOOTHED CT", (822, 855), 21)
    add_text_overlay(
        left,
        f"Original | spacing (x,y,z): {spacing} mm",
        (22, 822),
        12,
    )
    add_text_overlay(
        right,
        f"sigma = {args.sigma_mm:g} mm | identical intensity mapping",
        (822, 822),
        12,
    )
    add_text_overlay(
        left,
        "CT intensity mapping only; not functional activity",
        (22, 22),
        11,
    )
    add_text_overlay(
        right,
        "Smoothing may blur small anatomical details",
        (822, 22),
        11,
    )

    save_render_window_png(window, args.output)
    _ = orientation_widget
    interactor.Initialize()
    interactor.Start()


if __name__ == "__main__":
    main()
