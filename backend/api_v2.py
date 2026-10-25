"""Read-only API over documented benchmark V2 runs, plus an on-demand slice comparison.

Nothing here accepts a path from a client. Runs are the directories listed in the
``BENCHMARK_RUN_DIRS`` environment variable (separated by ``os.pathsep``); a run is addressed by
the directory name. The CT series used for the slice comparison is the directory named by
``CT_SERIES_DIR``. Without them the endpoints answer that no run / no series is configured.

Every number served comes from the CSV files of a run or from re-computation with the benchmark
code on the recorded seeds. The slice comparison reports whether its metrics reproduce the
values recorded in ``test_per_run.csv``; it does not invent results.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from scipy import ndimage

import benchmark_v2 as B

logger = logging.getLogger("biomedical_api.v2")
router = APIRouter(prefix="/api/v2", tags=["benchmark-v2"])

TABLES = (
    "test_summary", "selected_parameters", "grid_bracketing", "mask_ranking", "mask_sensitivity", "mask_summary",
    "tuning_criteria_comparison", "tuning_grid", "test_pairwise", "test_per_slice", "ssim_sensitivity",
    "comparison_vs_initial_grid", "tuning_slice_consistency",
)
FILTER_COLUMNS = ("condition", "mask", "family", "metric", "slice")
MAX_ROWS = 20000
BOUNDARY_BAND_PX = 3
IDENTITY_TOLERANCE_HU = 1e-6       # a mean change smaller than this is round-off, not an effect
CAVEATS = (
    "One CT series (one patient); tuning slices and test slices are slices of the same scan.",
    "The reference is a noisy clinical slice, not a noise-free ground truth; noise is synthetic.",
    "Test slices were inspected during development: this is not an untouched independent test set.",
    "Bootstrap intervals use few slices of one patient and under-cover; read them as descriptive spreads.",
    "Lower RMSE_HU or higher SSIM does not show better preservation of anatomy or any clinical benefit.",
)


# ----------------------------------------------------------------------------------------------
# configuration and run discovery
# ----------------------------------------------------------------------------------------------

def configured_runs() -> dict[str, Path]:
    """Runs that the server operator exposed, keyed by directory name."""
    runs: dict[str, Path] = {}
    for value in os.getenv("BENCHMARK_RUN_DIRS", "").split(os.pathsep):
        value = value.strip()
        if not value:
            continue
        path = Path(value)
        if (path / "run_metadata.json").is_file() and path.name not in runs:
            runs[path.name] = path.resolve()
    return runs


def _run_dir(run_id: str) -> Path:
    runs = configured_runs()
    if run_id not in runs:
        raise HTTPException(status_code=404, detail="Unknown benchmark run.")
    return runs[run_id]


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _signature(run_dir: Path) -> tuple:
    return tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(run_dir.glob("*")) if p.is_file())


@lru_cache(maxsize=16)
def _metadata_cached(run_dir: str, signature: tuple) -> dict:
    return B.json_safe(json.loads((Path(run_dir) / "run_metadata.json").read_text(encoding="utf-8")))   # NaN -> null


def load_metadata(run_dir: Path) -> dict:
    try:
        return _metadata_cached(str(run_dir), _signature(run_dir))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="The run metadata could not be read.") from exc


@lru_cache(maxsize=16)
def _integrity_cached(run_dir: str, signature: tuple) -> dict:
    base = Path(run_dir)
    recorded = _metadata_cached(run_dir, signature).get("files_sha256", {})
    missing, mismatched = [], []
    for name, expected in recorded.items():
        target = base / Path(name).name
        if not target.is_file():
            missing.append(name)
        elif _file_hash(target) != expected:
            mismatched.append(name)
    status = "no_hashes_recorded" if not recorded else ("verified" if not missing and not mismatched else "mismatch")
    unlisted = sorted(p.name for p in base.glob("*.csv") if p.name not in recorded)
    return {"status": status, "files_checked": len(recorded), "missing": missing, "mismatched": mismatched,
            "csv_files_not_covered_by_metadata": unlisted}


def integrity(run_dir: Path) -> dict:
    return _integrity_cached(str(run_dir), _signature(run_dir))


def _families_of(run_dir: Path) -> list[str]:
    """Denoiser families that were tuned in a run, in benchmark order (empty if the table is absent or unreadable)."""
    try:
        present = set(read_table(run_dir, "selected_parameters")["family"])
    except (HTTPException, KeyError, OSError, ValueError):
        return []
    return [family for family in B.ALL_FAMILIES if family in present]


def _summary_of(run_id: str, run_dir: Path) -> dict:
    meta = load_metadata(run_dir)
    params = meta.get("parameters", {})
    commit = str(meta.get("git_commit", "unknown"))
    return {
        "id": run_id,
        "generated_at": meta.get("generated_at"),
        "git_commit": commit,
        "source_state": "uncommitted working tree (dirty)" if commit.endswith("+dirty") else "clean commit",
        "grid_version": params.get("grid_version") or "v1 (first run; not recorded in its metadata)",
        "series_label": meta.get("series_directory_name"),
        "tune_slices": params.get("tune_slices", []),
        "test_slices": params.get("test_slices", []),
        "tune_repeats": params.get("tune_repeats"),
        "test_repeats": params.get("test_repeats"),
        "conditions": [c.get("name") for c in params.get("conditions", [])],
        "families": _families_of(run_dir),
        "integrity": integrity(run_dir),
        "tables": [n for n in TABLES if (run_dir / f"{n}.csv").is_file()],
        "limitations": meta.get("limitations"),
        "comparable_with_historical_results": False,
    }


# ----------------------------------------------------------------------------------------------
# tables
# ----------------------------------------------------------------------------------------------

@lru_cache(maxsize=64)
def _table_cached(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    return pd.read_csv(path)


INTERNAL_TABLES = ("test_per_run",)     # read by the slice comparison, never served as a table


def read_table(run_dir: Path, name: str, internal: bool = False) -> pd.DataFrame:
    if name not in TABLES and not (internal and name in INTERNAL_TABLES):
        raise HTTPException(status_code=404, detail="Unknown table.")
    path = run_dir / f"{name}.csv"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="This run does not contain that table.")
    stat = path.stat()
    return _table_cached(str(path), stat.st_mtime_ns, stat.st_size)


def json_rows(frame: pd.DataFrame) -> list[dict]:
    """Rows as JSON-safe dictionaries: NaN and infinities become null."""
    clean = frame.replace([np.inf, -np.inf], np.nan).astype(object)
    clean = clean.where(pd.notna(clean), None)
    return clean.to_dict(orient="records")


def filter_table(frame: pd.DataFrame, filters: dict[str, str | None]) -> pd.DataFrame:
    for column, value in filters.items():
        if value is None or column not in frame.columns:
            continue
        frame = frame[frame[column].astype(str) == value]
    return frame


# ----------------------------------------------------------------------------------------------
# interpretation computed from the tables
# ----------------------------------------------------------------------------------------------

def _is_unchanged(mean: float, low: float, high: float) -> bool:
    return abs(mean) <= IDENTITY_TOLERANCE_HU and abs(low) <= IDENTITY_TOLERANCE_HU and abs(high) <= IDENTITY_TOLERANCE_HU


def interpret(summary: pd.DataFrame, pairwise: pd.DataFrame | None = None) -> list[dict[str, Any]]:
    """Cautious statements derived from ``test_summary`` (and ``test_pairwise`` when available).

    Each statement names its evidence. It reports where the lowest mean RMSE_HU lies and how that
    compares with the unfiltered image; it never claims better anatomy preservation.
    """
    out: list[dict[str, Any]] = []
    filters = summary[summary["family"] != B.BASELINE]
    best_by: dict[tuple[str, str], str] = {}
    for (condition, mask), group in filters.groupby(["condition", "mask"], sort=False):
        group = group.dropna(subset=["RMSE_HU_mean"])
        if group.empty:
            out.append({"condition": condition, "mask": mask, "kind": "indeterminate",
                        "text": "No RMSE_HU values are available, so no statement can be made."})
            continue
        best = group.loc[group["RMSE_HU_mean"].idxmin()]
        best_by[(condition, mask)] = str(best["family"])
        others = group[group["family"] != best["family"]]
        separated, total = 0, len(others)
        if pairwise is not None and not pairwise.empty:
            rows = pairwise[(pairwise["condition"] == condition) & (pairwise["mask"] == mask) & (pairwise["metric"] == "RMSE_HU")]
            for other in others["family"]:
                direct = rows[(rows["A"] == best["family"]) & (rows["B"] == other)]
                reverse = rows[(rows["A"] == other) & (rows["B"] == best["family"])]
                if not direct.empty and float(direct.iloc[0]["ci_high"]) < 0:
                    separated += 1
                elif not reverse.empty and float(reverse.iloc[0]["ci_low"]) > 0:
                    separated += 1
        baseline = summary[(summary["condition"] == condition) & (summary["mask"] == mask) & (summary["family"] == B.BASELINE)]
        n = int(best["n_slices"]) if "n_slices" in best and pd.notna(best["n_slices"]) else None
        gain_text, change = "", "unknown"
        mean, low, high = (float(best.get(c, np.nan)) for c in ("RMSE_HU_gain_mean", "RMSE_HU_gain_ci_low", "RMSE_HU_gain_ci_high"))
        if np.isfinite([mean, low, high]).all():
            if _is_unchanged(mean, low, high):
                change = "identical"
                gain_text = "Its output is identical to the unfiltered noisy image (a no-filter choice), so it shows no change."
            elif high < 0:
                change = "lower"
                gain_text = (f"Relative to the unfiltered noisy image the paired mean change is {mean:+.2f} HU "
                             f"(interval {low:+.2f} to {high:+.2f} over {n} slices), an interval entirely below zero.")
            elif low > 0:
                change = "higher"
                gain_text = f"The error is higher than for the unfiltered image ({mean:+.2f} HU, interval {low:+.2f} to {high:+.2f})."
            else:
                change = "unresolved"
                gain_text = f"The change relative to the unfiltered image ({mean:+.2f} HU, interval {low:+.2f} to {high:+.2f}) is not resolved by these slices."
        sep_text = ""
        if pairwise is not None and total:
            sep_text = f" Paired intervals separate it from {separated} of {total} other filters."
        out.append({
            "condition": condition, "mask": mask, "kind": "best_rmse", "best_family": str(best["family"]),
            "unfiltered_rmse_hu": float(baseline.iloc[0]["RMSE_HU_mean"]) if not baseline.empty else None,
            "best_rmse_hu": float(best["RMSE_HU_mean"]), "change_vs_unfiltered": change,
            "separated_from": separated, "compared_with": total,
            "text": (f"On the {mask} mask the lowest mean RMSE_HU among the tuned filters is {best['family']} "
                     f"({float(best['RMSE_HU_mean']):.2f} HU). {gain_text}{sep_text} This is a statement about RMSE_HU on this mask only."),
        })
    for condition in sorted({c for c, _ in best_by}):
        pair = [best_by.get((condition, m)) for m in B.MASK_NAMES]
        if all(pair) and pair[0] != pair[1]:
            out.append({"condition": condition, "mask": "both", "kind": "mask_dependent", "main": pair[0], "inner": pair[1],
                        "text": f"The family with the lowest RMSE_HU depends on the mask: {pair[0]} on the principal mask, {pair[1]} on the inner mask."})
    return out


# ----------------------------------------------------------------------------------------------
# endpoints: runs and tables
# ----------------------------------------------------------------------------------------------

@router.get("/runs")
def list_runs():
    runs = configured_runs()
    return {"configured": bool(runs), "runs": [_summary_of(run_id, path) for run_id, path in sorted(runs.items())],
            "caveats": list(CAVEATS),
            "slice_comparison_available": bool(os.getenv("CT_SERIES_DIR", "").strip())}


@router.get("/runs/{run_id}")
def run_detail(run_id: str):
    run_dir = _run_dir(run_id)
    return {"summary": _summary_of(run_id, run_dir), "metadata": load_metadata(run_dir), "caveats": list(CAVEATS)}


@router.get("/runs/{run_id}/tables/{name}")
def table(run_id: str, name: str, format: str = Query("json", pattern="^(json|csv)$"),
          condition: str | None = Query(None, max_length=64), mask: str | None = Query(None, max_length=16),
          family: str | None = Query(None, max_length=64), metric: str | None = Query(None, max_length=64)):
    run_dir = _run_dir(run_id)
    frame = filter_table(read_table(run_dir, name), {"condition": condition, "mask": mask, "family": family, "metric": metric})
    if len(frame) > MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"The table has more than {MAX_ROWS} rows; add filters.")
    if format == "csv":
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        filename = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{run_id}_{name}.csv")
        return PlainTextResponse(buffer.getvalue(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    return {"run": run_id, "table": name, "columns": list(frame.columns), "rows": json_rows(frame), "n_rows": len(frame)}


@router.get("/runs/{run_id}/interpretation")
def interpretation(run_id: str):
    run_dir = _run_dir(run_id)
    summary = read_table(run_dir, "test_summary")
    pairwise = read_table(run_dir, "test_pairwise") if (run_dir / "test_pairwise.csv").is_file() else None
    return {"run": run_id, "statements": interpret(summary, pairwise), "caveats": list(CAVEATS)}


# ----------------------------------------------------------------------------------------------
# slice comparison (recomputed with the benchmark code on the recorded seeds)
# ----------------------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _volume(series_dir: str, signature: tuple) -> np.ndarray:
    from src.dicom_volume import load_dicom_volume

    volume, _spacing, _positions, _extra = load_dicom_volume(Path(series_dir))
    return volume


def load_series_volume() -> np.ndarray:
    value = os.getenv("CT_SERIES_DIR", "").strip()
    if not value or not Path(value).is_dir():
        raise HTTPException(status_code=503, detail="No CT series is configured on the server, so images cannot be recomputed.")
    path = Path(value).resolve()
    signature = tuple((p.name, p.stat().st_mtime_ns) for p in sorted(path.rglob("*")) if p.is_file())[:2000]
    try:
        return _volume(str(path), signature)
    except Exception as exc:  # the loader raises ValueError with curated messages for malformed series
        logger.info("CT series could not be loaded: %s", exc)
        raise HTTPException(status_code=503, detail="The configured CT series could not be loaded.") from exc


class SliceRequest:
    def __init__(self, run_id: str, slice_index: int, condition: str, repeat: int):
        self.run_dir = _run_dir(run_id)
        self.run_id = run_id
        meta = load_metadata(self.run_dir)
        params = meta["parameters"]
        names = [c["name"] for c in params["conditions"]]
        if condition not in names:
            raise HTTPException(status_code=422, detail="Unknown noise condition for this run.")
        self.condition_index = names.index(condition)
        self.condition = next(c for c in B.CONDITIONS if c.name == condition)
        if slice_index in params["test_slices"]:
            self.role, self.base_seed, repeats = "test", params["test_base_seed"], params["test_repeats"]
        elif slice_index in params["tune_slices"]:
            self.role, self.base_seed, repeats = "tuning", params["tune_base_seed"], params["tune_repeats"]
        else:
            raise HTTPException(status_code=422, detail="This slice was not used in the run (tuning or test slices only).")
        if not 1 <= repeat <= repeats:
            raise HTTPException(status_code=422, detail=f"repeat must be between 1 and {repeats} for this run.")
        self.slice_index, self.repeat = slice_index, repeat
        self.seed = B.condition_seed(self.base_seed, slice_index, self.condition_index, repeat - 1)
        selected = read_table(self.run_dir, "selected_parameters")
        rows = selected[selected["condition"] == condition]
        self.params = {str(r["family"]): json.loads(r["params"]) for _, r in rows.iterrows()}


def _boundary_split(mask: np.ndarray, band_px: int = BOUNDARY_BAND_PX) -> tuple[np.ndarray, np.ndarray]:
    distance = ndimage.distance_transform_edt(mask)
    return mask & (distance > band_px), mask & (distance <= band_px)


@lru_cache(maxsize=6)
def _case_bundle(run_id: str, signature: tuple, slice_index: int, condition: str, repeat: int, series_token: str):
    request = SliceRequest(run_id, slice_index, condition, repeat)
    volume = load_series_volume()
    if slice_index >= volume.shape[0]:
        raise HTTPException(status_code=422, detail="The configured series has no such slice.")
    reference = volume[slice_index]
    masks = B.reference_masks(reference.astype(np.float64))
    case = B.make_case(reference, request.condition, request.seed, masks=masks)
    outputs = {B.BASELINE: case.noisy_hu}
    for family in B.ALL_FAMILIES:
        if family in request.params:
            outputs[family] = B.filter_hu(case.noisy_hu, family, request.params[family])
    return request, case, outputs


def bundle(run_id: str, slice_index: int, condition: str, repeat: int):
    run_dir = _run_dir(run_id)
    token = os.getenv("CT_SERIES_DIR", "")
    return _case_bundle(run_id, _signature(run_dir), slice_index, condition, repeat, token)


def _rmse(error: np.ndarray, region: np.ndarray) -> float | None:
    return float(np.sqrt(np.mean(error[region] ** 2))) if region.any() else None


@router.get("/runs/{run_id}/slice-comparison")
def slice_comparison(run_id: str, slice: int = Query(..., ge=0, le=100000), condition: str = Query(..., max_length=64),
                     repeat: int = Query(1, ge=1, le=50), row: int | None = Query(None, ge=0, le=100000)):
    request, case, outputs = bundle(run_id, slice, condition, repeat)
    height = case.reference_hu.shape[0]
    if row is None:
        rows_in_mask = np.flatnonzero(case.mask.any(axis=1))
        row = int(rows_in_mask[len(rows_in_mask) // 2]) if rows_in_mask.size else height // 2
    if row >= height:
        raise HTTPException(status_code=422, detail="row is outside the image.")
    recorded = None
    per_run = read_table(request.run_dir, "test_per_run", internal=True) if request.role == "test" else None
    results = []
    mask_core, mask_band = _boundary_split(case.mask)
    for family, output in outputs.items():
        error = output.astype(np.float64) - case.reference_hu.astype(np.float64)
        metrics = B.evaluate_masks(case, output)
        entry = {"family": family, "params": request.params.get(family, {}),
                 "identity": bool(B.is_identity(family, request.params[family])) if family in request.params else True,
                 "metrics": {m: {k: (None if not np.isfinite(v) else float(v)) for k, v in vals.items()} for m, vals in metrics.items()},
                 "rmse_hu_boundary_band": _rmse(error, mask_band), "rmse_hu_core": _rmse(error, mask_core),
                 "max_abs_error_hu_in_mask": float(np.abs(error[case.mask]).max())}
        if per_run is not None:
            match = per_run[(per_run["condition"] == condition) & (per_run["slice"] == slice) & (per_run["repeat"] == repeat) & (per_run["family"] == family) & (per_run["mask"] == "main")]
            if len(match) == 1:
                entry["recorded_rmse_hu_main"] = float(match.iloc[0]["RMSE_HU"])
                entry["matches_recorded"] = bool(abs(entry["recorded_rmse_hu_main"] - entry["metrics"]["main"]["RMSE_HU"]) < 1e-4)
        results.append(entry)
    if per_run is not None:
        flags = [e.get("matches_recorded") for e in results if "matches_recorded" in e]
        recorded = {"compared": len(flags), "all_match": bool(flags) and all(flags)}
    return {
        "run": run_id, "slice": slice, "role": request.role, "condition": condition, "repeat": repeat, "seed": request.seed,
        "shape": list(case.reference_hu.shape), "row": row, "mask_pixels": {k: int(v.sum()) for k, v in case.masks().items()},
        "boundary_band_px": BOUNDARY_BAND_PX, "band_fraction_of_mask": float(mask_band.sum() / max(case.mask.sum(), 1)),
        "outputs": results, "reproduces_recorded_run": recorded,
        "profile": {"row": row, "unit": "HU", "reference": case.reference_hu[row].astype(float).tolist(),
                    "series": {name: out[row].astype(float).tolist() for name, out in outputs.items()}},
        "notes": ["Images are recomputed from the recorded seed with the benchmark code; they are not stored results.",
                  "Boundary-band and core RMSE_HU are descriptive splits of the principal mask (distance to the mask edge), not benchmark metrics.",
                  "A difference map shows filtered minus reference in HU; it is not a map of clinical change."],
    }


def _encode_png(gray_or_bgr: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", gray_or_bgr)
    if not ok:
        raise HTTPException(status_code=500, detail="The image could not be encoded.")
    return encoded.tobytes()


@router.get("/runs/{run_id}/slice-image")
def slice_image(run_id: str, slice: int = Query(..., ge=0, le=100000), condition: str = Query(..., max_length=64),
                repeat: int = Query(1, ge=1, le=50), view: str = Query(..., max_length=80),
                window_center: float = Query(B.DISPLAY_WINDOW_CENTER, ge=-2048, le=4096),
                window_width: float = Query(B.DISPLAY_WINDOW_WIDTH, gt=1, le=8192),
                diff_range_hu: float = Query(100.0, gt=0, le=2000), overlay: str | None = Query(None, pattern="^(main|inner)$")):
    request, case, outputs = bundle(run_id, slice, condition, repeat)
    kind, _, family = view.partition(":")
    if kind == "reference":
        hu = case.reference_hu
    elif kind == "noisy":
        hu = case.noisy_hu
    elif kind in ("filtered", "diff"):
        if family not in outputs:
            raise HTTPException(status_code=422, detail="Unknown filter family for this condition.")
        hu = outputs[family]
    else:
        raise HTTPException(status_code=422, detail="view must be reference, noisy, filtered:<family> or diff:<family>.")
    if kind == "diff":
        difference = hu.astype(np.float64) - case.reference_hu.astype(np.float64)
        gray = np.clip(127.5 + 127.5 * difference / diff_range_hu, 0, 255).astype(np.uint8)
    else:
        low, high = window_center - window_width / 2, window_center + window_width / 2
        gray = np.clip((hu.astype(np.float64) - low) / (high - low) * 255.0, 0, 255).astype(np.uint8)
    image: np.ndarray = gray
    if overlay:
        mask = case.masks()[overlay]
        edge = mask & ~ndimage.binary_erosion(mask)
        image = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        image[edge] = (60, 60, 230)
    return Response(content=_encode_png(image), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
