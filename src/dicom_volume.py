from pathlib import Path
from typing import List, Tuple

import numpy as np
import pydicom


def discover_dicom_files(series_dir: str | Path) -> List[Path]:
    series_path = Path(series_dir)

    if not series_path.exists():
        raise FileNotFoundError(
            f"DICOM series directory not found: {series_path}"
        )

    if not series_path.is_dir():
        raise ValueError(
            f"Expected a directory, got: {series_path}"
        )

    files = []

    for path in series_path.rglob("*"):
        if not path.is_file():
            continue

        try:
            dataset = pydicom.dcmread(
                path,
                stop_before_pixels=True
            )

            if hasattr(dataset, "SOPInstanceUID"):
                files.append(path)

        except Exception:
            continue

    if not files:
        raise ValueError(
            f"No valid DICOM files found in: {series_path}"
        )

    return files


def sort_dicom_slices(files: List[Path]) -> List[Path]:
    slice_information = []

    for path in files:
        dataset = pydicom.dcmread(
            path,
            stop_before_pixels=True
        )

        if hasattr(dataset, "ImagePositionPatient"):
            position = dataset.ImagePositionPatient

            if len(position) < 3:
                raise ValueError(
                    f"Invalid ImagePositionPatient in: {path}"
                )

            z_position = float(position[2])

        elif hasattr(dataset, "SliceLocation"):
            z_position = float(dataset.SliceLocation)

        else:
            raise ValueError(
                f"No slice position found in: {path}"
            )

        slice_information.append((z_position, path))

    slice_information.sort(key=lambda item: item[0])

    return [path for _, path in slice_information]


def load_dicom_volume(
    series_dir: str | Path,
) -> Tuple[
    np.ndarray,
    Tuple[float, float, float],
    Tuple[float, float, float],
]:
    files = discover_dicom_files(series_dir)
    files = sort_dicom_slices(files)

    datasets = [
        pydicom.dcmread(path)
        for path in files
    ]

    first = datasets[0]

    rows = int(first.Rows)
    columns = int(first.Columns)

    for dataset in datasets:
        if (
            int(dataset.Rows) != rows
            or int(dataset.Columns) != columns
        ):
            raise ValueError(
                "Inconsistent image dimensions in DICOM series."
            )

    slices = []

    for dataset in datasets:
        pixel_array = dataset.pixel_array

        if pixel_array.ndim != 2:
            raise ValueError(
                "Expected single-frame 2D DICOM slices."
            )

        slices.append(pixel_array)

    volume = np.stack(slices, axis=0)

    pixel_spacing = first.PixelSpacing

    spacing_y = float(pixel_spacing[0])
    spacing_x = float(pixel_spacing[1])

    z_positions = np.array(
        [
            float(dataset.ImagePositionPatient[2])
            for dataset in datasets
        ],
        dtype=np.float64,
    )

    if len(z_positions) > 1:
        spacing_z = float(
            np.median(np.abs(np.diff(z_positions)))
        )
    elif hasattr(first, "SliceThickness"):
        spacing_z = float(first.SliceThickness)
    else:
        raise ValueError(
            "Cannot determine slice spacing."
        )

    spacing = (spacing_x, spacing_y, spacing_z)

    position = first.ImagePositionPatient

    origin = (
        float(position[0]),
        float(position[1]),
        float(position[2]),
    )

    return volume, spacing, origin


if __name__ == "__main__":
    print("DICOM volume module loaded successfully.")