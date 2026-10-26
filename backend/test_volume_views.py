"""Display orientation of the orthogonal views (src/volume_views.py)."""

from __future__ import annotations

import numpy as np
import pytest

from src.volume_views import orthogonal_views, superior_is_up

IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
FLIPPED_STACK = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0))   # slice normal pointing towards the feet


def _volume_with_marker_in_last_slice():
    volume = np.zeros((6, 8, 10), dtype=np.float32)
    volume[5, :, :] = 100.0     # the highest slice index = the superior end for an axial LPS series
    return volume


def test_superior_end_is_drawn_at_the_top_of_coronal_and_sagittal_views():
    views = {v.name: v for v in orthogonal_views(_volume_with_marker_in_last_slice(), (0.5, 0.5, 3.0), IDENTITY)}
    for name in ("Coronal", "Sagittal"):
        assert views[name].image[0].min() == 100.0 and views[name].image[-1].max() == 0.0, name   # row 0 is drawn at the top by imshow
        assert "superior at the top" in views[name].note
    assert views["Axial"].image.shape == (8, 10)


def test_a_stack_whose_normal_points_to_the_feet_is_not_flipped():
    views = {v.name: v for v in orthogonal_views(_volume_with_marker_in_last_slice(), (0.5, 0.5, 3.0), FLIPPED_STACK)}
    assert views["Coronal"].image[-1].min() == 100.0           # last slice index stays at the bottom
    views = {v.name: v for v in orthogonal_views(_volume_with_marker_in_last_slice(), (0.5, 0.5, 3.0), None)}
    assert views["Coronal"].image[-1].min() == 100.0 and "not determined" in views["Coronal"].note


def test_aspect_ratios_use_the_physical_spacing():
    views = {v.name: v for v in orthogonal_views(np.zeros((5, 6, 7)), (0.5, 0.8, 3.0), IDENTITY)}
    assert views["Axial"].aspect == pytest.approx(0.8 / 0.5)
    assert views["Coronal"].aspect == pytest.approx(3.0 / 0.5)
    assert views["Sagittal"].aspect == pytest.approx(3.0 / 0.8)


def test_superior_is_up_only_for_a_normal_along_plus_z():
    assert superior_is_up(IDENTITY) and not superior_is_up(FLIPPED_STACK) and not superior_is_up(None)


@pytest.mark.parametrize("volume, spacing", [(np.zeros((3, 3)), (1, 1, 1)), (np.zeros((0, 3, 3)), (1, 1, 1)), (np.zeros((2, 3, 3)), (1, 0, 1)), (np.zeros((2, 3, 3)), (1, 1))])
def test_invalid_input_is_rejected(volume, spacing):
    with pytest.raises(ValueError):
        orthogonal_views(volume, spacing, IDENTITY)
