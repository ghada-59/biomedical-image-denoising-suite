"""The benchmark runs that ship inside the repository must stay byte-identical to what their metadata recorded."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import api_v2

RESULTS = Path(__file__).resolve().parent / "docs" / "results"
RUNS = sorted(p for p in RESULTS.glob("benchmark_v2_*") if (p / "run_metadata.json").is_file())


def test_at_least_one_documented_run_ships_with_the_repository():
    assert RUNS, "no documented benchmark V2 run found under docs/results"


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_every_recorded_hash_matches_the_file_on_disk(run):
    recorded = json.loads((run / "run_metadata.json").read_text(encoding="utf-8"))["files_sha256"]
    assert recorded
    for name, digest in recorded.items():
        assert hashlib.sha256((run / name).read_bytes()).hexdigest() == digest, f"{name} differs from its recorded SHA-256 (line endings?)"
    assert api_v2.integrity(run)["status"] == "verified"


@pytest.mark.parametrize("run", RUNS, ids=lambda p: p.name)
def test_a_shipped_run_was_made_from_a_clean_commit_and_names_its_code(run):
    meta = json.loads((run / "run_metadata.json").read_text(encoding="utf-8"))
    assert not meta["git_commit"].endswith("+dirty") and len(meta["git_commit"]) == 40
    assert set(meta["source_files_sha256"]) >= {"benchmark_v2.py", "filters.py", "src/dicom_volume.py"}
    assert meta["input_series"]["dicom_instances"] > 0 and len(meta["input_series"]["manifest_sha256"]) == 64
    text = (run / "run_metadata.json").read_text(encoding="utf-8")
    for tag in ("PatientID", "PatientName", "PatientBirthDate", "PatientSex", "InstitutionName", "StudyDate"):
        assert tag not in text, f"{tag} must not be recorded in run metadata"


def test_the_attributes_file_keeps_recorded_runs_out_of_line_ending_conversion():
    attributes = (RESULTS.parent.parent.parent / ".gitattributes").read_text(encoding="utf-8")
    assert "backend/docs/results/benchmark_v2_*/** -text" in attributes
