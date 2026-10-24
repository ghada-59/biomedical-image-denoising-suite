"""Provenance labelling of benchmark results (module and /api/results)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import provenance

HISTORICAL = provenance.HISTORICAL_LABEL


def _write_summary(reports: Path) -> Path:
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / provenance.SUMMARY_NAME
    pd.DataFrame({"Noise": ["Gaussian"], "Filter": ["Mean"], "Mean_PSNR_dB": [25.0]}).to_csv(path, index=False)
    return path


def _metadata(summary: Path, **overrides) -> dict:
    data = {
        "schema_version": 1,
        "generated_at": "2026-10-24T12:00:00+00:00",
        "git_commit": "abc1234",
        "parameters": {"cutoff_ratio": 0.15, "seed": 42},
        "summary_sha256": provenance.sha256_of(summary),
    }
    data.update(overrides)
    return data


def _write_metadata(reports: Path, data) -> None:
    (reports / provenance.METADATA_NAME).write_text(json.dumps(data), encoding="utf-8")


def test_results_without_metadata_are_labelled_historical(tmp_path):
    _write_summary(tmp_path)
    status = provenance.results_provenance(tmp_path)
    assert status["status"] == "historical_unverified"
    assert status["label"] == HISTORICAL == "Historical results — provenance and currency not verified"
    assert status["metadata"] is None
    assert provenance.METADATA_NAME in status["reason"]


def test_matching_metadata_marks_a_documented_run(tmp_path):
    summary = _write_summary(tmp_path)
    _write_metadata(tmp_path, _metadata(summary))
    status = provenance.results_provenance(tmp_path)
    assert status["status"] == "documented_run"
    assert status["metadata"] == {
        "generated_at": "2026-10-24T12:00:00+00:00", "git_commit": "abc1234",
        "parameters": {"cutoff_ratio": 0.15, "seed": 42},
    }


def test_metadata_for_a_different_file_does_not_validate_the_results(tmp_path):
    summary = _write_summary(tmp_path)
    _write_metadata(tmp_path, _metadata(summary, summary_sha256="0" * 64))
    status = provenance.results_provenance(tmp_path)
    assert status["status"] == "historical_unverified"
    assert "does not match" in status["reason"]


def test_replacing_the_csv_after_the_run_invalidates_the_metadata(tmp_path):
    summary = _write_summary(tmp_path)
    _write_metadata(tmp_path, _metadata(summary))
    summary.write_text(summary.read_text(encoding="utf-8") + "Gaussian,Median,26.0\n", encoding="utf-8")
    assert provenance.results_provenance(tmp_path)["status"] == "historical_unverified"


@pytest.mark.parametrize("missing", ["schema_version", "generated_at", "git_commit", "parameters", "summary_sha256"])
def test_incomplete_metadata_is_not_trusted(tmp_path, missing):
    summary = _write_summary(tmp_path)
    data = _metadata(summary)
    del data[missing]
    _write_metadata(tmp_path, data)
    status = provenance.results_provenance(tmp_path)
    assert status["status"] == "historical_unverified" and "incomplete" in status["reason"]


@pytest.mark.parametrize("content", ["not json {", "[]", '"text"'])
def test_unreadable_or_malformed_metadata_is_not_trusted(tmp_path, content):
    _write_summary(tmp_path)
    (tmp_path / provenance.METADATA_NAME).write_text(content, encoding="utf-8")
    assert provenance.results_provenance(tmp_path)["status"] == "historical_unverified"


def test_parameters_must_be_an_object(tmp_path):
    summary = _write_summary(tmp_path)
    _write_metadata(tmp_path, _metadata(summary, parameters="cutoff 0.15"))
    assert provenance.results_provenance(tmp_path)["status"] == "historical_unverified"


# --- through the API -------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app, raise_server_exceptions=False)


def test_api_labels_a_file_without_metadata_as_historical(client, tmp_path, monkeypatch):
    _write_summary(tmp_path / "reports")
    monkeypatch.setattr(api, "ROOT", tmp_path)
    body = client.get("/api/results").json()
    assert body["available"] is True
    assert body["provenance"]["status"] == "historical_unverified"
    assert body["provenance"]["label"] == HISTORICAL
    assert body["provenance"]["file_modified"]


def test_api_reports_a_documented_run_only_with_matching_metadata(client, tmp_path, monkeypatch):
    summary = _write_summary(tmp_path / "reports")
    _write_metadata(tmp_path / "reports", _metadata(summary))
    monkeypatch.setattr(api, "ROOT", tmp_path)
    body = client.get("/api/results").json()
    assert body["provenance"]["status"] == "documented_run"
    assert body["provenance"]["metadata"]["git_commit"] == "abc1234"


def test_api_without_any_results_has_no_provenance(client, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "ROOT", tmp_path)
    body = client.get("/api/results").json()
    assert body["available"] is False and body["provenance"] is None


def test_the_repository_reports_folder_is_never_called_a_documented_run_without_metadata():
    """The real backend/reports folder holds a copy of the historical snapshot and no metadata."""
    reports = Path(api.ROOT) / "reports"
    if not (reports / provenance.SUMMARY_NAME).is_file():
        pytest.skip("no local reports folder")
    if (reports / provenance.METADATA_NAME).is_file():
        pytest.skip("a run_metadata.json exists locally")
    assert provenance.results_provenance(reports)["status"] == "historical_unverified"
