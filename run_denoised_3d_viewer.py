"""Render a DICOM CT volume before and after 3D Gaussian smoothing."""

from __future__ import annotations

import argparse

import vtk

from src.dicom_volume import load_dicom_volume
from src.volume_denoising import gaussian_denoise_volume
from src.vtk_viewer import numpy_to_vtk_volume


def create_volume(image: vtk.vtkImageData) -> vtk.vtkVolume:
    """Create a VTK volume actor with CT-oriented transfer functions."""
    mapper = vtk.vtkSmartVolumeMapper()
    mapper.SetInputData(image)

    volume_property = vtk.vtkVolumeProperty()
    volume_property.ShadeOn()
    volume_property.SetInterpolationTypeToLinear()

    color = vtk.vtkColorTransferFunction()
    color.AddRGBPoint(-1000, 0.05, 0.05, 0.10)
    color.AddRGBPoint(-700, 0.10, 0.25, 0.80)
    color.AddRGBPoint(-400, 0.10, 0.70, 0.95)
    color.AddRGBPoint(-100, 0.20, 0.90, 0.70)
    color.AddRGBPoint(100, 0.95, 0.85, 0.20)
    color.AddRGBPoint(300, 1.00, 0.45, 0.10)
    color.AddRGBPoint(700, 0.90, 0.10, 0.10)

    opacity = vtk.vtkPiecewiseFunction()
    opacity.AddPoint(-1000, 0.00)
    opacity.AddPoint(-700, 0.005)
    opacity.AddPoint(-400, 0.015)
    opacity.AddPoint(-100, 0.035)
    opacity.AddPoint(100, 0.08)
    opacity.AddPoint(300, 0.18)
    opacity.AddPoint(700, 0.30)

    volume_property.SetColor(color)
    volume_property.SetScalarOpacity(opacity)

    actor = vtk.vtkVolume()
    actor.SetMapper(mapper)
    actor.SetProperty(volume_property)
    return actor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare original and smoothed CT volumes."
    )
    parser.add_argument("series_dir", help="Path to a DICOM series directory.")
    parser.add_argument("--sigma", type=float, default=1.0)
    args = parser.parse_args()

    volume, spacing, origin = load_dicom_volume(args.series_dir)
    denoised = gaussian_denoise_volume(volume, sigma=args.sigma)

    original_actor = create_volume(
        numpy_to_vtk_volume(volume, spacing, origin)
    )
    denoised_actor = create_volume(
        numpy_to_vtk_volume(denoised, spacing, origin)
    )

    renderer_original = vtk.vtkRenderer()
    renderer_denoised = vtk.vtkRenderer()
    renderer_original.AddVolume(original_actor)
    renderer_denoised.AddVolume(denoised_actor)

    renderer_original.SetBackground(0.03, 0.03, 0.05)
    renderer_denoised.SetBackground(0.03, 0.03, 0.05)
    renderer_original.SetViewport(0.0, 0.0, 0.5, 1.0)
    renderer_denoised.SetViewport(0.5, 0.0, 1.0, 1.0)

    renderer_original.ResetCamera()
    camera = renderer_original.GetActiveCamera()
    renderer_denoised.SetActiveCamera(camera)
    renderer_denoised.ResetCameraClippingRange()

    window = vtk.vtkRenderWindow()
    window.AddRenderer(renderer_original)
    window.AddRenderer(renderer_denoised)
    window.SetSize(1400, 800)
    window.SetWindowName("CT: Original vs Smoothed")

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)

    window.Render()
    interactor.Start()


if __name__ == "__main__":
    main()
