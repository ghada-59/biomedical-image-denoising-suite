"""DICOM series discovery, validation, sorting, and 3D reconstruction."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
from pydicom.pixel_data_handlers.util import apply_modality_lut


def discover_dicom_files(series_dir: str | Path) -> list[Path]:
    """Find readable DICOM instances in a directory tree."""
    series_path = Path(series_dir)

    if not series_path.exists():
        raise FileNotFoundError(f"DICOM series directory not found: {series_path}")
    if not series_path.is_dir():
        raise ValueError(f"Expected a directory, got: {series_path}")

    files = []
    for path in sorted(series_path.rglob("*")):
        if not path.is_file():
            continue
        try:
            dataset = pydicom.dcmread(path, stop_before_pixels=True)
        except Exception:
            continue
        if hasattr(dataset, "SOPInstanceUID"):
            files.append(path)

    if not files:
        raise ValueError(f"No readable DICOM files found in: {series_path}")

    return files


def _slice_key(dataset: pydicom.Dataset) -> tuple[float, np.ndarray]:
    """Return the physical position used to order a slice."""
    if hasattr(dataset, "ImageOrientationPatient") and hasattr(
        dataset, "ImagePositionPatient"
    ):
        orientation = np.asarray(
            dataset.ImageOrientationPatient, dtype=float
        )
        if orientation.size != 6:
            raise ValueError("ImageOrientationPatient must contain 6 values.")
        row = orientation[:3]
        column = orientation[3:]
        normal = np.cross(row, column)
        norm = np.linalg.norm(normal)
        if norm == 0:
            raise ValueError("Invalid ImageOrientationPatient.")
        normal /= norm
        position = np.asarray(dataset.ImagePositionPatient, dtype=float)
        return float(np.dot(position, normal)), normal

    if hasattr(dataset, "SliceLocation"):
        return float(dataset.SliceLocation), np.array([0.0, 0.0, 1.0])

    raise ValueError(
        "DICOM slice has neither ImagePositionPatient nor SliceLocation."
    )


def sort_dicom_slices(files: list[Path]) -> list[Path]:
    """Sort slices along their physical acquisition direction."""
    entries = []
    reference_normal = None

    for path in files:
        dataset = pydicom.dcmread(path, stop_before_pixels=True)
        position, normal = _slice_key(dataset)
        if reference_normal is None:
            reference_normal = normal
        elif not np.allclose(
            np.abs(np.dot(reference_normal, normal)), 1.0, atol=1e-3
        ):
            raise ValueError("Inconsistent slice orientation in DICOM series.")
        entries.append((position, path))

    entries.sort(key=lambda item: item[0])
    return [path for _, path in entries]


def load_dicom_volume(
    series_dir: str | Path,
) -> tuple[np.ndarray, tuple[float, float, float], tuple[float, float, float]]:
    """Load a validated single-frame DICOM series as a 3D array.

    The returned volume uses CT modality values when RescaleSlope/
    RescaleIntercept are present. For CT, these are normally Hounsfield units.
    """
    files = sort_dicom_slices(discover_dicom_files(series_dir))
    datasets = [pydicom.dcmread(path) for path in files]
    first = datasets[0]

    series_uid = getattr(first, "SeriesInstanceUID", None)
    rows = int(first.Rows)
    columns = int(first.Columns)
    first_spacing = np.asarray(first.PixelSpacing, dtype=float)

    if first_spacing.size != 2 or np.any(first_spacing <= 0):
        raise ValueError("Invalid PixelSpacing in DICOM series.")

    slices = []
    positions = []

    for dataset in datasets:
        if getattr(dataset, "SeriesInstanceUID", series_uid) != series_uid:
            raise ValueError("Multiple SeriesInstanceUID values were found.")

        if int(dataset.Rows) != rows or int(dataset.Columns) != columns:
            raise ValueError("Inconsistent image dimensions in DICOM series.")

        spacing = np.asarray(dataset.PixelSpacing, dtype=float)
        if spacing.size != 2 or not np.allclose(spacing, first_spacing):
            raise ValueError("Inconsistent PixelSpacing in DICOM series.")

        pixel_array = dataset.pixel_array
        if pixel_array.ndim != 2:
            raise ValueError("Expected single-frame 2D DICOM slices.")

        pixel_array = apply_modality_lut(pixel_array, dataset)
        slices.append(np.asarray(pixel_array, dtype=np.float32))

        position = np.asarray(dataset.ImagePositionPatient, dtype=float)
        if position.size != 3:
            raise ValueError("Invalid ImagePositionPatient.")
        positions.append(position)

    volume = np.stack(slices, axis=0)

    _, normal = _slice_key(first)
    positions = np.asarray(positions)
    distances = positions @ normal
    if len(distances) > 1:
        spacing_z = float(np.median(np.abs(np.diff(distances))))
        if spacing_z <= 0:
            raise ValueError("Invalid slice spacing.")
    elif hasattr(first, "SliceThickness"):
        spacing_z = float(first.SliceThickness)
    else:
        raise ValueError("Cannot determine slice spacing.")

    spacing = (
        float(first_spacing[1]),
        float(first_spacing[0]),
        spacing_z,
    )
    origin = tuple(float(value) for value in positions[0])

    return volume, spacing, origin
