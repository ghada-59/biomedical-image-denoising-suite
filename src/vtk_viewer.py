"""VTK helpers for geometrically faithful and clearly labelled CT volume views."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import vtk
from vtk.util import numpy_support


def numpy_to_vtk_volume(volume, spacing, origin, direction=None):
    """Convert a finite (z,y,x) NumPy array to VTK while preserving patient geometry."""
    if not isinstance(volume, np.ndarray) or volume.ndim != 3 or volume.size == 0:
        raise ValueError("volume must be a non-empty 3D NumPy array.")
    if not np.isfinite(volume).all():
        raise ValueError("volume must contain only finite values.")

    spacing = np.asarray(spacing, dtype=float)
    origin = np.asarray(origin, dtype=float)
    if spacing.shape != (3,) or not np.isfinite(spacing).all() or np.any(spacing <= 0):
        raise ValueError("spacing must contain three positive finite values.")
    if origin.shape != (3,) or not np.isfinite(origin).all():
        raise ValueError("origin must contain three finite values.")

    direction = np.eye(3) if direction is None else np.asarray(direction, dtype=float)
    if direction.shape != (3, 3) or not np.isfinite(direction).all():
        raise ValueError("direction must be a finite 3x3 matrix.")
    if not np.allclose(direction.T @ direction, np.eye(3), atol=1e-3):
        raise ValueError("direction matrix must be orthonormal.")

    contiguous = np.ascontiguousarray(volume.astype(np.float32))
    image = vtk.vtkImageData()
    image.SetDimensions(contiguous.shape[2], contiguous.shape[1], contiguous.shape[0])
    image.SetSpacing(*[float(value) for value in spacing])
    image.SetOrigin(*[float(value) for value in origin])

    matrix = vtk.vtkMatrix3x3()
    for row in range(3):
        for col in range(3):
            matrix.SetElement(row, col, float(direction[row, col]))
    image.SetDirectionMatrix(matrix)

    values = numpy_support.numpy_to_vtk(contiguous.ravel(order="C"), deep=True)
    values.SetName("CT modality values (HU when represented by the source DICOM)")
    image.GetPointData().SetScalars(values)
    return image


def create_ct_volume_actor(image, color_mode="grayscale"):
    """Create a volume actor with a documented CT-intensity transfer function.

    The grayscale mode is neutral. HU pseudo-colour is only a mapping of CT
    intensity values; it does not represent functional activity.
    """
    if color_mode not in {"grayscale", "hu-pseudocolor"}:
        raise ValueError("color_mode must be 'grayscale' or 'hu-pseudocolor'.")

    mapper = vtk.vtkSmartVolumeMapper()
    mapper.SetInputData(image)

    prop = vtk.vtkVolumeProperty()
    prop.ShadeOn()
    prop.SetInterpolationTypeToLinear()
    prop.SetAmbient(0.25)
    prop.SetDiffuse(0.70)
    prop.SetSpecular(0.15)
    prop.SetSpecularPower(12.0)
    prop.SetScalarOpacityUnitDistance(1.0)

    color = vtk.vtkColorTransferFunction()
    if color_mode == "grayscale":
        color_points = [
            (-1000, (0.00, 0.00, 0.00)),
            (-700, (0.15, 0.15, 0.15)),
            (-400, (0.32, 0.32, 0.32)),
            (-150, (0.58, 0.58, 0.58)),
            (0, (0.78, 0.78, 0.78)),
            (300, (0.93, 0.93, 0.93)),
            (1000, (1.00, 1.00, 1.00)),
        ]
    else:
        color_points = [
            (-1000, (0.05, 0.05, 0.10)),
            (-700, (0.10, 0.25, 0.80)),
            (-400, (0.10, 0.70, 0.95)),
            (-100, (0.20, 0.90, 0.70)),
            (100, (0.95, 0.85, 0.20)),
            (300, (1.00, 0.45, 0.10)),
            (700, (0.90, 0.10, 0.10)),
        ]
    for value, rgb in color_points:
        color.AddRGBPoint(value, *rgb)

    opacity = vtk.vtkPiecewiseFunction()
    for value, alpha in [
        (-1000, 0.00),
        (-900, 0.002),
        (-700, 0.008),
        (-400, 0.020),
        (-200, 0.045),
        (0, 0.090),
        (300, 0.180),
        (700, 0.300),
        (1200, 0.350),
    ]:
        opacity.AddPoint(value, alpha)

    prop.SetColor(color)
    prop.SetScalarOpacity(opacity)
    actor = vtk.vtkVolume()
    actor.SetMapper(mapper)
    actor.SetProperty(prop)
    return actor


def add_text_overlay(renderer, text, position=(18, 760), font_size=18):
    """Add a legible, shadowed annotation in window-display coordinates."""
    actor = vtk.vtkTextActor()
    actor.SetInput(str(text))
    actor.SetDisplayPosition(int(position[0]), int(position[1]))
    text_prop = actor.GetTextProperty()
    text_prop.SetFontSize(int(font_size))
    text_prop.SetBold(True)
    text_prop.SetColor(1.0, 1.0, 1.0)
    text_prop.SetShadow(True)
    renderer.AddActor2D(actor)
    return actor


def add_orientation_marker(interactor, viewport=(0.015, 0.02, 0.15, 0.22)):
    """Add an interactive XYZ orientation marker to a VTK render window."""
    axes = vtk.vtkAxesActor()
    widget = vtk.vtkOrientationMarkerWidget()
    widget.SetOrientationMarker(axes)
    widget.SetInteractor(interactor)
    widget.SetViewport(*viewport)
    widget.SetEnabled(True)
    widget.InteractiveOff()
    return widget


def save_render_window_png(render_window, output_path):
    """Render a VTK window and save a non-empty PNG snapshot."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    render_window.Render()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(render_window)
    capture.SetInputBufferTypeToRGB()
    capture.ReadFrontBufferOff()
    capture.Update()

    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(output))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()

    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"VTK failed to save a non-empty image: {output}")
    print(f"Figure saved to: {output}")
    return output
