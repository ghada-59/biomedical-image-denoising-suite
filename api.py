"""FastAPI endpoints for the React biomedical imaging dashboard."""
from __future__ import annotations

import base64
import io
import json
import os
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from filters import (
    NOISE_TYPES,
    add_noise,
    apply_frequency_lowpass,
    apply_spatial_filters,
    calculate_metrics,
    load_medical_image,
)
from src.dicom_volume import load_dicom_volume
from src.plotly_ct_viewer import create_ct_volume_figure

ROOT = Path(__file__).resolve().parent
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


async def _read_upload(upload: UploadFile) -> bytes:
    payload = await upload.read()
    if not payload:
        raise HTTPException(status_code=400, detail=f"{upload.filename or 'File'} is empty.")
    return payload


def _decode_image(filename: str, payload: bytes) -> np.ndarray:
    try:
        return load_medical_image(io.BytesIO(payload) if not filename.lower().endswith(".dcm") else _NamedBytes(payload, filename))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read {filename}: {exc}") from exc


class _NamedBytes(io.BytesIO):
    def __init__(self, payload: bytes, name: str):
        super().__init__(payload)
        self.name = name


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "Biomedical Imaging API"}


@app.get("/api/results")
def results():
    candidates = [
        ROOT / "reports" / "denoising_summary.csv",
        ROOT / "docs" / "results" / "denoising_summary.csv",
    ]
    summary = next((path for path in candidates if path.is_file()), None)
    if summary is None:
        return {"available": False, "source": None, "rows": [], "noise_types": list(NOISE_TYPES)}
    try:
        frame = pd.read_csv(summary).replace({np.nan: None})
        rows = frame.to_dict(orient="records")
        return {
            "available": bool(rows),
            "source": summary.relative_to(ROOT).as_posix(),
            "rows": rows,
            "noise_types": sorted(str(v) for v in frame["Noise"].dropna().unique()) if "Noise" in frame else [],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read benchmark results: {exc}") from exc


@app.post("/api/image/preview")
async def image_preview(file: UploadFile = File(...)):
    payload = await _read_upload(file)
    image = _decode_image(file.filename or "upload", payload)
    height, width = image.shape
    return {
        "filename": file.filename or "upload",
        "width": int(width),
        "height": int(height),
        "preview": _png_data_url(image),
        "format": "DICOM" if (file.filename or "").lower().endswith(".dcm") else "grayscale image",
    }


@app.post("/api/denoise")
async def denoise(
    file: UploadFile = File(...),
    noise_type: str = Form("Gaussian"),
    noise_amount: float = Form(0.02),
    noise_variance: float = Form(0.02),
    seed: int = Form(42),
    kernel_size: int = Form(5),
    sigma: float = Form(0.0),
    cutoff_ratio: float = Form(0.15),
):
    payload = await _read_upload(file)
    clean = _decode_image(file.filename or "upload", payload)
    rng_seed = int(seed)
    if noise_type == "None":
        noisy = clean.copy()
    else:
        noisy = add_noise(
            clean,
            noise_type,
            amount=float(noise_amount),
            var=float(noise_variance),
            seed=rng_seed,
        )
    mean_img, median_img, gaussian_img = apply_spatial_filters(
        noisy, kernel_size=int(kernel_size), sigma=float(sigma)
    )
    freq_results = {}
    for method in ("ideal", "gauss", "butterworth"):
        filtered, _, _ = apply_frequency_lowpass(
            noisy, cutoff_ratio=float(cutoff_ratio), filter_type=method
        )
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


@app.post("/api/ct/volume")
async def ct_volume(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="Select all slices from one DICOM series.")
    if len(files) < 2:
        raise HTTPException(
            status_code=400,
            detail="Only one DICOM slice was selected. Its 2D preview is available in the Image Lab, but 3D reconstruction requires multiple slices from one series.",
        )
    payloads = []
    for upload in files:
        name = Path(upload.filename or "slice.dcm").name
        if not name.lower().endswith(".dcm"):
            raise HTTPException(status_code=400, detail=f"{name} is not a .dcm file.")
        payloads.append((name, await _read_upload(upload)))
    try:
        with tempfile.TemporaryDirectory(prefix="biomed-ct-") as temp_dir:
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
        raise HTTPException(
            status_code=400,
            detail=f"Could not reconstruct this CT series. Select all slices from one consistent series. Details: {exc}",
        ) from exc
