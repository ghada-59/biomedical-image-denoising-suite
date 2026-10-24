"""Tests for DICOM series discovery, ordering, validation and geometry (src/dicom_volume.py).

Expected values are computed independently of the loader, straight from the DICOM bytes
with pydicom, so these tests do not merely mirror the implementation.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pydicom
import pytest

from conftest import make_dicom_bytes
from src.dicom_volume import discover_dicom_files, load_dicom_volume, sort_dicom_slices

SERIES = "1.2.826.0.1.3680043.8.498.100"


def _write(directory: Path, items: list[tuple[str, bytes]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, payload in items:
        (directory / name).write_bytes(payload)
    return directory


def _slice(z: float, number: int, **kwargs) -> bytes:
    return make_dicom_bytes(series_uid=kwargs.pop("series_uid", SERIES), instance_number=number, z_mm=z, **kwargs)


def _modality_values(payload: bytes) -> np.ndarray:
    """Slope/intercept applied by hand, independent of ``apply_modality_lut``."""
    ds = pydicom.dcmread(io.BytesIO(payload))
    return ds.pixel_array.astype(np.float64) * float(ds.RescaleSlope) + float(ds.RescaleIntercept)


# --- successful loading and geometry -----------------------------------------------------


def test_slices_are_ordered_by_physical_position_not_by_file_name(tmp_path):
    z_values = [0.0, 3.0, 6.0, 9.0]
    payloads = {z: _slice(z, number=i + 1) for i, z in enumerate(z_values)}
    # File names sort in the opposite order to the physical positions.
    items = [(f"a_{len(z_values) - i}.dcm", payloads[z]) for i, z in enumerate(z_values)]
    volume, spacing, origin, direction = load_dicom_volume(_write(tmp_path, items))

    expected = np.stack([_modality_values(payloads[z]) for z in z_values])
    assert volume.shape == (4, 16, 16)
    assert volume.dtype == np.float32
    np.testing.assert_allclose(volume, expected, atol=1e-3)
    assert origin == (0.0, 0.0, 0.0)


def test_spacing_is_returned_as_x_y_z_with_pixel_spacing_order_row_then_column(tmp_path):
    # DICOM PixelSpacing is (row spacing, column spacing) = (y, x).
    items = [(f"s{i}.dcm", _slice(i * 2.5, i + 1, pixel_spacing=(0.7, 0.9))) for i in range(3)]
    _, spacing, _, _ = load_dicom_volume(_write(tmp_path, items))
    assert spacing == pytest.approx((0.9, 0.7, 2.5))


def test_axial_direction_matrix_is_identity(tmp_path):
    items = [(f"s{i}.dcm", _slice(i * 2.0, i + 1)) for i in range(3)]
    _, _, _, direction = load_dicom_volume(_write(tmp_path, items))
    np.testing.assert_allclose(np.array(direction), np.eye(3), atol=1e-9)


def test_non_axial_series_is_sorted_along_its_own_normal(tmp_path):
    # Coronal-like orientation: rows along +x, columns along -z, so the normal is +y.
    orientation = (1.0, 0.0, 0.0, 0.0, 0.0, -1.0)
    ys = [10.0, 14.0, 18.0]
    payloads = [_slice(0.0, i + 1, orientation=orientation, position=(0.0, y, 0.0)) for i, y in enumerate(ys)]
    items = [(f"s{i}.dcm", payloads[len(ys) - 1 - i]) for i in range(len(ys))]  # reversed on disk
    volume, spacing, origin, direction = load_dicom_volume(_write(tmp_path, items))

    np.testing.assert_allclose(volume, np.stack([_modality_values(p) for p in payloads]), atol=1e-3)
    assert spacing[2] == pytest.approx(4.0)
    assert origin == (0.0, 10.0, 0.0)
    np.testing.assert_allclose(np.array(direction)[:, 2], [0.0, 1.0, 0.0], atol=1e-9)


def test_rescale_slope_and_intercept_are_applied(tmp_path):
    payloads = [_slice(i * 2.0, i + 1, overrides={"RescaleSlope": 2.0, "RescaleIntercept": -100.0}) for i in range(3)]
    volume, *_ = load_dicom_volume(_write(tmp_path, [(f"s{i}.dcm", p) for i, p in enumerate(payloads)]))
    raw = np.stack([pydicom.dcmread(io.BytesIO(p)).pixel_array.astype(np.float64) for p in payloads])
    np.testing.assert_allclose(volume, raw * 2.0 - 100.0, atol=1e-3)


def test_monochrome1_does_not_invert_quantitative_values(tmp_path):
    base = [_slice(i * 2.0, i + 1) for i in range(2)]
    inverted = [_slice(i * 2.0, i + 1, photometric="MONOCHROME1") for i in range(2)]
    vol_a, *_ = load_dicom_volume(_write(tmp_path / "m2", [(f"s{i}.dcm", p) for i, p in enumerate(base)]))
    vol_b, *_ = load_dicom_volume(_write(tmp_path / "m1", [(f"s{i}.dcm", p) for i, p in enumerate(inverted)]))
    np.testing.assert_array_equal(vol_a, vol_b)


def test_slice_spacing_within_tolerance_is_accepted(tmp_path):
    z_values = [0.0, 2.0, 4.03, 6.0]  # jitter of 0.03 mm, below max(0.1 mm, 2 %)
    items = [(f"s{i}.dcm", _slice(z, i + 1)) for i, z in enumerate(z_values)]
    _, spacing, _, _ = load_dicom_volume(_write(tmp_path, items))
    assert spacing[2] == pytest.approx(2.0, abs=0.05)


def test_single_slice_uses_spacing_between_slices_then_slice_thickness(tmp_path):
    only = [("s.dcm", _slice(0.0, 1, overrides={"SpacingBetweenSlices": 5.0, "SliceThickness": 1.0}))]
    assert load_dicom_volume(_write(tmp_path / "a", only))[1][2] == pytest.approx(5.0)
    only = [("s.dcm", _slice(0.0, 1, overrides={"SliceThickness": 1.5}))]
    assert load_dicom_volume(_write(tmp_path / "b", only))[1][2] == pytest.approx(1.5)


def test_single_slice_without_any_spacing_information_is_rejected(tmp_path):
    only = [("s.dcm", _slice(0.0, 1))]
    with pytest.raises(ValueError, match="Cannot determine spacing"):
        load_dicom_volume(_write(tmp_path, only))


# --- series consistency ------------------------------------------------------------------


def test_mixed_series_are_rejected(tmp_path):
    items = [
        ("a0.dcm", _slice(0.0, 1, series_uid="1.2.3.1")),
        ("a1.dcm", _slice(2.0, 2, series_uid="1.2.3.1")),
        ("b0.dcm", _slice(4.0, 3, series_uid="1.2.3.2")),
    ]
    with pytest.raises(ValueError, match="exactly one DICOM SeriesInstanceUID"):
        load_dicom_volume(_write(tmp_path, items))


def test_sort_dicom_slices_also_rejects_mixed_series(tmp_path):
    folder = _write(tmp_path, [("a.dcm", _slice(0.0, 1, series_uid="1.2.3.1")), ("b.dcm", _slice(2.0, 2, series_uid="1.2.3.2"))])
    with pytest.raises(ValueError, match="Multiple SeriesInstanceUID"):
        sort_dicom_slices(discover_dicom_files(folder))


def test_missing_slice_in_the_middle_is_detected_as_non_uniform_spacing(tmp_path):
    z_values = [0.0, 2.0, 4.0, 8.0]  # the slice at 6.0 mm is missing
    items = [(f"s{i}.dcm", _slice(z, i + 1)) for i, z in enumerate(z_values)]
    with pytest.raises(ValueError, match="Non-uniform slice spacing"):
        load_dicom_volume(_write(tmp_path, items))


def test_spacing_jitter_above_tolerance_is_rejected(tmp_path):
    z_values = [0.0, 2.0, 4.2, 6.0]  # 0.2 mm off, above max(0.1 mm, 2 %)
    items = [(f"s{i}.dcm", _slice(z, i + 1)) for i, z in enumerate(z_values)]
    with pytest.raises(ValueError, match="Non-uniform slice spacing"):
        load_dicom_volume(_write(tmp_path, items))


def test_duplicate_slice_positions_are_rejected(tmp_path):
    items = [("a.dcm", _slice(0.0, 1)), ("b.dcm", _slice(2.0, 2)), ("c.dcm", _slice(2.0, 3))]
    with pytest.raises(ValueError, match="Duplicate or non-increasing"):
        load_dicom_volume(_write(tmp_path, items))


def test_incompatible_orientations_are_rejected(tmp_path):
    items = [
        ("a.dcm", _slice(0.0, 1)),
        ("b.dcm", _slice(2.0, 2, orientation=(0.0, 1.0, 0.0, 1.0, 0.0, 0.0))),
    ]
    with pytest.raises(ValueError, match="Inconsistent ImageOrientationPatient"):
        load_dicom_volume(_write(tmp_path, items))


def test_non_orthonormal_orientation_is_rejected(tmp_path):
    bad = (1.0, 0.0, 0.0, 0.5, 0.5, 0.0)  # row and column directions are not perpendicular
    items = [(f"s{i}.dcm", _slice(i * 2.0, i + 1, orientation=bad)) for i in range(2)]
    with pytest.raises(ValueError, match="orthonormal"):
        load_dicom_volume(_write(tmp_path, items))


@pytest.mark.parametrize(
    "tag, message",
    [
        ("ImageOrientationPatient", "missing ImageOrientationPatient"),
        ("ImagePositionPatient", "missing ImagePositionPatient"),
    ],
)
def test_missing_geometry_tags_are_rejected(tmp_path, tag, message):
    items = [("a.dcm", _slice(0.0, 1)), ("b.dcm", _slice(2.0, 2, omit=(tag,)))]
    with pytest.raises(ValueError, match=message):
        load_dicom_volume(_write(tmp_path, items))


def test_inconsistent_pixel_spacing_is_rejected(tmp_path):
    items = [("a.dcm", _slice(0.0, 1)), ("b.dcm", _slice(2.0, 2, pixel_spacing=(0.9, 0.9)))]
    with pytest.raises(ValueError, match="Inconsistent PixelSpacing"):
        load_dicom_volume(_write(tmp_path, items))


def test_inconsistent_image_dimensions_are_rejected(tmp_path):
    items = [("a.dcm", _slice(0.0, 1)), ("b.dcm", _slice(2.0, 2, rows=8, cols=8))]
    with pytest.raises(ValueError, match="Inconsistent image dimensions"):
        load_dicom_volume(_write(tmp_path, items))


def test_inconsistent_photometric_interpretation_is_rejected(tmp_path):
    items = [("a.dcm", _slice(0.0, 1)), ("b.dcm", _slice(2.0, 2, photometric="MONOCHROME1"))]
    with pytest.raises(ValueError, match="Inconsistent PhotometricInterpretation"):
        load_dicom_volume(_write(tmp_path, items))


def test_unsupported_photometric_interpretation_is_rejected(tmp_path):
    items = [(f"s{i}.dcm", _slice(i * 2.0, i + 1, photometric="PALETTE COLOR")) for i in range(2)]
    with pytest.raises(ValueError, match="Unsupported PhotometricInterpretation"):
        load_dicom_volume(_write(tmp_path, items))


# --- directory handling and corrupt files ---------------------------------------------


def test_missing_directory_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_dicom_volume(tmp_path / "does_not_exist")


def test_a_file_path_instead_of_a_directory_is_rejected(tmp_path):
    file_path = tmp_path / "slice.dcm"
    file_path.write_bytes(_slice(0.0, 1))
    with pytest.raises(ValueError, match="Expected a directory"):
        load_dicom_volume(file_path)


def test_directory_without_dicom_files_is_rejected(tmp_path):
    _write(tmp_path, [("readme.txt", b"hello"), ("garbage.bin", b"\x00\x01\x02")])
    with pytest.raises(ValueError, match="No readable DICOM instances"):
        load_dicom_volume(tmp_path)


def test_non_dicom_files_in_a_series_folder_are_ignored(tmp_path):
    items = [(f"s{i}.dcm", _slice(i * 2.0, i + 1)) for i in range(3)]
    items += [("README.txt", b"notes"), ("index.json", b"{}")]
    volume, *_ = load_dicom_volume(_write(tmp_path, items))
    assert volume.shape[0] == 3


def test_unreadable_slice_in_the_middle_is_caught_by_the_spacing_check(tmp_path):
    items = [(f"s{i}.dcm", _slice(i * 2.0, i + 1)) for i in range(4)]
    items[2] = ("s2.dcm", b"corrupted bytes, not a DICOM file")
    with pytest.raises(ValueError, match="Non-uniform slice spacing"):
        load_dicom_volume(_write(tmp_path, items))


def test_unreadable_last_slice_is_silently_dropped_when_loading_a_folder(tmp_path):
    """Documents a known limitation of folder scanning.

    ``discover_dicom_files`` skips unreadable files (needed to ignore README files), so a
    corrupt slice at either end of the series leaves a shorter but internally consistent
    volume and no error. The upload API guards against this separately (see test_api.py).
    """
    items = [(f"s{i}.dcm", _slice(i * 2.0, i + 1)) for i in range(4)]
    items[3] = ("s3.dcm", b"corrupted bytes, not a DICOM file")
    volume, *_ = load_dicom_volume(_write(tmp_path, items))
    assert volume.shape[0] == 3


def test_truncated_pixel_data_raises_instead_of_returning_a_partial_slice(tmp_path):
    good = [_slice(i * 2.0, i + 1) for i in range(3)]
    truncated = good[1][:-100]  # header intact, pixel data cut short
    items = [("s0.dcm", good[0]), ("s1.dcm", truncated), ("s2.dcm", good[2])]
    with pytest.raises(ValueError, match="pixel data"):
        load_dicom_volume(_write(tmp_path, items))
