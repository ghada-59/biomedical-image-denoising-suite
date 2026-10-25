"""Startup-facing behaviour of the API: what a person sees when opening it, and what happens in an environment that lacks a package.

These are real in-process requests against the real application (no mocks of the API itself); the only thing replaced is the
operating-system check for an installed package, to reproduce an environment without PyWavelets.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
import methods as M
from conftest import make_png_bytes

ALL_IDS = [m.id for m in M.METHODS]


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app, raise_server_exceptions=False)


@pytest.fixture
def without_pywavelets(monkeypatch):
    real = M.package_available
    monkeypatch.setattr(M, "package_available", lambda module: False if module == "pywt" else real(module))


def post(client, **fields):
    return client.post("/api/denoise", files={"file": ("s.png", make_png_bytes((64, 64)), "image/png")}, data={k: str(v) for k, v in fields.items()})


# --- opening the API address in a browser -------------------------------------------------------------


def test_the_api_root_explains_what_it_is_instead_of_answering_not_found(client):
    response = client.get("/")
    body = response.json()
    assert response.status_code == 200 and body["service"] == "Biomedical Imaging API"
    assert "not the dashboard" in body["message"] and "5173" in body["message"]
    for path in body["links"].values():
        assert client.get(path).status_code == 200, path          # every advertised link works


def test_the_interactive_documentation_and_the_schema_are_served(client):
    assert client.get("/docs").status_code == 200 and "swagger" in client.get("/docs").text.lower()
    schema = client.get("/openapi.json").json()
    for path in ("/api/health", "/api/methods", "/api/samples", "/api/denoise", "/api/image/preview", "/api/ct/volume", "/api/v2/runs"):
        assert path in schema["paths"], f"{path} is not registered"


def test_health_reports_the_version_and_no_problems_in_a_complete_environment(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["version"] == api.app.version and body["problems"] == [] and body["unavailable_methods"] == []


# --- an environment without PyWavelets (the Conda environment used earlier lacks it) --------------------------


def test_a_missing_package_is_reported_by_health_and_the_catalogue(client, without_pywavelets):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert [m["id"] for m in health["unavailable_methods"]] == ["wavelet"] and "PyWavelets" in health["problems"][0]
    catalogue = {m["id"]: m for m in client.get("/api/methods").json()["methods"]}
    assert catalogue["wavelet"]["available"] is False and "pip install" in catalogue["wavelet"]["unavailable_reason"]
    assert all(catalogue[i]["available"] and catalogue[i]["unavailable_reason"] is None for i in ALL_IDS if i != "wavelet")


def test_asking_for_an_unavailable_method_is_a_clear_422_not_an_internal_error(client, without_pywavelets):
    response = post(client, methods="wavelet")
    assert response.status_code == 422 and isinstance(response.json()["detail"], str)
    assert "PyWavelets" in response.json()["detail"] and "requirements-api.txt" in response.json()["detail"]
    assert "Traceback" not in response.text and ":\\" not in response.text and "site-packages" not in response.text     # no server path or stack trace


def test_the_other_methods_keep_working_without_pywavelets(client, without_pywavelets):
    response = post(client, methods="mean,median,nlm,bilateral")
    assert response.status_code == 200 and len(response.json()["results"]) == 5
    assert post(client).status_code == 200                                  # the default selection never includes the missing method


def test_the_default_selection_never_depends_on_an_optional_package():
    assert not any(M.BY_ID[i].requires for i in M.DEFAULT_METHOD_IDS)


def test_available_methods_report_no_reason_when_the_package_is_present():
    assert M.package_available("numpy") and not M.package_available("a_package_that_does_not_exist_anywhere")
    assert M.BY_ID["mean"].unavailable_reason() is None
