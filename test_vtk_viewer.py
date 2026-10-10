"""Tests for CT-to-VTK conversion and the documented rendering modes."""
import numpy as np
import pytest
import vtk

from src.vtk_viewer import create_ct_volume_actor, numpy_to_vtk_volume


def test_numpy_to_vtk_volume_preserves_shape_spacing_origin_and_values():
    volume = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    spacing = (0.54, 0.54, 3.0)
    origin = (12.0, 23.0, 34.0)
    image = numpy_to_vtk_volume(volume, spacing, origin)

    assert image.GetDimensions() == (4, 3, 2)
    assert image.GetSpacing() == pytest.approx(spacing)
    assert image.GetOrigin() == pytest.approx(origin)
    assert image.GetPointData().GetScalars().GetNumberOfTuples() == volume.size


@pytest.mark.parametrize("mode", ["grayscale", "hu-pseudocolor"])
def test_create_ct_volume_actor_supports_documented_modes(mode):
    image = numpy_to_vtk_volume(
        np.zeros((2, 3, 4), dtype=np.float32), (1, 1, 1), (0, 0, 0)
    )
    actor = create_ct_volume_actor(image, color_mode=mode)
    assert isinstance(actor, vtk.vtkVolume)
    assert actor.GetMapper() is not None
    assert actor.GetProperty() is not None


def test_create_ct_volume_actor_rejects_unknown_colour_mode():
    image = numpy_to_vtk_volume(
        np.zeros((2, 3, 4), dtype=np.float32), (1, 1, 1), (0, 0, 0)
    )
    with pytest.raises(ValueError, match="color_mode"):
        create_ct_volume_actor(image, color_mode="functional-activity")


def test_numpy_to_vtk_volume_rejects_non_orthonormal_direction():
    volume = np.zeros((2, 3, 4), dtype=np.float32)
    bad_direction = np.array([[1, 1, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    with pytest.raises(ValueError, match="orthonormal"):
        numpy_to_vtk_volume(volume, (1, 1, 1), (0, 0, 0), bad_direction)
