"""Render a DICOM CT series as a VTK volume."""

from __future__ import annotations

import argparse

import vtk

from src.dicom_volume import load_dicom_volume
from src.vtk_viewer import numpy_to_vtk_volume


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a DICOM CT volume.")
    parser.add_argument("series_dir", help="Path to a DICOM series directory.")
    args = parser.parse_args()

    volume, spacing, origin = load_dicom_volume(args.series_dir)
    image = numpy_to_vtk_volume(volume, spacing, origin)

    mapper = vtk.vtkSmartVolumeMapper()
    mapper.SetInputData(image)

    volume_property = vtk.vtkVolumeProperty()
    volume_property.ShadeOn()
    volume_property.SetInterpolationTypeToLinear()

    color = vtk.vtkColorTransferFunction()
    color.AddRGBPoint(-1000, 0.0, 0.0, 0.0)
    color.AddRGBPoint(-500, 0.7, 0.7, 0.7)
    color.AddRGBPoint(0, 0.9, 0.9, 0.9)
    color.AddRGBPoint(500, 1.0, 1.0, 1.0)

    opacity = vtk.vtkPiecewiseFunction()
    opacity.AddPoint(-1000, 0.0)
    opacity.AddPoint(-500, 0.01)
    opacity.AddPoint(-200, 0.03)
    opacity.AddPoint(0, 0.08)
    opacity.AddPoint(300, 0.15)
    opacity.AddPoint(700, 0.25)

    volume_property.SetColor(color)
    volume_property.SetScalarOpacity(opacity)

    actor = vtk.vtkVolume()
    actor.SetMapper(mapper)
    actor.SetProperty(volume_property)

    renderer = vtk.vtkRenderer()
    renderer.AddVolume(actor)
    renderer.SetBackground(0.1, 0.1, 0.1)

    window = vtk.vtkRenderWindow()
    window.AddRenderer(renderer)
    window.SetSize(1000, 800)
    window.SetWindowName("DICOM CT Volume")

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)

    renderer.ResetCamera()
    window.Render()
    interactor.Start()


if __name__ == "__main__":
    main()
