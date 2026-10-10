"""VTK conversion and PNG export helpers."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import vtk
from vtk.util import numpy_support


def numpy_to_vtk_volume(volume, spacing, origin, direction=None):
    """Convert a finite (z,y,x) NumPy array to VTK preserving physical geometry."""
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
    image.SetSpacing(*[float(x) for x in spacing])
    image.SetOrigin(*[float(x) for x in origin])
    matrix = vtk.vtkMatrix3x3()
    for row in range(3):
        for col in range(3):
            matrix.SetElement(row, col, float(direction[row, col]))
    image.SetDirectionMatrix(matrix)
    values = numpy_support.numpy_to_vtk(contiguous.ravel(order="C"), deep=True)
    values.SetName("CT modality values")
    image.GetPointData().SetScalars(values)
    return image


def save_render_window_png(render_window, output_path):
    """Render a VTK window and save a PNG snapshot."""
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
