"""Shared test fixtures: small in-memory image and DICOM factories."""

from __future__ import annotations

import io
import warnings

import cv2
import numpy as np
import pytest


def make_png_bytes(size: tuple[int, int] = (64, 64), seed: int = 0) -> bytes:
    """Return a small grayscale PNG with a bright disc on a dark background."""
    rows, cols = size
    yy, xx = np.mgrid[0:rows, 0:cols]
    radius = np.hypot(yy - rows / 2, xx - cols / 2)
    image = np.where(radius < min(rows, cols) * 0.3, 200, 40).astype(np.uint8)
    image = image + np.random.default_rng(seed).integers(0, 5, size=image.shape, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def make_dicom_bytes(
    *,
    series_uid: str,
    instance_number: int,
    z_mm: float,
    rows: int = 16,
    cols: int = 16,
    pixel_spacing: tuple[float, float] = (0.8, 0.8),
    orientation: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
    photometric: str = "MONOCHROME2",
    seed: int = 0,
    position: tuple[float, float, float] | None = None,
    omit: tuple[str, ...] = (),
    overrides: dict | None = None,
    hu: np.ndarray | None = None,
) -> bytes:
    """Return a minimal, valid single-frame CT DICOM file as bytes.

    Stored values are signed 16-bit with RescaleIntercept -1024, so the modality
    values (HU) are ``stored - 1024``. ``position`` replaces the default
    ImagePositionPatient ``(0, 0, z_mm)``; ``omit`` deletes attributes and
    ``overrides`` sets extra ones, so tests can build deliberately defective files.
    """
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    yy, xx = np.mgrid[0:rows, 0:cols]
    radius = np.hypot(yy - rows / 2, xx - cols / 2)
    if hu is None:
        hu = np.where(radius < min(rows, cols) * 0.3, 300.0, -800.0)
        hu = hu + np.random.default_rng(seed + instance_number).normal(0, 5, size=hu.shape)
    elif hu.shape != (rows, cols):
        raise ValueError("hu must have shape (rows, cols).")
    stored = np.round(hu + 1024.0).astype(np.int16)

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = FileDataset(
            None, {}, file_meta=file_meta, preamble=b"\x00" * 128,
            is_implicit_VR=False, is_little_endian=True,
        )
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = series_uid
    ds.StudyInstanceUID = "1.2.826.0.1.3680043.8.498.1"
    ds.Modality = "CT"
    ds.InstanceNumber = instance_number
    ds.Rows, ds.Columns = rows, cols
    ds.PixelSpacing = list(pixel_spacing)
    ds.ImageOrientationPatient = list(orientation)
    ds.ImagePositionPatient = list(position) if position is not None else [0.0, 0.0, float(z_mm)]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.RescaleSlope = 1.0
    ds.RescaleIntercept = -1024.0
    ds.WindowCenter = -300
    ds.WindowWidth = 1400
    ds.PixelData = stored.tobytes()
    for key, value in (overrides or {}).items():
        setattr(ds, key, value)
    for key in omit:
        delattr(ds, key)

    buffer = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds.save_as(buffer)
    return buffer.getvalue()


@pytest.fixture
def png_bytes() -> bytes:
    return make_png_bytes()


@pytest.fixture
def dicom_series_bytes():
    """Factory: ``dicom_series_bytes(n)`` -> list of (filename, bytes) for one series."""

    def factory(count: int = 3, *, spacing_mm: float = 2.0, series_uid: str = "1.2.826.0.1.3680043.8.498.77"):
        return [
            (
                f"slice_{index:03d}.dcm",
                make_dicom_bytes(series_uid=series_uid, instance_number=index + 1, z_mm=index * spacing_mm),
            )
            for index in range(count)
        ]

    return factory
