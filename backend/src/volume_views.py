"""Orthogonal (axial, coronal, sagittal) views of a (z, y, x) volume, oriented for display.

A series loaded by ``load_dicom_volume`` has its slices sorted by position along the slice normal, so index 0 is the
lowest position. For an axial series in the usual patient frame (DICOM LPS: +x towards the patient's left, +y towards the
back, +z towards the head) that is the *inferior* end. ``imshow`` draws row 0 at the top, so an unflipped coronal or
sagittal slice shows the feet at the top. This module flips those two views so that superior is up.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class View:
    name: str
    image: np.ndarray          # 2D array, ready for imshow with the default origin
    aspect: float              # pixel height / pixel width in millimetres, for imshow(aspect=...)
    note: str                  # what the display orientation is


def superior_is_up(direction: tuple | np.ndarray | None) -> bool:
    """True when increasing slice index moves towards the patient's head (slice normal pointing along +z)."""
    if direction is None:
        return False
    normal = np.asarray(direction, dtype=float)[:, 2]
    return bool(normal[2] > 0.5)


def orthogonal_views(volume: np.ndarray, spacing_xyz_mm: tuple[float, float, float], direction: tuple | np.ndarray | None = None) -> list[View]:
    """Middle axial, coronal and sagittal slices of ``volume`` (z, y, x) with their physical aspect ratios.

    The axial view is drawn as stored (anterior at the top, patient's left on the right for an LPS series). Coronal and
    sagittal views are flipped vertically when the slice normal points towards the head, so that superior is at the top.
    For a series whose normal does not point along +z the vertical axis is left as stored and the note says so.
    """
    if not isinstance(volume, np.ndarray) or volume.ndim != 3 or volume.size == 0:
        raise ValueError("volume must be a non-empty 3D NumPy array.")
    spacing = np.asarray(spacing_xyz_mm, dtype=float)
    if spacing.shape != (3,) or not np.isfinite(spacing).all() or np.any(spacing <= 0):
        raise ValueError("spacing_xyz_mm must contain three positive finite values.")
    sx, sy, sz = (float(v) for v in spacing)
    nz, ny, nx = volume.shape
    flip = superior_is_up(direction)
    vertical = "superior at the top" if flip else "vertical axis as stored (orientation not determined)"
    coronal = volume[:, ny // 2, :]
    sagittal = volume[:, :, nx // 2]
    return [
        View("Axial", volume[nz // 2], sy / sx, "as stored"),
        View("Coronal", coronal[::-1] if flip else coronal, sz / sx, vertical),
        View("Sagittal", sagittal[::-1] if flip else sagittal, sz / sy, vertical),
    ]
