"""The bundled chest CT sample: how download_data.py cuts it from a LOCAL series, what it refuses, and that it never silently replaces the shipped file.

Small synthetic series are written to temporary folders; the real LIDC-IDRI series is only used by the last test, and only if it is present.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import download_data
from conftest import make_dicom_bytes

SERIES_A = "1.2.826.0.1.3680043.8.498.101"
SERIES_B = "1.2.826.0.1.3680043.8.498.202"
ROOT = Path(__file__).resolve().parent.parent

# Lung window -600/1500 HU spans [-1350, 150] HU: HU = -1350 + 300 k is displayed as exactly 51 k out of 255.
LEVELS_5 = [-1350.0 + 300.0 * k for k in range(5)]
EXPECTED_5 = [0, 51, 102, 153, 204]


def write_series(directory: Path, levels_hu, *, rows: int = 16, cols: int = 16, series_uid: str = SERIES_A) -> Path:
    """One constant-HU slice per level, 3 mm apart: the slice a test asks for can be recognised by its single grey value."""
    directory.mkdir(parents=True, exist_ok=True)
    for index, level in enumerate(levels_hu):
        payload = make_dicom_bytes(series_uid=series_uid, instance_number=index + 1, z_mm=3.0 * index, rows=rows, cols=cols,
                                   hu=np.full((rows, cols), float(level)))
        (directory / f"s{index:03d}.dcm").write_bytes(payload)
    return directory


@pytest.fixture()
def samples(tmp_path, monkeypatch) -> Path:
    """Redirect the generator's output folder: the real backend/samples is never touched by a test."""
    target = tmp_path / "samples"
    monkeypatch.setattr(download_data, "SAMPLES_DIR", target)
    return target


def grey_values(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        assert image.mode == "L"                                         # an 8-bit greyscale image
        return np.asarray(image)


# --- what is written ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("index", range(5))
def test_the_requested_slice_is_windowed_to_exact_8_bit_grey_values(tmp_path, samples, index):
    series = write_series(tmp_path / "series", LEVELS_5)
    path = download_data.generate_chest_ct_sample(series, index)
    assert path == samples / "chest_ct.png"
    pixels = grey_values(path)
    assert pixels.shape == (16, 16) and pixels.dtype == np.uint8
    assert (pixels == EXPECTED_5[index]).all()                           # slice k holds one value, so a wrong slice would be seen at once


def test_values_outside_the_window_are_clipped_not_wrapped(tmp_path, samples):
    series = write_series(tmp_path / "series", [-2000.0, 1000.0])        # far below -1350 HU and far above 150 HU
    low = grey_values(download_data.generate_chest_ct_sample(series, 0))
    assert (low == 0).all()
    high = grey_values(download_data.generate_chest_ct_sample(series, 1, overwrite=True))
    assert (high == 255).all()


def test_the_default_slice_is_the_documented_fiftieth_zero_based(tmp_path, samples):
    assert download_data.CHEST_CT_SLICE == 50
    levels = [-1350.0 + 30.0 * k for k in range(52)]                     # slice 49 -> 250, slice 50 -> 255, slice 51 is above the window
    series = write_series(tmp_path / "series", levels, rows=4, cols=4)
    assert (grey_values(download_data.generate_chest_ct_sample(series)) == 255).all()


def test_the_png_carries_neither_dicom_identifiers_nor_text_metadata(tmp_path, samples):
    series = write_series(tmp_path / "series", LEVELS_5)
    path = download_data.generate_chest_ct_sample(series, 2)
    with Image.open(path) as image:
        assert not image.info                                            # no text chunk, no DPI, nothing copied from the header
    assert SERIES_A.encode() not in path.read_bytes()


# --- what is refused ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("index", [-1, 5, 50])
def test_a_slice_outside_the_series_is_refused_and_nothing_is_written(tmp_path, samples, index):
    series = write_series(tmp_path / "series", LEVELS_5)
    with pytest.raises(ValueError, match="outside the series"):
        download_data.generate_chest_ct_sample(series, index)
    assert not samples.exists()


def test_a_missing_folder_is_refused_and_nothing_is_written(tmp_path, samples):
    with pytest.raises(FileNotFoundError):
        download_data.generate_chest_ct_sample(tmp_path / "not-there")
    assert not samples.exists()


def test_a_folder_without_readable_dicom_is_refused_and_nothing_is_written(tmp_path, samples):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "README.txt").write_text("not an image")
    with pytest.raises(ValueError, match="No readable DICOM"):
        download_data.generate_chest_ct_sample(empty)
    assert not samples.exists()


def test_a_damaged_slice_is_an_error_not_a_shorter_series(tmp_path, samples):
    series = write_series(tmp_path / "series", LEVELS_5)
    (series / "s002.dcm").write_bytes(b"this is not a DICOM file")
    with pytest.raises(ValueError, match="Unreadable DICOM file"):
        download_data.generate_chest_ct_sample(series, 1)
    assert not samples.exists()


def test_a_folder_that_mixes_two_series_is_refused(tmp_path, samples):
    series = write_series(tmp_path / "series", LEVELS_5[:3])
    other = write_series(tmp_path / "other", LEVELS_5[:1], series_uid=SERIES_B)
    (series / "intruder.dcm").write_bytes(next(other.glob("*.dcm")).read_bytes())
    with pytest.raises(ValueError, match="exactly one DICOM SeriesInstanceUID"):
        download_data.generate_chest_ct_sample(series, 1)
    assert not samples.exists()


# --- the shipped file is protected ----------------------------------------------------------------------------------------------

def test_an_existing_sample_is_never_replaced_by_different_pixels(tmp_path, samples):
    first = write_series(tmp_path / "a", LEVELS_5)
    path = download_data.generate_chest_ct_sample(first, 3)
    before = path.read_bytes()
    different = write_series(tmp_path / "b", LEVELS_5[::-1], series_uid=SERIES_B)             # another series: slice 3 is now 51, not 153
    with pytest.raises(FileExistsError, match="--overwrite-chest-ct"):
        download_data.generate_chest_ct_sample(different, 3)
    assert path.read_bytes() == before


def test_identical_pixels_leave_the_existing_file_byte_for_byte_untouched(tmp_path, samples):
    series = write_series(tmp_path / "series", LEVELS_5)
    path = download_data.generate_chest_ct_sample(series, 3)
    Image.fromarray(grey_values(path)).save(path)                        # same pixels, different encoder settings (no optimize)
    bytes_before, mtime_before = path.read_bytes(), path.stat().st_mtime_ns
    assert download_data.generate_chest_ct_sample(series, 3) == path
    assert path.read_bytes() == bytes_before and path.stat().st_mtime_ns == mtime_before   # no spurious change that Git would show


def test_an_unreadable_existing_file_is_not_silently_replaced_either(tmp_path, samples):
    samples.mkdir()
    (samples / "chest_ct.png").write_bytes(b"corrupt")
    series = write_series(tmp_path / "series", LEVELS_5)
    with pytest.raises(FileExistsError):
        download_data.generate_chest_ct_sample(series, 1)
    assert (samples / "chest_ct.png").read_bytes() == b"corrupt"


def test_overwrite_replaces_the_sample_on_purpose(tmp_path, samples):
    first = write_series(tmp_path / "a", LEVELS_5)
    path = download_data.generate_chest_ct_sample(first, 3)
    assert (grey_values(path) == 153).all()
    different = write_series(tmp_path / "b", LEVELS_5[::-1], series_uid=SERIES_B)
    download_data.generate_chest_ct_sample(different, 3, overwrite=True)
    assert (grey_values(path) == 51).all()


# --- command line -----------------------------------------------------------------------------------------------------------------

OFFLINE = ["--skip-skimage", "--skip-synthetic-dicom", "--skip-dicom-test-files", "--skip-kaggle"]       # nothing is generated or downloaded except the sample


def run_cli(monkeypatch, capsys, *arguments: str) -> str:
    monkeypatch.setattr(sys, "argv", ["download_data.py", *OFFLINE, *arguments])
    download_data.main()
    return capsys.readouterr().out


LEVELS_52 = [-1350.0 + 30.0 * k for k in range(52)]                      # the command line always cuts slice 50, so the series needs 51 slices or more


def test_ct_series_writes_the_sample_and_reports_it(tmp_path, samples, monkeypatch, capsys):
    series = write_series(tmp_path / "series", LEVELS_52, rows=4, cols=4)
    output = run_cli(monkeypatch, capsys, "--ct-series", str(series))
    assert "ok chest_ct.png" in output and "chest_ct.png" in output.split("Contents of samples/")[1]
    assert (grey_values(samples / "chest_ct.png") == 255).all()          # slice 50 of this series


def test_a_series_shorter_than_the_documented_slice_is_reported_as_a_failure(tmp_path, samples, monkeypatch, capsys):
    series = write_series(tmp_path / "series", LEVELS_5)
    output = run_cli(monkeypatch, capsys, "--ct-series", str(series))
    assert "FAILED chest_ct.png skipped" in output and "outside the series (5 slices)" in output
    assert not (samples / "chest_ct.png").exists()


def test_without_ct_series_no_chest_sample_is_attempted(samples, monkeypatch, capsys):
    output = run_cli(monkeypatch, capsys)
    assert "chest CT slice" not in output and not (samples / "chest_ct.png").exists()


def test_the_command_line_reports_a_bad_series_and_writes_nothing(tmp_path, samples, monkeypatch, capsys):
    output = run_cli(monkeypatch, capsys, "--ct-series", str(tmp_path / "missing"))
    assert "FAILED chest_ct.png skipped" in output and "not found" in output
    assert not (samples / "chest_ct.png").exists()


def test_the_command_line_protects_the_sample_unless_overwrite_is_requested(tmp_path, samples, monkeypatch, capsys):
    first = write_series(tmp_path / "a", LEVELS_52, rows=4, cols=4)
    run_cli(monkeypatch, capsys, "--ct-series", str(first))
    different = write_series(tmp_path / "b", LEVELS_52[::-1], rows=4, cols=4, series_uid=SERIES_B)      # slice 50 is now 5, not 255
    protected = run_cli(monkeypatch, capsys, "--ct-series", str(different))
    assert "FAILED chest_ct.png skipped" in protected and "--overwrite-chest-ct" in protected
    assert (grey_values(samples / "chest_ct.png") == 255).all()          # still the first series
    replaced = run_cli(monkeypatch, capsys, "--ct-series", str(different), "--overwrite-chest-ct")
    assert "ok chest_ct.png" in replaced
    assert (grey_values(samples / "chest_ct.png") == 5).all()


# --- provenance of the file that ships with the repository -----------------------------------------------------------------------

def local_lidc_series() -> Path | None:
    base = ROOT / "backend" / "data" / "tcia" / "LIDC-IDRI-0709"
    candidates = [p for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
    return candidates[0] if len(candidates) == 1 else None


def test_the_shipped_sample_is_exactly_slice_50_of_the_local_series(tmp_path, samples):
    series = local_lidc_series()
    if series is None:
        pytest.skip("the local LIDC-IDRI-0709 series (not part of the repository) is not present")
    shipped = grey_values(ROOT / "backend" / "samples" / "chest_ct.png")
    regenerated = grey_values(download_data.generate_chest_ct_sample(series))                    # written to the temporary folder
    assert shipped.shape == (512, 512)
    assert np.array_equal(shipped, regenerated)
    neighbour = grey_values(download_data.generate_chest_ct_sample(series, 49, overwrite=True))
    assert not np.array_equal(shipped, neighbour)                        # the comparison can tell slice 50 from its neighbour
