"""Behavioural tests for the FastAPI service (no network, in-process TestClient)."""

from __future__ import annotations

import re

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api

EXPECTED_FILTERS = [
    "Noisy input",
    "Mean",
    "Median",
    "Gaussian",
    "Frequency ideal",
    "Frequency Gaussian",
    "Frequency Butterworth",
]
DATA_URL = re.compile(r"^data:image/png;base64,[A-Za-z0-9+/=]+$")


@pytest.fixture
def client() -> TestClient:
    # raise_server_exceptions=False reproduces what a real client sees: an HTTP 500
    # response instead of an exception propagating into the test.
    return TestClient(api.app, raise_server_exceptions=False)


def _post_denoise(client, png_bytes, **fields):
    data = {key: str(value) for key, value in fields.items()}
    return client.post("/api/denoise", files={"file": ("slice.png", png_bytes, "image/png")}, data=data)


def _assert_detail_is_text(response):
    """The React client does ``new Error(payload.detail)``, so detail must be a string."""
    assert isinstance(response.json()["detail"], str)


# --- health and results ---------------------------------------------------------------


def test_health_reports_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Biomedical Imaging API"}


def test_results_unavailable_when_no_report_exists(client, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "ROOT", tmp_path)
    body = client.get("/api/results").json()
    assert body["available"] is False
    assert body["rows"] == []
    assert body["source"] is None


def test_results_serves_generated_summary_and_converts_nan_to_null(client, tmp_path, monkeypatch):
    (tmp_path / "reports").mkdir()
    pd.DataFrame(
        {"Noise": ["Gaussian", "Salt & Pepper"], "Filter": ["Mean", "Median"], "Mean_PSNR_dB": [25.0, float("nan")]}
    ).to_csv(tmp_path / "reports" / "denoising_summary.csv", index=False)
    monkeypatch.setattr(api, "ROOT", tmp_path)

    response = client.get("/api/results")
    body = response.json()
    assert response.status_code == 200
    assert body["available"] is True
    assert body["source"] == "reports/denoising_summary.csv"
    assert body["noise_types"] == ["Gaussian", "Salt & Pepper"]
    assert body["rows"][1]["Mean_PSNR_dB"] is None


def test_results_unreadable_csv_returns_500_without_leaking_paths(client, tmp_path, monkeypatch):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "denoising_summary.csv").write_bytes(b"")
    monkeypatch.setattr(api, "ROOT", tmp_path)

    response = client.get("/api/results")
    assert response.status_code == 500
    _assert_detail_is_text(response)
    assert str(tmp_path) not in response.text


# --- /api/image/preview -----------------------------------------------------------------


def test_preview_returns_dimensions_and_png_data_url(client, png_bytes):
    response = client.post("/api/image/preview", files={"file": ("slice.png", png_bytes, "image/png")})
    body = response.json()
    assert response.status_code == 200
    assert (body["width"], body["height"]) == (64, 64)
    assert body["format"] == "grayscale image"
    assert DATA_URL.match(body["preview"])


def test_preview_accepts_dicom(client, dicom_series_bytes):
    name, payload = dicom_series_bytes(1)[0]
    response = client.post("/api/image/preview", files={"file": (name, payload, "application/dicom")})
    assert response.status_code == 200
    assert response.json()["format"] == "DICOM"


def test_preview_without_file_is_a_client_error(client):
    response = client.post("/api/image/preview")
    assert response.status_code == 422
    _assert_detail_is_text(response)


def test_preview_empty_file_is_400(client):
    response = client.post("/api/image/preview", files={"file": ("empty.png", b"", "image/png")})
    assert response.status_code == 400
    _assert_detail_is_text(response)


@pytest.mark.parametrize("filename", ["broken.png", "broken.dcm"])
def test_preview_corrupt_file_is_400(client, filename):
    response = client.post("/api/image/preview", files={"file": (filename, b"not an image at all", "application/octet-stream")})
    assert response.status_code == 400
    _assert_detail_is_text(response)


# --- /api/denoise: valid requests -------------------------------------------------------


def test_denoise_returns_all_filters_with_metrics_and_images(client, png_bytes):
    response = _post_denoise(client, png_bytes, noise_type="Gaussian", seed=7)
    body = response.json()
    assert response.status_code == 200
    assert [row["Filter"] for row in body["results"]] == EXPECTED_FILTERS
    assert set(body["images"]) == set(EXPECTED_FILTERS)
    assert all(DATA_URL.match(url) for url in body["images"].values())
    assert all(isinstance(row["SSIM"], float) and 0.0 <= row["SSIM"] <= 1.0 for row in body["results"])
    assert (body["width"], body["height"]) == (64, 64)
    assert "before synthetic noise" in body["note"]


def test_denoise_is_reproducible_for_a_fixed_seed(client, png_bytes):
    first = _post_denoise(client, png_bytes, noise_type="Gaussian", seed=11).json()
    second = _post_denoise(client, png_bytes, noise_type="Gaussian", seed=11).json()
    other = _post_denoise(client, png_bytes, noise_type="Gaussian", seed=12).json()
    assert first["results"] == second["results"]
    assert first["images"] == second["images"]
    assert first["results"] != other["results"]


def test_denoise_without_noise_labels_metrics_as_similarity_to_input(client, png_bytes):
    body = _post_denoise(client, png_bytes, noise_type="None").json()
    assert "No synthetic noise was added" in body["note"]
    assert body["results"][0]["PSNR (dB)"] == "∞"


@pytest.mark.parametrize("noise_type", ["Gaussian", "Salt & Pepper", "Speckle (synthetic)"])
def test_denoise_supports_every_noise_model(client, png_bytes, noise_type):
    assert _post_denoise(client, png_bytes, noise_type=noise_type).status_code == 200


# --- /api/denoise: invalid parameters ---------------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("noise_type", "Poisson"),
        ("noise_amount", -0.1),
        ("noise_amount", 1.5),
        ("noise_amount", "nan"),
        ("noise_variance", -1),
        ("noise_variance", "inf"),
        ("seed", -1),
        ("kernel_size", 0),
        ("kernel_size", -3),
        ("kernel_size", 1001),
        ("sigma", -0.5),
        ("sigma", "nan"),
        ("cutoff_ratio", 0),
        ("cutoff_ratio", 1.0),
        ("cutoff_ratio", -0.2),
        ("cutoff_ratio", "nan"),
    ],
)
def test_denoise_rejects_invalid_parameters_with_422(client, png_bytes, field, value):
    response = _post_denoise(client, png_bytes, **{field: value})
    assert response.status_code == 422, response.text
    _assert_detail_is_text(response)
    assert field in response.json()["detail"]


def test_denoise_missing_file_is_422(client):
    response = client.post("/api/denoise", data={"noise_type": "Gaussian"})
    assert response.status_code == 422
    _assert_detail_is_text(response)


def test_denoise_empty_and_corrupt_files_are_400(client):
    for payload in (b"", b"garbage"):
        response = client.post("/api/denoise", files={"file": ("x.png", payload, "image/png")})
        assert response.status_code == 400
        _assert_detail_is_text(response)


# --- /api/denoise: resource limits ------------------------------------------------------


def test_denoise_rejects_oversized_upload_with_413(client, png_bytes, monkeypatch):
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 100)
    response = _post_denoise(client, png_bytes)
    assert response.status_code == 413
    _assert_detail_is_text(response)


def test_denoise_rejects_images_over_the_pixel_limit(client, png_bytes, monkeypatch):
    monkeypatch.setattr(api, "MAX_IMAGE_PIXELS", 64 * 64 - 1)
    response = _post_denoise(client, png_bytes)
    assert response.status_code == 413
    _assert_detail_is_text(response)


def test_preview_enforces_the_same_limits(client, png_bytes, monkeypatch):
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 100)
    response = client.post("/api/image/preview", files={"file": ("slice.png", png_bytes, "image/png")})
    assert response.status_code == 413


# --- /api/ct/volume ---------------------------------------------------------------------


def _post_volume(client, series):
    return client.post("/api/ct/volume", files=[("files", (name, payload, "application/dicom")) for name, payload in series])


def test_ct_volume_builds_figure_for_a_valid_series(client, dicom_series_bytes):
    response = _post_volume(client, dicom_series_bytes(4))
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["slices"] == 4
    assert body["dimensions_xyz"] == [16, 16, 4]
    assert body["spacing_xyz_mm"] == [0.8, 0.8, 2.0]
    assert DATA_URL.match(body["middle_slice"])
    assert "data" in body["figure"]
    assert "not for diagnosis" in body["note"]


def test_ct_volume_single_slice_is_400(client, dicom_series_bytes):
    response = _post_volume(client, dicom_series_bytes(1))
    assert response.status_code == 400
    _assert_detail_is_text(response)


def test_ct_volume_rejects_non_dicom_extension(client, dicom_series_bytes):
    series = dicom_series_bytes(2)
    series[1] = ("notes.txt", series[1][1])
    response = _post_volume(client, series)
    assert response.status_code == 400


def test_ct_volume_rejects_mixed_series_without_leaking_server_paths(client, dicom_series_bytes):
    mixed = dicom_series_bytes(2, series_uid="1.2.3.4.1") + dicom_series_bytes(2, series_uid="1.2.3.4.2")
    mixed = [(f"{i}_{name}", payload) for i, (name, payload) in enumerate(mixed)]
    response = _post_volume(client, mixed)
    assert response.status_code == 400
    _assert_detail_is_text(response)
    assert "biomed-ct-" not in response.text
    assert "Temp" not in response.text and "tmp" not in response.text.lower()


def test_ct_volume_corrupt_slice_is_400_without_leaking_server_paths(client, dicom_series_bytes):
    series = dicom_series_bytes(3)
    series[1] = (series[1][0], b"this is not a dicom file")
    response = _post_volume(client, series)
    assert response.status_code == 400
    assert "biomed-ct-" not in response.text


def test_ct_volume_enforces_file_count_limit(client, dicom_series_bytes, monkeypatch):
    monkeypatch.setattr(api, "MAX_CT_FILES", 2)
    response = _post_volume(client, dicom_series_bytes(3))
    assert response.status_code == 413
    _assert_detail_is_text(response)


def test_ct_volume_enforces_total_size_limit(client, dicom_series_bytes, monkeypatch):
    monkeypatch.setattr(api, "MAX_CT_TOTAL_BYTES", 1000)
    response = _post_volume(client, dicom_series_bytes(3))
    assert response.status_code == 413
