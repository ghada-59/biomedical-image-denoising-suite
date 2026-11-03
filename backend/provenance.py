"""Provenance status of the benchmark files served by the API and the Streamlit app.

A results CSV is only presented as a documented run when a ``run_metadata.json`` next to
it records the run *and* its ``summary_sha256`` matches the CSV actually on disk. In every
other case the files are reported as historical and unverified. Metadata is never
invented retroactively.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUMMARY_NAME = "denoising_summary.csv"
METADATA_NAME = "run_metadata.json"

HISTORICAL_LABEL = "Historical results — provenance and currency not verified"
DOCUMENTED_LABEL = "Documented run — run metadata matches this summary file"
REQUIRED_KEYS = ("schema_version", "generated_at", "git_commit", "parameters", "summary_sha256")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _historical(reason: str, modified: str | None) -> dict[str, Any]:
    return {
        "status": "historical_unverified",
        "label": HISTORICAL_LABEL,
        "reason": reason,
        "file_modified": modified,
        "metadata": None,
    }


def results_provenance(reports_dir: Path) -> dict[str, Any]:
    """Describe how far the summary CSV in ``reports_dir`` can be trusted as a recorded run."""
    summary = reports_dir / SUMMARY_NAME
    metadata_path = reports_dir / METADATA_NAME
    modified = None
    if summary.is_file():
        modified = datetime.fromtimestamp(summary.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")

    if not metadata_path.is_file():
        return _historical(f"No {METADATA_NAME} accompanies the results file.", modified)
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _historical(f"{METADATA_NAME} is unreadable.", modified)
    if not isinstance(metadata, dict) or any(key not in metadata for key in REQUIRED_KEYS):
        return _historical(f"{METADATA_NAME} is incomplete (required: {', '.join(REQUIRED_KEYS)}).", modified)
    if not isinstance(metadata["parameters"], dict):
        return _historical(f"{METADATA_NAME} has invalid parameters.", modified)
    if not summary.is_file() or sha256_of(summary) != metadata["summary_sha256"]:
        return _historical(f"{METADATA_NAME} does not match the results file on disk.", modified)

    return {
        "status": "documented_run",
        "label": DOCUMENTED_LABEL,
        "reason": None,
        "file_modified": modified,
        "metadata": {key: metadata[key] for key in ("generated_at", "git_commit", "parameters")},
    }
