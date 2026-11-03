"""Render a labelled DICOM CT volume in 3D and export a PNG snapshot."""
from __future__ import annotations

import argparse
from pathlib import Path

import vtk

from src.dicom_volume import load_dicom_volume
from src.vtk_viewer import (
    add_orientation_marker,
    add_text_overlay,
    create_ct_volume_actor,
    numpy_to_vtk_volume,
    save_render_window_png,
)


def main():
    parser = argparse.ArgumentParser(
        description="Render one DICOM CT volume in 3D and export a labelled snapshot."
    )
    parser.add_argument("series_dir", help="Directory containing one DICOM series.")
    parser.add_argument(
        "--output", type=Path, default=Path("reports/3D/original_ct_volume.png")
    )
    parser.add_argument(
        "--color-mode",
        choices=("grayscale", "hu-pseudocolor"),
        default="grayscale",
        help="grayscale is the neutral CT view; hu-pseudocolor colours CT intensities only.",
    )
    args = parser.parse_args()

    volume, spacing, origin, direction = load_dicom_volume(args.series_dir)
    image = numpy_to_vtk_volume(volume, spacing, origin, direction)
    actor = create_ct_volume_actor(image, color_mode=args.color_mode)

    renderer = vtk.vtkRenderer()
    renderer.AddVolume(actor)
    renderer.SetBackground(0.025, 0.03, 0.045)

    window = vtk.vtkRenderWindow()
    window.AddRenderer(renderer)
    window.SetSize(1200, 900)
    window.SetWindowName("DICOM CT — 3D Volume Rendering")

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    orientation_widget = add_orientation_marker(interactor)

    renderer.ResetCamera()
    renderer.GetActiveCamera().Azimuth(20)
    renderer.GetActiveCamera().Elevation(10)
    renderer.ResetCameraClippingRange()
    add_text_overlay(renderer, "DICOM CT | 3D VOLUME RENDERING", (22, 855), 21)
    add_text_overlay(
        renderer,
        f"Shape (z,y,x): {volume.shape} | spacing (x,y,z): {spacing} mm",
        (22, 822),
        13,
    )
    add_text_overlay(
        renderer,
        f"Display: {args.color_mode} | colour encodes CT intensity, not function",
        (22, 22),
        12,
    )

    save_render_window_png(window, args.output)
    # Keep the widget referenced for the lifetime of the interactive window.
    _ = orientation_widget
    interactor.Initialize()
    interactor.Start()


if __name__ == "__main__":
    main()
