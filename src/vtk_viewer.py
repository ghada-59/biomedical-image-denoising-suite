import numpy as np
import vtk
from vtk.util import numpy_support


def numpy_to_vtk_volume(
    volume: np.ndarray,
    spacing: tuple[float, float, float],
    origin: tuple[float, float, float],
) -> vtk.vtkImageData:
    if volume.ndim != 3:
        raise ValueError("Expected a 3D NumPy array.")

    volume = np.ascontiguousarray(volume)

    image = vtk.vtkImageData()
    image.SetDimensions(
        volume.shape[2],
        volume.shape[1],
        volume.shape[0],
    )
    image.SetSpacing(spacing)
    image.SetOrigin(origin)

    vtk_array = numpy_support.numpy_to_vtk(
        volume.ravel(order="C"),
        deep=True,
        array_type=numpy_support.get_vtk_array_type(volume.dtype),
    )

    image.GetPointData().SetScalars(vtk_array)

    return image