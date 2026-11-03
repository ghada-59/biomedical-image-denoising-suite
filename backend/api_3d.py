"""Read-only API over documented Benchmark 3D runs (slice-wise versus volumetric Gaussian smoothing).

Same rules as ``api_v2``: nothing here accepts a path from a client. Runs are the directories listed in the ``BENCHMARK_3D_RUN_DIRS``
environment variable (separated by ``os.pathsep``; relative entries mean "relative to backend/") and are addressed by directory name. Without
that variable the endpoints answer that no run is configured. Every number served comes from the CSV files or the metadata of a recorded run;
the interpretation endpoint only counts and compares values of those tables.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

import benchmark_3d as B3
import benchmark_v2 as B2
from api_v2 import filter_table, json_rows

router = APIRouter(prefix="/api/3d", tags=["benchmark-3d"])

TABLES = ("test_summary", "test_pairwise", "test_per_slice", "selected_parameters", "tuning_grid")
MAX_ROWS = 20000
UNCHANGED_TOLERANCE_HU = 1e-6          # differences below this are round-off, not an effect
CAVEATS = (
    "One CT series (one patient); tuning slices and test slices are slices of the same scan, and slices of one scan are not independent samples.",
    "The reference is a noisy clinical slice and the noise is synthetic; every score measures similarity to that reference.",
    "Only Gaussian smoothing is compared; the result says nothing about other 3D filters, thinner slices or other patients.",
    "Intervals are percentile bootstrap intervals over 8 slices of one patient; they describe spread over slices and under-cover (about 78 to 89 % for a nominal 95 %).",
    "A lower RMSE_HU does not show better preservation of anatomy or any clinical benefit.",
)
DEFAULT_NOISE_MODEL = {
    "kind": "white, independent between voxels and between slices",
    "adjacent_slice_correlation": 0.0,
    "note": "More favourable to smoothing across slices than the real noise of the series, which is partly correlated between adjacent slices.",
}


def configured_runs() -> dict[str, Path]:
    """Runs that the server operator exposed, keyed by directory name."""
    runs: dict[str, Path] = {}
    for value in os.getenv("BENCHMARK_3D_RUN_DIRS", "").split(os.pathsep):
        value = value.strip()
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        if (path / "run_metadata.json").is_file() and path.name not in runs:
            runs[path.name] = path.resolve()
    return runs


def _run_dir(run_id: str) -> Path:
    runs = configured_runs()
    if run_id not in runs:
        raise HTTPException(status_code=404, detail="Unknown benchmark run.")
    return runs[run_id]


def _signature(run_dir: Path) -> tuple:
    return tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(run_dir.glob("*")) if p.is_file())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@lru_cache(maxsize=16)
def _metadata_cached(run_dir: str, signature: tuple) -> dict:
    return B2.json_safe(json.loads((Path(run_dir) / "run_metadata.json").read_text(encoding="utf-8")))


def load_metadata(run_dir: Path) -> dict:
    try:
        return _metadata_cached(str(run_dir), _signature(run_dir))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="The run metadata could not be read.") from exc


@lru_cache(maxsize=16)
def _integrity_cached(run_dir: str, signature: tuple) -> dict:
    base = Path(run_dir)
    meta = _metadata_cached(run_dir, signature)
    recorded = {**meta.get("files_sha256", {}), **meta.get("figures_sha256", {})}
    missing, mismatched = [], []
    for name, expected in recorded.items():
        target = base / Path(name).name
        if not target.is_file():
            missing.append(name)
        elif _sha256(target) != expected:
            mismatched.append(name)
    status = "no_hashes_recorded" if not recorded else ("verified" if not missing and not mismatched else "mismatch")
    unlisted = sorted(p.name for p in base.glob("*") if p.is_file() and p.name not in recorded and p.name != "run_metadata.json")
    return {"status": status, "files_checked": len(recorded), "missing": missing, "mismatched": mismatched, "files_not_covered_by_metadata": unlisted}


def integrity(run_dir: Path) -> dict:
    return _integrity_cached(str(run_dir), _signature(run_dir))


@lru_cache(maxsize=64)
def _table_cached(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    return pd.read_csv(path)


def read_table(run_dir: Path, name: str) -> pd.DataFrame:
    if name not in TABLES:
        raise HTTPException(status_code=404, detail="Unknown table.")
    path = run_dir / f"{name}.csv"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="This run does not contain that table.")
    stat = path.stat()
    return _table_cached(str(path), stat.st_mtime_ns, stat.st_size)


def _noise_model(meta: dict) -> dict:
    return meta.get("parameters", {}).get("noise_model") or DEFAULT_NOISE_MODEL


def _summary_of(run_id: str, run_dir: Path) -> dict:
    meta = load_metadata(run_dir)
    params = meta.get("parameters", {})
    commit = str(meta.get("git_commit", "unknown"))
    try:
        methods = [m for m in B3.METHODS if m in set(read_table(run_dir, "selected_parameters")["method"])]
    except (HTTPException, KeyError, OSError, ValueError):
        methods = []
    return {
        "id": run_id, "benchmark": meta.get("benchmark"), "generated_at": meta.get("generated_at"), "git_commit": commit,
        "source_state": "uncommitted working tree (dirty); the SHA-256 of the source files identifies the code" if commit.endswith("+dirty") else "clean commit",
        "series_label": meta.get("series_directory_name"), "volume_shape_zyx": meta.get("volume_shape_zyx"), "voxel_spacing_xyz_mm": meta.get("voxel_spacing_xyz_mm"),
        "tune_slices": params.get("tune_slices", []), "test_slices": params.get("test_slices", []), "tune_repeats": params.get("tune_repeats"),
        "test_repeats": params.get("test_repeats"), "noise_sigmas_hu": params.get("noise_sigmas_hu", []), "primary_mask": params.get("primary_mask"),
        "selection_criterion": params.get("selection_criterion"), "bootstrap_seed": params.get("bootstrap_seed"), "n_boot": params.get("n_boot"),
        "noise_model": _noise_model(meta), "methods": methods, "integrity": integrity(run_dir), "tables": [n for n in TABLES if (run_dir / f"{n}.csv").is_file()],
        "figures": sorted(meta.get("figures_sha256", {})), "source_files": sorted(meta.get("source_files_sha256", {})), "limitations": meta.get("limitations"),
        "status": "recorded run; exploratory, one patient (not an independent validation)",
        "comparable_with_historical_results": False,
    }


@router.get("/runs")
def list_runs():
    runs = configured_runs()
    return {"configured": bool(runs), "runs": [_summary_of(run_id, path) for run_id, path in sorted(runs.items())], "caveats": list(CAVEATS)}


@router.get("/runs/{run_id}")
def run_detail(run_id: str):
    run_dir = _run_dir(run_id)
    return {"summary": _summary_of(run_id, run_dir), "metadata": load_metadata(run_dir), "caveats": list(CAVEATS)}


@router.get("/runs/{run_id}/tables/{name}")
def table(run_id: str, name: str, format: str = Query("json", pattern="^(json|csv)$"),
          condition: str | None = Query(None, max_length=64), mask: str | None = Query(None, max_length=16),
          method: str | None = Query(None, max_length=64), metric: str | None = Query(None, max_length=64)):
    run_dir = _run_dir(run_id)
    frame = filter_table(read_table(run_dir, name), {"condition": condition, "mask": mask, "method": method, "metric": metric})
    if len(frame) > MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"The table has more than {MAX_ROWS} rows; add filters.")
    if format == "csv":
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        filename = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{run_id}_{name}.csv")
        return PlainTextResponse(buffer.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    return {"run": run_id, "table": name, "columns": list(frame.columns), "rows": json_rows(frame), "n_rows": len(frame)}


@router.get("/runs/{run_id}/figures/{name}")
def figure(run_id: str, name: str):
    run_dir = _run_dir(run_id)
    recorded = load_metadata(run_dir).get("figures_sha256", {})
    if name not in recorded:                                         # only the figures named by the metadata; no client-supplied path is ever opened
        raise HTTPException(status_code=404, detail="Unknown figure.")
    path = run_dir / Path(name).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="This run does not contain that figure.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


# ----------------------------------------------------------------------------------------------
# interpretation computed from the tables
# ----------------------------------------------------------------------------------------------

def _classify(mean: float, low: float, high: float) -> str:
    if max(abs(mean), abs(low), abs(high)) <= UNCHANGED_TOLERANCE_HU:
        return "identical"
    if high < 0:
        return "lower"
    if low > 0:
        return "higher"
    return "unresolved"


def interpret(summary: pd.DataFrame, pairwise: pd.DataFrame, per_slice: pd.DataFrame, mask: str = "main") -> list[dict[str, Any]]:
    """One statement per noise condition: the three methods against the unfiltered image, and the anisotropic 3D family against slice-wise 2D.

    The paired difference comes from ``test_pairwise``; the slice counts compare the two families slice by slice in ``test_per_slice``.
    Nothing is concluded beyond RMSE_HU on the named mask of this series.
    """
    two_d, _iso, aniso = B3.METHODS
    out: list[dict[str, Any]] = []
    for condition in summary["condition"].drop_duplicates():
        rows = summary[(summary["condition"] == condition) & (summary["mask"] == mask)].set_index("method")
        if two_d not in rows.index or aniso not in rows.index or B3.BASELINE not in rows.index:
            continue
        pair = pairwise[(pairwise["condition"] == condition) & (pairwise["mask"] == mask) & (pairwise["metric"] == "RMSE_HU") & (pairwise["A"] == aniso) & (pairwise["B"] == two_d)]
        slices = per_slice[(per_slice["condition"] == condition) & (per_slice["mask"] == mask)].pivot(index="slice", columns="method", values="RMSE_HU")
        difference = (slices[aniso] - slices[two_d]).dropna()
        lower, higher = int((difference < -UNCHANGED_TOLERANCE_HU).sum()), int((difference > UNCHANGED_TOLERANCE_HU).sum())
        entry: dict[str, Any] = {
            "condition": condition, "mask": mask,
            "unfiltered_rmse_hu": float(rows.loc[B3.BASELINE, "RMSE_HU_mean"]),
            "rmse_hu": {m: float(rows.loc[m, "RMSE_HU_mean"]) for m in B3.METHODS},
            "slices_compared": int(len(difference)), "slices_lower": lower, "slices_higher": higher, "slices_equal": int(len(difference)) - lower - higher,
        }
        if pair.empty:
            entry.update(kind="indeterminate", text=f"{condition}: no paired difference is recorded for the anisotropic family against slice-wise smoothing.")
        else:
            mean, low, high = (float(pair.iloc[0][c]) for c in ("mean_A_minus_B", "ci_low", "ci_high"))
            kind = _classify(mean, low, high)
            relative = 100.0 * abs(mean) / float(rows.loc[two_d, "RMSE_HU_mean"]) if rows.loc[two_d, "RMSE_HU_mean"] else 0.0
            entry.update(kind=kind, paired_difference_hu=mean, ci_low=low, ci_high=high, relative_percent=relative)
            if kind == "identical":
                detail = "The anisotropic 3D family selected the slice-wise setting, so its output equals the slice-wise output."
            else:
                detail = (f"Anisotropic 3D minus slice-wise 2D: {mean:+.2f} HU (interval {low:+.2f} to {high:+.2f} over {entry['slices_compared']} slices, "
                          f"{relative:.1f} % of the 2D error; lower in {lower}, higher in {higher} of the slices).")
            entry["text"] = (f"At {condition.replace('white_', '').replace('HU', ' HU')}: unfiltered {entry['unfiltered_rmse_hu']:.2f} HU, 2D {entry['rmse_hu'][two_d]:.2f} HU, "
                             f"3D isotropic {entry['rmse_hu'][B3.METHODS[1]]:.2f} HU, 3D anisotropic {entry['rmse_hu'][aniso]:.2f} HU (RMSE_HU, {mask} mask). {detail} "
                             "A statement about RMSE_HU on this mask and this series only.")
        out.append(entry)
    return out


@router.get("/runs/{run_id}/interpretation")
def interpretation(run_id: str):
    run_dir = _run_dir(run_id)
    meta = load_metadata(run_dir)
    mask = str(meta.get("parameters", {}).get("primary_mask") or "main")
    return {"run": run_id, "mask": mask, "noise_model": _noise_model(meta),
            "statements": interpret(read_table(run_dir, "test_summary"), read_table(run_dir, "test_pairwise"), read_table(run_dir, "test_per_slice"), mask),
            "caveats": list(CAVEATS)}
