"""Utilities for displaying NumPy volumes with VTK."""

from __future__ import annotations

import numpy as np
import vtk
from vtk.util import numpy_support


def numpy_to_vtk_volume(
    volume: np.ndarray,
    spacing: tuple[float, float, float],
    origin: tuple[float, float, float],
) -> vtk.vtkImageData:
    """Convert a z-y-x NumPy volume to VTK ImageData."""
    if not isinstance(volume, np.ndarray) or volume.ndim != 3:
        raise ValueError("volume must be a 3D NumPy array.")
    if not np.isfinite(volume).all():
        raise ValueError("volume must contain only finite values.")
    if len(spacing) != 3 or any(value <= 0 for value in spacing):
        raise ValueError("spacing must contain three positive values.")
    if len(origin) != 3:
        raise ValueError("origin must contain three values.")

    volume = np.ascontiguousarray(volume)
    image = vtk.vtkImageData()
    image.SetDimensions(volume.shape[2], volume.shape[1], volume.shape[0])
    image.SetSpacing(spacing)
    image.SetOrigin(origin)

    vtk_array = numpy_support.numpy_to_vtk(
        volume.ravel(order="C"),
        deep=True,
        array_type=numpy_support.get_vtk_array_type(volume.dtype),
    )
    image.GetPointData().SetScalars(vtk_array)
    return image
