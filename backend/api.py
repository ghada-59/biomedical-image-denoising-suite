"""FastAPI endpoints for the React biomedical imaging dashboard."""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import pandas as pd
import pydicom
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image

from filters import (
    NOISE_TYPES,
    add_noise,
    apply_frequency_lowpass,
    apply_spatial_filters,
    calculate_metrics,
    load_medical_image,
)
from provenance import results_provenance
from src.dicom_volume import load_dicom_volume
from src.plotly_ct_viewer import create_ct_volume_figure

logger = logging.getLogger("biomedical_api")

ROOT = Path(__file__).resolve().parent


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


# Resource limits (override with environment variables). They bound memory and CPU use:
# every request decodes the image and runs seven filters, each on a float64 copy.
MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_MB", 25) * 1024 * 1024
MAX_IMAGE_PIXELS = _env_int("MAX_IMAGE_PIXELS", 2048 * 2048)
MAX_CT_FILES = _env_int("MAX_CT_FILES", 400)
MAX_CT_TOTAL_BYTES = _env_int("MAX_CT_TOTAL_MB", 200) * 1024 * 1024

NoiseChoice = Literal["None", "Gaussian", "Salt & Pepper", "Speckle (synthetic)"]

app = FastAPI(title="Biomedical Imaging API", version="1.0.0")


def _cors_origins() -> list[str]:
    origins = {"http://127.0.0.1:5173", "http://localhost:5173"}
    for value in os.getenv("CORS_ORIGINS", "").split(","):
        origin = value.strip().rstrip("/")
        if not origin:
            continue
        if not origin.startswith(("http://", "https://")):
            origin = f"https://{origin}"
        origins.add(origin)
    return sorted(origins)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    """Return validation problems as one readable string.

    FastAPI's default ``detail`` is a list of objects, which the dashboard would show
    as "[object Object]". Submitted values are deliberately not echoed back.
    """
    problems = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ()) if part not in ("body", "query")]
        problems.append(f"{'.'.join(location) or 'request'}: {error.get('msg', 'invalid value')}")
    return JSONResponse(status_code=422, content={"detail": "Invalid request. " + "; ".join(problems)})


def _png_data_url(image: np.ndarray) -> str:
    array = np.asarray(image)
    if array.ndim != 2 or array.size == 0:
        raise ValueError("Expected a non-empty grayscale image.")
    if np.issubdtype(array.dtype, np.floating):
        array = np.clip(array, 0, 1)
        array = (array * 255).round().astype(np.uint8)
    else:
        array = np.clip(array, 0, 255).astype(np.uint8)
    ok, encoded = cv2.imencode(".png", array)
    if not ok:
        raise ValueError("Could not encode the preview image.")
    return "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


def _mb(limit_bytes: int) -> str:
    return f"{limit_bytes / (1024 * 1024):g} MB"


def _read_upload(upload: UploadFile, limit: int | None = None) -> bytes:
    """Read an upload without ever holding more than ``limit`` + 1 bytes."""
    limit = MAX_UPLOAD_BYTES if limit is None else limit
    name = Path(upload.filename or "file").name
    payload = upload.file.read(limit + 1)
    if not payload:
        raise HTTPException(status_code=400, detail=f"{name} is empty.")
    if len(payload) > limit:
        raise HTTPException(status_code=413, detail=f"{name} exceeds the {_mb(limit)} upload limit.")
    return payload


def _scrub(message: str, *hidden: str) -> str:
    """Remove server-side paths and object reprs from a message shown to clients."""
    for text in hidden:
        if text:
            message = message.replace(text, "<upload>")
    return re.sub(r"<[^<>]*object at 0x[0-9a-fA-F]+>", "the uploaded file", message)


def _declared_pixels(filename: str, payload: bytes) -> int | None:
    """Pixel count taken from the file header, before any full decode (None if unknown)."""
    try:
        if filename.lower().endswith(".dcm"):
            header = pydicom.dcmread(io.BytesIO(payload), stop_before_pixels=True)
            return int(header.Rows) * int(header.Columns)
        with Image.open(io.BytesIO(payload)) as image:
            return int(image.size[0]) * int(image.size[1])
    except Exception:
        return None


def _check_pixel_limit(pixels: int | None, name: str) -> None:
    if pixels is not None and pixels > MAX_IMAGE_PIXELS:
        raise HTTPException(
            status_code=413,
            detail=f"{name} has {pixels:,} pixels; the limit is {MAX_IMAGE_PIXELS:,}.",
        )


class _NamedBytes(io.BytesIO):
    """BytesIO carrying a file name, so DICOM files are recognised by extension."""

    def __init__(self, payload: bytes, name: str):
        super().__init__(payload)
        self.name = name


def _decode_image(filename: str, payload: bytes) -> np.ndarray:
    name = Path(filename).name
    _check_pixel_limit(_declared_pixels(name, payload), name)
    try:
        source = _NamedBytes(payload, name) if name.lower().endswith(".dcm") else io.BytesIO(payload)
        image = load_medical_image(source)
    except Exception as exc:
        logger.info("Could not decode %s: %s", name, exc)
        raise HTTPException(status_code=400, detail=f"Could not read {name}: {_scrub(str(exc))}") from exc
    _check_pixel_limit(int(image.size), name)
    return image


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "Biomedical Imaging API"}


@app.get("/api/results")
def results():
    # Serve the runtime report only, never docs/results. Whether it is a documented run
    # or an unverified historical file is reported in ``provenance``.
    summary = ROOT / "reports" / "denoising_summary.csv"
    if not summary.is_file():
        return {"available": False, "source": None, "rows": [], "noise_types": list(NOISE_TYPES), "provenance": None}
    try:
        frame = pd.read_csv(summary).replace({np.nan: None})
        rows = frame.to_dict(orient="records")
        return {
            "available": bool(rows),
            "source": summary.relative_to(ROOT).as_posix(),
            "provenance": results_provenance(summary.parent),
            "rows": rows,
            "noise_types": sorted(str(v) for v in frame["Noise"].dropna().unique()) if "Noise" in frame else [],
        }
    except Exception as exc:
        logger.exception("Could not read %s", summary)
        raise HTTPException(status_code=500, detail="Could not read the benchmark results file.") from exc


@app.post("/api/image/preview")
def image_preview(file: UploadFile = File(...)):
    payload = _read_upload(file)
    image = _decode_image(file.filename or "upload", payload)
    height, width = image.shape
    return {
        "filename": file.filename or "upload",
        "width": int(width),
        "height": int(height),
        "preview": _png_data_url(image),
        "format": "DICOM" if (file.filename or "").lower().endswith(".dcm") else "grayscale image",
    }


# These endpoints are plain ``def`` on purpose: they are CPU-bound, so FastAPI runs them
# in its worker thread pool instead of blocking the event loop.
@app.post("/api/denoise")
def denoise(
    file: UploadFile = File(...),
    noise_type: NoiseChoice = Form("Gaussian"),
    noise_amount: float = Form(0.02, ge=0.0, le=1.0),
    noise_variance: float = Form(0.02, ge=0.0, le=1.0),
    seed: int = Form(42, ge=0, le=2**32 - 1),
    kernel_size: int = Form(5, ge=1, le=51),
    sigma: float = Form(0.0, ge=0.0, le=50.0),
    cutoff_ratio: float = Form(0.15, gt=0.0, lt=1.0),
):
    payload = _read_upload(file)
    clean = _decode_image(file.filename or "upload", payload)
    try:
        if noise_type == "None":
            noisy = clean.copy()
        else:
            noisy = add_noise(clean, noise_type, amount=noise_amount, var=noise_variance, seed=seed)
        mean_img, median_img, gaussian_img = apply_spatial_filters(noisy, kernel_size=kernel_size, sigma=sigma)
        freq_results = {}
        for method in ("ideal", "gauss", "butterworth"):
            filtered, _, _ = apply_frequency_lowpass(noisy, cutoff_ratio=cutoff_ratio, filter_type=method)
            freq_results[method] = filtered

        outputs = {
            "Noisy input": noisy,
            "Mean": mean_img,
            "Median": median_img,
            "Gaussian": gaussian_img,
            "Frequency ideal": freq_results["ideal"],
            "Frequency Gaussian": freq_results["gauss"],
            "Frequency Butterworth": freq_results["butterworth"],
        }
        results_rows = []
        images = {}
        for label, output in outputs.items():
            psnr, ssim = calculate_metrics(clean, output)
            results_rows.append({
                "Filter": label,
                "PSNR (dB)": "∞" if np.isinf(psnr) else round(float(psnr), 3),
                "SSIM": round(float(ssim), 4),
            })
            images[label] = _png_data_url(output)
    except ValueError as exc:
        # Parameter and image checks in filters.py raise ValueError with curated messages.
        logger.info("Rejected /api/denoise request: %s", exc)
        raise HTTPException(status_code=422, detail=_scrub(str(exc))) from exc
    return {
        "filename": file.filename or "upload",
        "width": int(clean.shape[1]),
        "height": int(clean.shape[0]),
        "noise_type": noise_type,
        "images": images,
        "results": results_rows,
        "note": (
            "Metrics compare outputs with the original image before synthetic noise was added."
            if noise_type != "None"
            else "No synthetic noise was added. Metrics measure similarity to the input image, not ground-truth denoising accuracy."
        ),
    }


def _require_valid_dicom_slice(name: str, payload: bytes) -> None:
    """Reject an uploaded file that is not a readable DICOM slice.

    ``load_dicom_volume`` silently skips unreadable files, which is right when scanning a
    folder that also holds README or index files, but wrong for an explicit upload: a
    dropped corrupt slice would yield a volume with a wrong slice gap and no warning.
    """
    try:
        header = pydicom.dcmread(io.BytesIO(payload), stop_before_pixels=True)
        valid = hasattr(header, "SOPInstanceUID") and hasattr(header, "SeriesInstanceUID")
    except Exception:
        valid = False
    if not valid:
        raise HTTPException(status_code=400, detail=f"{name} is not a readable DICOM slice.")


@app.post("/api/ct/volume")
def ct_volume(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="Select all slices from one DICOM series.")
    if len(files) < 2:
        raise HTTPException(
            status_code=400,
            detail="Only one DICOM slice was selected. Its 2D preview is available in the Image Lab, but 3D reconstruction requires multiple slices from one series.",
        )
    if len(files) > MAX_CT_FILES:
        raise HTTPException(status_code=413, detail=f"At most {MAX_CT_FILES} slices can be uploaded at once.")
    payloads = []
    total_bytes = 0
    for upload in files:
        name = Path(upload.filename or "slice.dcm").name
        if not name.lower().endswith(".dcm"):
            raise HTTPException(status_code=400, detail=f"{name} is not a .dcm file.")
        payload = _read_upload(upload)
        total_bytes += len(payload)
        if total_bytes > MAX_CT_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail=f"The series exceeds the {_mb(MAX_CT_TOTAL_BYTES)} total upload limit.")
        _require_valid_dicom_slice(name, payload)
        payloads.append((name, payload))
    temp_name = ""
    try:
        with tempfile.TemporaryDirectory(prefix="biomed-ct-") as temp_dir:
            temp_name = temp_dir
            temp_path = Path(temp_dir)
            for index, (name, payload) in enumerate(payloads):
                (temp_path / f"{index:05d}_{name}").write_bytes(payload)
            volume, spacing, origin, direction = load_dicom_volume(temp_path)
        sample_step = max(1, int(np.ceil(max(volume.shape) / 48)))
        sample = volume[::sample_step, ::sample_step, ::sample_step]
        low = float(np.percentile(sample, 1))
        high = float(np.percentile(sample, 99))
        if high <= low:
            low, high = float(np.min(volume)), float(np.max(volume))
        if high <= low:
            raise ValueError("The selected CT volume has no intensity variation.")
        intensity_min = max(low, -1000.0)
        intensity_max = min(high, 400.0)
        if intensity_max <= intensity_min:
            intensity_min, intensity_max = low, high
        figure = create_ct_volume_figure(
            volume=volume,
            spacing_xyz_mm=spacing,
            origin_xyz_mm=origin,
            direction_matrix=direction,
            intensity_min=intensity_min,
            intensity_max=intensity_max,
        )
        middle_slice = volume[volume.shape[0] // 2]
        normalized = np.clip((middle_slice - intensity_min) / (intensity_max - intensity_min), 0, 1)
        return {
            "filename_count": len(payloads),
            "slices": int(volume.shape[0]),
            "dimensions_xyz": [int(volume.shape[2]), int(volume.shape[1]), int(volume.shape[0])],
            "spacing_xyz_mm": [round(float(v), 3) for v in spacing],
            "intensity_range": [round(intensity_min, 2), round(intensity_max, 2)],
            "middle_slice": _png_data_url(normalized),
            "figure": json.loads(figure.to_json()),
            "note": "Research and educational visualization only; not for diagnosis.",
        }
    except Exception as exc:
        logger.warning("CT reconstruction failed: %s", exc)
        reason = _scrub(str(exc), temp_name) if isinstance(exc, ValueError) else "unexpected processing error"
        raise HTTPException(
            status_code=400,
            detail=f"Could not reconstruct this CT series. Select all slices from one consistent series. Details: {reason}",
        ) from exc
