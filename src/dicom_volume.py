"""Validated DICOM-series loading with physical geometry preservation."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pydicom
from pydicom.pixels import apply_modality_lut


def _header(path: Path):
    try:
        return pydicom.dcmread(path, stop_before_pixels=True)
    except Exception:
        return None


def discover_dicom_files(series_dir: str | Path) -> list[Path]:
    """Find readable DICOM instances below a directory."""
    root = Path(series_dir)
    if not root.exists():
        raise FileNotFoundError(f"DICOM series directory not found: {root}")
    if not root.is_dir():
        raise ValueError(f"Expected a directory, got: {root}")
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            ds = _header(path)
            if ds is not None and hasattr(ds, "SOPInstanceUID") and hasattr(ds, "SeriesInstanceUID"):
                files.append(path)
    if not files:
        raise ValueError(f"No readable DICOM instances found in: {root}")
    return files


def _orientation(dataset):
    if not hasattr(dataset, "ImageOrientationPatient"):
        raise ValueError("DICOM slice is missing ImageOrientationPatient.")
    values = np.asarray(dataset.ImageOrientationPatient, dtype=float)
    if values.shape != (6,) or not np.isfinite(values).all():
        raise ValueError("ImageOrientationPatient must contain six finite values.")
    x_dir, y_dir = values[:3], values[3:]
    if (not np.isclose(np.linalg.norm(x_dir), 1, atol=1e-3)
        or not np.isclose(np.linalg.norm(y_dir), 1, atol=1e-3)
        or not np.isclose(np.dot(x_dir, y_dir), 0, atol=1e-3)):
        raise ValueError("ImageOrientationPatient direction cosines must be orthonormal.")
    normal = np.cross(x_dir, y_dir)
    normal /= np.linalg.norm(normal)
    return x_dir, y_dir, normal


def _position(dataset):
    if not hasattr(dataset, "ImagePositionPatient"):
        raise ValueError("DICOM slice is missing ImagePositionPatient.")
    position = np.asarray(dataset.ImagePositionPatient, dtype=float)
    if position.shape != (3,) or not np.isfinite(position).all():
        raise ValueError("ImagePositionPatient must contain three finite values.")
    return position


def sort_dicom_slices(files: list[Path]) -> list[Path]:
    """Sort slices along the physical normal and reject mixed series/orientations."""
    if not files:
        raise ValueError("No DICOM files were supplied.")
    entries, series_uid, reference_orientation, normal = [], None, None, None
    for path in files:
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        uid = str(getattr(ds, "SeriesInstanceUID", ""))
        if not uid:
            raise ValueError(f"Missing SeriesInstanceUID in {path}.")
        if series_uid is None:
            series_uid = uid
        elif uid != series_uid:
            raise ValueError("Multiple SeriesInstanceUID values were found.")
        x_dir, y_dir, this_normal = _orientation(ds)
        orientation = np.asarray(ds.ImageOrientationPatient, dtype=float)
        if reference_orientation is None:
            reference_orientation, normal = orientation, this_normal
        elif not np.allclose(orientation, reference_orientation, atol=1e-3):
            raise ValueError("Inconsistent ImageOrientationPatient across DICOM slices.")
        entries.append((float(np.dot(_position(ds), normal)), path))
    entries.sort(key=lambda item: item[0])
    distances = np.asarray([item[0] for item in entries])
    if len(distances) > 1 and np.any(np.diff(distances) <= 1e-6):
        raise ValueError("Duplicate or non-increasing physical slice positions were found.")
    return [item[1] for item in entries]


def load_dicom_volume(series_dir: str | Path):
    """Return modality values, xyz spacing, patient-space origin and direction matrix.

    Volume array order is (z,y,x); spacing is (x,y,z) in millimetres. MONOCHROME1
    affects display polarity, not the quantitative modality values returned here.
    """
    discovered = discover_dicom_files(series_dir)
    headers = [pydicom.dcmread(p, stop_before_pixels=True) for p in discovered]
    uids = {str(getattr(ds, "SeriesInstanceUID", "")) for ds in headers}
    if len(uids) != 1 or not next(iter(uids), ""):
        raise ValueError("Expected exactly one DICOM SeriesInstanceUID. Use a single-series folder.")
    files = sort_dicom_slices(discovered)
    datasets = [pydicom.dcmread(p) for p in files]
    first = datasets[0]
    rows, cols = int(first.Rows), int(first.Columns)
    pixel_spacing = np.asarray(first.PixelSpacing, dtype=float)
    if pixel_spacing.shape != (2,) or not np.isfinite(pixel_spacing).all() or np.any(pixel_spacing <= 0):
        raise ValueError("PixelSpacing must contain two positive finite values.")
    x_dir, y_dir, normal = _orientation(first)
    direction_matrix = np.column_stack((x_dir, y_dir, normal))
    slices, positions = [], []
    uid = str(first.SeriesInstanceUID)
    photometric = str(getattr(first, "PhotometricInterpretation", "MONOCHROME2"))
    for path, ds in zip(files, datasets):
        if str(getattr(ds, "SeriesInstanceUID", "")) != uid:
            raise ValueError("Multiple SeriesInstanceUID values were found.")
        if int(ds.Rows) != rows or int(ds.Columns) != cols:
            raise ValueError(f"Inconsistent image dimensions in {path}.")
        if not np.allclose(np.asarray(ds.PixelSpacing, dtype=float), pixel_spacing, atol=1e-5, rtol=0):
            raise ValueError(f"Inconsistent PixelSpacing in {path}.")
        if str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")) != photometric:
            raise ValueError(f"Inconsistent PhotometricInterpretation in {path}.")
        if photometric not in ("MONOCHROME1", "MONOCHROME2"):
            raise ValueError(f"Unsupported PhotometricInterpretation {photometric!r}.")
        pixels = ds.pixel_array
        if pixels.ndim != 2 or int(getattr(ds, "SamplesPerPixel", 1)) != 1:
            raise ValueError(f"Expected a single-frame grayscale slice in {path}.")
        values = np.asarray(apply_modality_lut(pixels, ds), dtype=np.float32)
        if not np.isfinite(values).all():
            raise ValueError(f"Non-finite modality values found in {path}.")
        slices.append(values)
        positions.append(_position(ds))
    positions = np.asarray(positions)
    distances = positions @ normal
    if len(distances) > 1:
        differences = np.diff(distances)
        spacing_z = float(np.median(differences))
        if np.any(np.abs(differences - spacing_z) > max(0.1, spacing_z * 0.02)):
            raise ValueError("Non-uniform slice spacing detected; resample before 3D voxel-grid processing.")
    elif hasattr(first, "SpacingBetweenSlices"):
        spacing_z = abs(float(first.SpacingBetweenSlices))
    elif hasattr(first, "SliceThickness"):
        spacing_z = float(first.SliceThickness)
    else:
        raise ValueError("Cannot determine spacing for a single-slice series.")
    if not np.isfinite(spacing_z) or spacing_z <= 0:
        raise ValueError("Slice spacing must be positive and finite.")
    volume = np.stack(slices, axis=0)
    spacing_xyz = (float(pixel_spacing[1]), float(pixel_spacing[0]), spacing_z)
    origin_xyz = tuple(float(v) for v in positions[0])
    direction = tuple(tuple(float(direction_matrix[r, c]) for c in range(3)) for r in range(3))
    return volume, spacing_xyz, origin_xyz, direction
