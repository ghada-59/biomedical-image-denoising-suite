"""Generates the contents of `samples/`, used by `app.py` for its
"Use a sample" selector.
"""

from __future__ import annotations

import argparse
import shutil
import urllib.request
from pathlib import Path

import numpy as np

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
KAGGLE_DATASET = "tawsifurrahman/covid19-radiography-database"
DEFAULT_IMAGES_PER_CLASS = 3

ORTHANC_SAMPLES = {
    "brain_mri_clinical.dcm": "https://raw.githubusercontent.com/pydicom/pydicom/main/src/pydicom/data/test_files/MR_small.dcm",
    "chest_ct_clinical.dcm": "https://raw.githubusercontent.com/pydicom/pydicom/main/src/pydicom/data/test_files/CT_small.dcm",
}


def generate_skimage_samples() -> None:
    """Saves sample images from scikit-image."""
    import matplotlib.pyplot as plt
    from skimage import data

    print("→ scikit-image samples…")
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    try:
        brain = data.brain()
        brain_img = brain[5] if brain.ndim == 3 else brain
        plt.imsave(SAMPLES_DIR / "brain_mri.png", brain_img, cmap="gray")
        print("  ✓ brain_mri.png")
    except Exception as exc:
        print(f"  ✗ brain_mri.png skipped ({exc})")

    try:
        cells = data.cell()
        if cells.ndim == 4:
            cells_img = cells[0, 0]
        elif cells.ndim == 3:
            cells_img = cells[0]
        else:
            cells_img = cells
        plt.imsave(SAMPLES_DIR / "cells_tissue.png", cells_img, cmap="gray")
        print("  ✓ cells_tissue.png")
    except Exception as exc:
        print(f"  ✗ cells_tissue.png skipped ({exc})")


def generate_synthetic_dicom() -> None:
    """Generates a synthetic DICOM (fictional abdominal CT scan), 100% local."""
    try:
        import pydicom
        from pydicom.dataset import FileDataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    except ImportError:
        print("→ Synthetic DICOM skipped: package `pydicom` is not installed.")
        return

    print("→ Synthetic DICOM (fictional abdominal CT scan)…")
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    size = 256
    yy, xx = np.mgrid[0:size, 0:size]
    r = np.sqrt((xx - size / 2) ** 2 + (yy - size / 2) ** 2)

    hu = np.full((size, size), -1000.0)
    hu[r < size * 0.4] = 40.0
    hu[r < size * 0.15] = 400.0
    hu += np.random.default_rng(0).normal(0, 15, size=(size, size))

    slope, intercept = 1.0, -1024.0
    stored_pixels = np.round((hu - intercept) / slope).astype(np.int16)

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    dcm_path = SAMPLES_DIR / "synthetic_ct_scan.dcm"
    ds = FileDataset(
        str(dcm_path),
        {},
        file_meta=file_meta,
        preamble=b"\x00" * 128,
        is_implicit_VR=False,
        is_little_endian=True,
    )

    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "CT"
    ds.PatientName = "Synthetic^Subject"
    ds.PatientID = "SYNTH-0001"
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()

    ds.Rows, ds.Columns = size, size
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1

    ds.RescaleSlope = slope
    ds.RescaleIntercept = intercept
    ds.WindowCenter = 40
    ds.WindowWidth = 400

    ds.PixelData = stored_pixels.tobytes()

    try:
        ds.save_as(dcm_path)
        print(f"  ✓ {dcm_path.name}")
    except Exception as exc:
        print(f"  ✗ {dcm_path.name} skipped ({exc})")


def download_orthanc_samples() -> None:
    """Downloads real lightweight clinical DICOM samples from Orthanc server."""
    print("→ Clinical DICOM samples (Orthanc)…")
    dicom_dir = SAMPLES_DIR / "clinical_dicom"
    dicom_dir.mkdir(parents=True, exist_ok=True)

    for filename, url in ORTHANC_SAMPLES.items():
        dest = dicom_dir / filename
        if dest.exists():
            print(f"  ✓ {filename} (already exists)")
            continue
        try:
            urllib.request.urlretrieve(url, dest)
            print(f"  ✓ {filename}")
        except Exception as exc:
            print(f"  ✗ {filename} failed ({exc})")


def download_kaggle_samples(n_per_class: int = DEFAULT_IMAGES_PER_CLASS) -> None:
    """Downloads a subset of the Kaggle COVID-19 Radiography Database dataset."""
    try:
        import kagglehub
    except ImportError:
        print("→ Kaggle dataset skipped: package `kagglehub` is not installed.")
        return

    print(f"→ Downloading '{KAGGLE_DATASET}'…")
    try:
        dataset_root = Path(kagglehub.dataset_download(KAGGLE_DATASET))
    except Exception as exc:
        print(f"  ✗ Kaggle download failed ({exc}).")
        return

    image_dirs = sorted(p for p in dataset_root.rglob("images") if p.is_dir())
    if not image_dirs:
        image_dirs = [dataset_root]

    dest_root = SAMPLES_DIR / "covid19_radiography"
    dest_root.mkdir(parents=True, exist_ok=True)
    total_copied = 0

    for img_dir in image_dirs:
        class_name = img_dir.parent.name if img_dir.name == "images" else img_dir.name
        class_slug = class_name.strip().replace(" ", "_")

        files = sorted(img_dir.glob("*.png")) or sorted(img_dir.glob("*.jpg"))
        chosen = files[:n_per_class]
        if not chosen:
            continue

        dest_dir = dest_root / class_slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src in chosen:
            shutil.copy2(src, dest_dir / src.name)
            total_copied += 1
        print(f"  ✓ {class_slug}: {len(chosen)} image(s)")

    if total_copied == 0:
        print("  ✗ No images found in downloaded archive.")
    else:
        print(f"  ✓ {total_copied} image(s) copied in total to {dest_root}/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generates samples/ for biomedical-image-denoising-suite.")
    parser.add_argument("--skip-skimage", action="store_true", help="Skip scikit-image samples.")
    parser.add_argument("--skip-synthetic-dicom", action="store_true", help="Skip synthetic DICOM.")
    parser.add_argument("--skip-orthanc", action="store_true", help="Skip real Orthanc clinical DICOMs.")
    parser.add_argument("--skip-kaggle", action="store_true", help="Skip Kaggle dataset download.")
    parser.add_argument(
        "--kaggle-per-class",
        type=int,
        default=DEFAULT_IMAGES_PER_CLASS,
        help="Number of images to keep per class.",
    )
    args = parser.parse_args()

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating samples in {SAMPLES_DIR}/\n")

    if not args.skip_skimage:
        generate_skimage_samples()
    if not args.skip_synthetic_dicom:
        generate_synthetic_dicom()
    if not args.skip_orthanc:
        download_orthanc_samples()
    if not args.skip_kaggle:
        download_kaggle_samples(n_per_class=args.kaggle_per_class)

    print("\nDone. Contents of samples/:")
    found_any = False
    for path in sorted(SAMPLES_DIR.rglob("*")):
        if path.is_file():
            print(f"  {path.relative_to(SAMPLES_DIR)}")
            found_any = True
    if not found_any:
        print("  (empty — all sources failed or were skipped)")


if __name__ == "__main__":
    main()