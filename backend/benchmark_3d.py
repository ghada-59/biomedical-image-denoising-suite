"""Benchmark 3D: does smoothing across slices help? Slice-wise (2D) versus volumetric (3D) Gaussian smoothing on a CT series.

Question
    Add white Gaussian noise (sigma 10, 25 or 50 HU, independent for every voxel) to a CT volume and smooth it with a Gaussian
    filter whose width is given in millimetres. Three families are compared, all tuned on separate slices and then frozen:

    * ``2D slice-wise Gaussian``: sigma_xy in the plane, nothing across slices;
    * ``3D isotropic Gaussian``: the same sigma in millimetres along x, y and z (so, in voxels, far less along z on thick slices);
    * ``3D anisotropic Gaussian``: sigma_xy and sigma_z tuned jointly; it contains the 2D family as the case sigma_z = 0.

    The anisotropic family can only match or beat the 2D family on the tuning data, so the interesting number is whether it still
    wins on the held-out test slices, and by how much.

What is reported, per method and per region
    * RMSE_HU and MAE_HU against the reference slice (unclipped HU); PSNR and SSIM on the displayed -600/1500 HU window;
    * a trade-off split of the error. For a linear filter ``f``: ``f(reference + noise) - reference = (f(reference) - reference) + f(noise)``.
      ``blur_rmse_hu`` is the RMS of the first term (what the filter does to the structure with no noise present) and
      ``residual_noise_hu`` the RMS of the second (the noise that is left). ``cross_term_hu2`` is the remainder, so that
      ``RMSE_HU**2 = blur_rmse_hu**2 + residual_noise_hu**2 + cross_term_hu2`` holds exactly and can be checked.
    * the regions: ``main`` (the body of the reference slice; primary, as in benchmark V2), ``inner`` (the body more than 10 px from the
      padding; sensitivity) and ``soft`` (homogeneous soft tissue, 0 to 100 HU, away from edges; only the HU errors and the split are
      reported there). In ``soft`` there is almost no structure to lose, so it shows the noise reduction a filter *can* give; ``main``
      includes the lung boundaries, vessels and the skin, so it shows what that costs.

Protocol (same spirit as benchmark V2)
    The tuning slices and the test slices are disjoint and at least ``HALF_SLAB`` slices apart; tuning and test use different noise
    seeds; the parameters are selected on RMSE_HU over the principal mask of the tuning slices only; every method sees the same noisy
    volume; the interval of a mean is a percentile bootstrap over the test slices of ONE patient.

The padding outside the field of view
    CT series store the area outside the circular field of view as a constant (-2048 HU here). Smoothing raw HU would smear that constant
    into the body edge and the error on the principal mask would be dominated by this artefact. The filters therefore use *normalised
    convolution*: ``f(x) = G*(valid * x) / G*(valid)``, where ``valid`` marks the voxels inside the field of view (known from the
    reference, not from the noisy data) and ``G`` is the Gaussian. Only valid voxels contribute, and ``f`` stays linear in ``x``.

Limits
    The noise is independent between voxels, including between slices. Real CT noise is correlated in-plane and often partly across
    slices, so this experiment is more favourable to smoothing across slices than real data would be. The reference slice itself is a
    noisy clinical slice. One patient, 8 test slices: intervals describe the spread over slices of that patient, not over patients.
    RMSE over a whole mask is dominated by the few high-contrast edges, which favours weak smoothing; the ``soft`` region and the split
    exist to show the other side. Nothing here says anything about diagnostic quality.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage

import benchmark_v2 as b2

SCHEMA_VERSION = 2
BASELINE = b2.BASELINE
HALF_SLAB = 8                                   # slices kept on each side of a case; at least the reach of the widest kernel along z
NOISE_SIGMAS_HU = (10.0, 25.0, 50.0)
XY_GRID_MM = (0.0, 0.25, 0.4, 0.55, 0.8, 1.1, 1.6, 2.2, 3.0)
Z_GRID_MM = (0.0, 1.0, 1.5, 3.0, 4.5, 6.0)
ISO_GRID_MM = (*XY_GRID_MM[1:], 4.5, 6.0)
METHODS = ("2D slice-wise Gaussian", "3D isotropic Gaussian", "3D anisotropic Gaussian")
PRIMARY_MASK = "main"
MASKS = ("main", "inner")                       # all metrics
REGIONS = ("soft",)                             # HU errors and the error split only
ALL_REGIONS = (*MASKS, *REGIONS)
PAIRS = ((METHODS[2], METHODS[0]), (METHODS[1], METHODS[0]), (METHODS[2], METHODS[1]))
SUMMARY_METRICS = ("RMSE_HU", "MAE_HU", "PSNR_dB", "SSIM_Wang2004", "blur_rmse_hu", "residual_noise_hu")
PAIR_METRICS = ("RMSE_HU", "blur_rmse_hu", "residual_noise_hu", "SSIM_Wang2004")
TUNING_BASE_SEED, TEST_BASE_SEED = 3000, 4000000
BOOTSTRAP_SEED = 12345
MIN_SOFT_PIXELS = 1000
MIN_WEIGHT = 1e-9


# --- filters ---------------------------------------------------------------------------------------------


def sigma_voxels(sigma_xy_mm: float, sigma_z_mm: float, spacing_xyz_mm: tuple[float, float, float]) -> tuple[float, float, float]:
    """Gaussian sigmas in voxels for a (z, y, x) volume from sigmas in millimetres and the voxel spacing (x, y, z)."""
    sx, sy, sz = (float(v) for v in spacing_xyz_mm)
    if min(sx, sy, sz) <= 0 or sigma_xy_mm < 0 or sigma_z_mm < 0:
        raise ValueError("spacing must be positive and sigmas must not be negative.")
    return (sigma_z_mm / sz, sigma_xy_mm / sy, sigma_xy_mm / sx)


def kernel_radius(sigma_voxels_along_axis: float, truncate: float = 4.0) -> int:
    """Half-width scipy.ndimage.gaussian_filter uses for a given sigma (in voxels)."""
    return int(truncate * sigma_voxels_along_axis + 0.5)


def _gaussian(volume: np.ndarray, params: dict, spacing_xyz_mm: tuple[float, float, float]) -> np.ndarray:
    sigma = sigma_voxels(params["sigma_xy_mm"], params["sigma_z_mm"], spacing_xyz_mm)
    if kernel_radius(sigma[0]) > HALF_SLAB:
        raise ValueError(f"sigma_z of {params['sigma_z_mm']} mm reaches {kernel_radius(sigma[0])} slices; HALF_SLAB is {HALF_SLAB}.")
    return ndimage.gaussian_filter(volume, sigma=sigma, mode="reflect", truncate=4.0)     # an axis with sigma 0 is left untouched


def valid_weights(valid: np.ndarray, params: dict, spacing_xyz_mm: tuple[float, float, float]) -> np.ndarray:
    """Denominator of the normalised convolution: how much of the Gaussian window at each voxel lies inside the field of view."""
    return _gaussian(valid.astype(np.float64), params, spacing_xyz_mm)


def smooth(volume_hu: np.ndarray, params: dict, spacing_xyz_mm: tuple[float, float, float], valid: np.ndarray | None = None,
           weights: np.ndarray | None = None) -> np.ndarray:
    """Gaussian smoothing of a (z, y, x) HU volume with sigmas in millimetres.

    Without ``valid`` this is a plain Gaussian filter. With ``valid`` (voxels inside the field of view) it is a normalised convolution,
    ``G*(valid*x) / G*(valid)``, so that the padding never leaks into the image; ``weights`` may pass a precomputed ``G*(valid)``.
    """
    if valid is None:
        return _gaussian(volume_hu, params, spacing_xyz_mm)
    denominator = valid_weights(valid, params, spacing_xyz_mm) if weights is None else weights
    numerator = _gaussian(np.where(valid, volume_hu, 0.0), params, spacing_xyz_mm)
    return np.where(denominator > MIN_WEIGHT, numerator / np.maximum(denominator, MIN_WEIGHT), volume_hu)


def method_grid() -> dict[str, list[dict]]:
    return {
        METHODS[0]: [{"sigma_xy_mm": s, "sigma_z_mm": 0.0} for s in XY_GRID_MM],
        METHODS[1]: [{"sigma_xy_mm": s, "sigma_z_mm": s} for s in ISO_GRID_MM],
        METHODS[2]: [{"sigma_xy_mm": s, "sigma_z_mm": z} for s in XY_GRID_MM for z in Z_GRID_MM],
    }


# --- cases -----------------------------------------------------------------------------------------------


def extract_slab(volume: np.ndarray, index: int, half: int = HALF_SLAB) -> tuple[np.ndarray, int]:
    """Slices ``index - half .. index + half`` (clipped to the volume) as float64, and the position of ``index`` inside them.

    Smoothing the slab and reading its centre slice equals smoothing the whole volume and reading slice ``index``, because
    ``half`` is at least the reach of the widest kernel and a slab end that is also the volume end reflects exactly like the volume.
    """
    low, high = max(0, index - half), min(volume.shape[0], index + half + 1)
    return volume[low:high].astype(np.float64), index - low


def white_noise(shape: tuple[int, ...], sigma_hu: float, seed: int) -> np.ndarray:
    return sigma_hu * np.random.default_rng(seed).standard_normal(shape)


def rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(values**2))) if values.size else float("nan")


def tradeoff(reference: np.ndarray, filtered_reference: np.ndarray, filtered_noisy: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    """Split the error of a linear filter into what it does to the structure and the noise that is left (see module docstring)."""
    blur = (filtered_reference - reference)[mask]
    left = (filtered_noisy - filtered_reference)[mask]
    return {"blur_rmse_hu": rms(blur), "residual_noise_hu": rms(left), "cross_term_hu2": float(2.0 * np.mean(blur * left)) if blur.size else float("nan")}


def region_masks(reference_slice: np.ndarray) -> dict[str, np.ndarray]:
    """The masks of one slice, all computed from the clean reference only."""
    masks = b2.reference_masks(reference_slice)
    soft = b2.soft_tissue_region(reference_slice)
    masks["soft"] = soft if int(soft.sum()) >= MIN_SOFT_PIXELS else np.zeros_like(soft)
    return masks


class SlabCase:
    """One slice of the reference with its slab, its masks and one noise realisation."""

    def __init__(self, volume: np.ndarray, index: int, sigma_hu: float, seed: int, masks: dict[str, np.ndarray]):
        self.index, self.seed, self.sigma_hu = index, seed, sigma_hu
        self.reference_slab, self.center = extract_slab(volume, index)
        self.valid = self.reference_slab > b2.PADDING_HU        # inside the field of view, known from the reference
        self.noisy_slab = self.reference_slab + white_noise(self.reference_slab.shape, sigma_hu, seed)
        self.reference, self.noisy = self.reference_slab[self.center], self.noisy_slab[self.center]
        self.masks = masks
        self.v2_case = b2.Case(self.reference, self.noisy, masks["main"], masks["inner"])


class ReferenceCache:
    """What does not depend on the noise, once per (slice, parameter set): the smoothed reference slice and the window weights."""

    def __init__(self, volume: np.ndarray, spacing: tuple[float, float, float]):
        self.volume, self.spacing, self._store = volume, spacing, {}

    def get(self, index: int, params: dict) -> tuple[np.ndarray, np.ndarray]:
        key = (index, params["sigma_xy_mm"], params["sigma_z_mm"])
        if key not in self._store:
            slab, centre = extract_slab(self.volume, index)
            valid = slab > b2.PADDING_HU
            weights = valid_weights(valid, params, self.spacing)
            self._store[key] = (smooth(slab, params, self.spacing, valid, weights)[centre], weights)
        return self._store[key]


def _add_split(results: dict, case: SlabCase, filtered_reference: np.ndarray, filtered: np.ndarray) -> dict:
    for name in ALL_REGIONS:
        if name in REGIONS:
            mask = case.masks[name]
            rmse, mae = b2.hu_errors(case.reference, filtered, mask) if mask.any() else (float("nan"), float("nan"))
            results[name] = {"RMSE_HU": rmse, "MAE_HU": mae}
        results[name].update(tradeoff(case.reference, filtered_reference, filtered, case.masks[name]))
    return results


def evaluate_config(case: SlabCase, params: dict, spacing: tuple[float, float, float], cache: ReferenceCache, full: bool) -> dict[str, dict[str, float]]:
    """Metrics of one parameter set on one case, per region: HU errors and the error split; ``full`` adds PSNR and SSIM for the masks."""
    filtered_reference, weights = cache.get(case.index, params)
    filtered = smooth(case.noisy_slab, params, spacing, case.valid, weights)[case.center]
    if full:
        results = b2.evaluate_masks(case.v2_case, filtered, MASKS)
    else:
        results = {m: dict(zip(("RMSE_HU", "MAE_HU"), b2.hu_errors(case.reference, filtered, case.masks[m]))) for m in MASKS}
    return _add_split(results, case, filtered_reference, filtered)


def evaluate_baseline(case: SlabCase) -> dict[str, dict[str, float]]:
    return _add_split(b2.evaluate_masks(case.v2_case, case.noisy, MASKS), case, case.reference, case.noisy)


# --- tuning and testing ----------------------------------------------------------------------------------


def plan_slices(volume: np.ndarray, n_tune: int = 3, n_test: int = 8, min_gap: int = HALF_SLAB) -> tuple[list[int], list[int]]:
    """Tuning and test slices: disjoint, at least ``min_gap`` apart, both inside the eligible (lung-bearing) range."""
    return b2.split_slices(b2.eligible_slices(volume), n_tune, n_test, min_gap)


def select_parameters(volume: np.ndarray, spacing, tune_slices: list[int], repeats: int, masks_by_slice: dict, cache: ReferenceCache) -> tuple[pd.DataFrame, dict]:
    """Score every grid point of every method on the tuning cases; keep the best per (condition, method) by RMSE_HU on the primary mask."""
    rows = []
    grid = method_grid()
    for condition_index, sigma_hu in enumerate(NOISE_SIGMAS_HU):
        cases = [SlabCase(volume, s, sigma_hu, b2.condition_seed(TUNING_BASE_SEED, s, condition_index, r), masks_by_slice[s])
                 for s in tune_slices for r in range(repeats)]
        for method, configs in grid.items():
            for params in configs:
                scored = [evaluate_config(case, params, spacing, cache, full=False) for case in cases]
                row = {"condition": f"white_{sigma_hu:g}HU", "method": method, "params": json.dumps(params, sort_keys=True), "n_tuning_cases": len(cases)}
                for region in ALL_REGIONS:
                    for key in ("RMSE_HU", "blur_rmse_hu", "residual_noise_hu"):
                        row[f"{key}_{region}"] = b2._mean_or_nan(np.array([s[region][key] for s in scored]))
                rows.append(row)
    table = pd.DataFrame(rows)
    selected = {}
    for (condition, method), group in table.groupby(["condition", "method"], sort=False):
        best = group.loc[group[f"RMSE_HU_{PRIMARY_MASK}"].idxmin()]
        selected[(condition, method)] = json.loads(best["params"])
    return table, selected


def evaluate_selected(volume: np.ndarray, spacing, test_slices: list[int], repeats: int, masks_by_slice: dict, cache: ReferenceCache, selected: dict) -> pd.DataFrame:
    rows = []
    for condition_index, sigma_hu in enumerate(NOISE_SIGMAS_HU):
        condition = f"white_{sigma_hu:g}HU"
        for index in test_slices:
            for repeat in range(repeats):
                seed = b2.condition_seed(TEST_BASE_SEED, index, condition_index, repeat)
                case = SlabCase(volume, index, sigma_hu, seed, masks_by_slice[index])
                outputs = {BASELINE: ({}, evaluate_baseline(case))}
                for method in METHODS:
                    params = selected[(condition, method)]
                    outputs[method] = (params, evaluate_config(case, params, spacing, cache, full=True))
                for method, (params, per_region) in outputs.items():
                    for region, metrics in per_region.items():
                        rows.append({"condition": condition, "mask": region, "slice": index, "repeat": repeat + 1, "seed": seed, "method": method,
                                     "params": json.dumps(params, sort_keys=True), "mask_pixels": int(case.masks[region].sum()), **metrics})
    return pd.DataFrame(rows)


# --- summaries -------------------------------------------------------------------------------------------


def per_slice_means(per_run: pd.DataFrame) -> pd.DataFrame:
    keys = ["condition", "mask", "slice", "method"]
    return per_run.groupby(keys, as_index=False, sort=False).agg(**{m: (m, "mean") for m in SUMMARY_METRICS}, n_repeats=("repeat", "size"))


def summarise(per_slice: pd.DataFrame, n_boot: int) -> pd.DataFrame:
    rows = []
    for (condition, mask, method), group in per_slice.groupby(["condition", "mask", "method"], sort=False):
        row = {"condition": condition, "mask": mask, "method": method, "n_slices": int(len(group))}
        for metric in SUMMARY_METRICS:
            values = group.sort_values("slice")[metric].to_numpy()
            low, high = b2.bootstrap_ci(values, n_boot, seed=BOOTSTRAP_SEED)
            row[f"{metric}_mean"], row[f"{metric}_ci_low"], row[f"{metric}_ci_high"] = b2._mean_or_nan(values), low, high
        rows.append(row)
    return pd.DataFrame(rows)


def pairwise(per_slice: pd.DataFrame, n_boot: int) -> pd.DataFrame:
    """Paired (same slice) differences A - B with a bootstrap interval over slices."""
    rows = []
    for (condition, mask), group in per_slice.groupby(["condition", "mask"], sort=False):
        for a, b in PAIRS:
            for metric in PAIR_METRICS:
                wide = group.pivot(index="slice", columns="method", values=metric)
                diff = (wide[a] - wide[b]).to_numpy()
                low, high = b2.bootstrap_ci(diff, n_boot, seed=BOOTSTRAP_SEED)
                rows.append({"condition": condition, "mask": mask, "metric": metric, "A": a, "B": b, "mean_A_minus_B": b2._mean_or_nan(diff),
                             "ci_low": low, "ci_high": high, "n_slices": int(np.isfinite(diff).sum())})
    return pd.DataFrame(rows)


def run(volume: np.ndarray, spacing, tune_slices: list[int], test_slices: list[int], tune_repeats: int, test_repeats: int, n_boot: int,
        log=lambda message: None) -> dict[str, pd.DataFrame]:
    if set(tune_slices) & set(test_slices):
        raise ValueError("Tuning and test slices must be disjoint.")
    masks_by_slice = {i: region_masks(volume[i].astype(np.float64)) for i in sorted({*tune_slices, *test_slices})}
    cache = ReferenceCache(volume, spacing)
    tuning, selected = select_parameters(volume, spacing, tune_slices, tune_repeats, masks_by_slice, cache)
    log(f"tuned on slices {tune_slices}: {len(tuning)} grid points")
    selection = pd.DataFrame([{"condition": c, "method": m, "params": json.dumps(p, sort_keys=True)} for (c, m), p in selected.items()])
    per_run = evaluate_selected(volume, spacing, test_slices, test_repeats, masks_by_slice, cache, selected)
    log(f"evaluated on slices {test_slices}: {len(per_run)} rows")
    per_slice = per_slice_means(per_run)
    return {"tuning_grid": tuning, "selected_parameters": selection, "test_per_run": per_run, "test_per_slice": per_slice,
            "test_summary": summarise(per_slice, n_boot), "test_pairwise": pairwise(per_slice, n_boot)}


# --- figures ---------------------------------------------------------------------------------------------


def make_figures(tables: dict[str, pd.DataFrame], out_dir: Path) -> list[Path]:
    """Two figures drawn from the tables only: the noise/structure trade-off curves and the held-out errors with intervals."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    colours = {METHODS[0]: "#1b6ca8", METHODS[1]: "#c0392b", METHODS[2]: "#2e8b57"}
    grid = tables["tuning_grid"]
    selection = tables["selected_parameters"].set_index(["condition", "method"])["params"]
    conditions = [f"white_{s:g}HU" for s in NOISE_SIGMAS_HU]

    fig, axes = plt.subplots(2, 3, figsize=(15, 9.2))
    rows_spec = (("main", "principal mask (lung boundaries included)"), ("soft", "homogeneous soft tissue"))
    for row_axes, (region, label) in zip(axes, rows_spec):
        for axis, condition in zip(row_axes, conditions):
            sub = grid[grid["condition"] == condition]
            sigma = float(condition.split("_")[1].removesuffix("HU"))
            blur, left = f"blur_rmse_hu_{region}", f"residual_noise_hu_{region}"
            limit = 1.2 * sigma                      # the region where a filter is not worse than doing nothing, plus a margin
            for fraction in (0.25, 0.5, 0.75, 1.0):
                axis.add_patch(plt.Circle((0, 0), fraction * sigma, fill=False, ls=":", lw=0.7, color="grey"))
                axis.text(fraction * sigma / np.sqrt(2), fraction * sigma / np.sqrt(2), f"RMSE {fraction * sigma:g}", fontsize=6, color="grey")
            for method in METHODS:
                part = sub[sub["method"] == method]
                if method == METHODS[2]:
                    axis.scatter(part[blur], part[left], s=12, alpha=0.4, color=colours[method], label=method)
                else:
                    axis.plot(part[blur], part[left], "o-", ms=3.5, lw=1.1, color=colours[method], label=method)
                best = json.loads(selection[(condition, method)])
                chosen = part[part["params"] == json.dumps(best, sort_keys=True)].iloc[0]
                axis.scatter([chosen[blur]], [chosen[left]], s=120, facecolors="none", edgecolors=colours[method], lw=2)
            axis.scatter([0], [sigma], marker="x", color="black", label="unfiltered")
            axis.set_xlim(0, limit)
            axis.set_ylim(0, limit)
            axis.set_aspect("equal")
            axis.set_xlabel("structure change: RMS of f(reference) - reference (HU)")
            axis.set_ylabel("residual noise: RMS of f(noise) (HU)")
            axis.set_title(f"noise sigma {sigma:g} HU - {label}", fontsize=8.5)
    axes[0][0].legend(fontsize=7, loc="upper right")
    fig.suptitle("Trade-off of Gaussian smoothing on the tuning slices: dotted arcs are lines of equal RMSE (HU); large circles mark the tuned setting of each method; the cross is the unfiltered image", fontsize=10)
    fig.tight_layout()
    first = out_dir / "tradeoff_curves.png"
    fig.savefig(first, dpi=150)
    plt.close(fig)

    summary = tables["test_summary"]
    summary = summary[summary["mask"] == PRIMARY_MASK]
    fig, axis = plt.subplots(figsize=(8.5, 4.6))
    labels = [BASELINE, *METHODS]
    width = 0.2
    for k, method in enumerate(labels):
        rows = [summary[(summary["condition"] == c) & (summary["method"] == method)].iloc[0] for c in conditions]
        means = np.array([r["RMSE_HU_mean"] for r in rows])
        errors = np.array([[r["RMSE_HU_mean"] - r["RMSE_HU_ci_low"] for r in rows], [r["RMSE_HU_ci_high"] - r["RMSE_HU_mean"] for r in rows]])
        bars = axis.bar(np.arange(3) + (k - 1.5) * width, means, width, yerr=errors, capsize=2, label=method, color=colours.get(method, "#999999"))
        axis.bar_label(bars, fmt="%.1f", fontsize=7, padding=2)
    axis.set_xticks(range(3))
    axis.set_xticklabels([f"sigma {s:g} HU" for s in NOISE_SIGMAS_HU])
    axis.set_ylabel("RMSE_HU on the held-out slices (principal mask)")
    axis.set_title("Held-out error, mean and 95% bootstrap interval over 8 slices of one patient", fontsize=10)
    axis.legend(fontsize=8)
    fig.tight_layout()
    second = out_dir / "test_rmse.png"
    fig.savefig(second, dpi=150)
    plt.close(fig)
    return [first, second]


# --- command line ----------------------------------------------------------------------------------------


SOURCE_FILES = ("benchmark_3d.py", "benchmark_v2.py", "src/dicom_volume.py", "requirements.txt")
LIMITATIONS = ("Synthetic white noise that is independent between voxels and between slices (more favourable to smoothing across slices than real "
               "CT noise); noisy clinical reference; one patient, 8 test slices; Gaussian smoothing only; no clinical meaning.")


def main(argv: list[str] | None = None) -> None:
    from src.dicom_volume import load_dicom_volume

    parser = argparse.ArgumentParser(description="Benchmark 3D: slice-wise versus volumetric Gaussian smoothing under synthetic noise.")
    parser.add_argument("--dicom-series", type=Path, required=True, help="Directory of ONE CT DICOM series (local data only).")
    parser.add_argument("--out", type=Path, required=True, help="Output directory outside the repository, e.g. ../../benchmark_3d_<date>.")
    parser.add_argument("--tune-repeats", type=int, default=2)
    parser.add_argument("--test-repeats", type=int, default=5)
    parser.add_argument("--n-boot", type=int, default=10000)
    parser.add_argument("--allow-inside-repo", action="store_true")
    parser.add_argument("--plan-only", action="store_true", help="Print the slice selection and exit.")
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parent.parent
    b2.ensure_outside_repository(args.out, repo, args.allow_inside_repo)
    b2.require_hounsfield_series(args.dicom_series)
    volume, spacing, _origin, _direction = load_dicom_volume(args.dicom_series)
    tune_slices, test_slices = plan_slices(volume)
    print(f"series: {args.dicom_series.name} | volume {volume.shape} | spacing (x,y,z) mm {spacing}")
    print(f"tuning slices: {tune_slices} | test slices: {test_slices} | slab half-width {HALF_SLAB} slices")
    if args.plan_only:
        return
    tables = run(volume, spacing, tune_slices, test_slices, args.tune_repeats, args.test_repeats, args.n_boot, log=print)
    out = args.out
    figures = make_figures(tables, out)
    metadata = {
        "schema_version": SCHEMA_VERSION, "benchmark": "3D smoothing: slice-wise versus volumetric", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": b2.git_state(repo), "series_directory_name": args.dicom_series.name, "volume_shape_zyx": list(volume.shape), "voxel_spacing_xyz_mm": list(spacing),
        "parameters": {"tune_slices": tune_slices, "test_slices": test_slices, "min_gap_slices": HALF_SLAB, "half_slab": HALF_SLAB, "noise_sigmas_hu": list(NOISE_SIGMAS_HU),
                       "tune_repeats": args.tune_repeats, "test_repeats": args.test_repeats, "tune_base_seed": TUNING_BASE_SEED, "test_base_seed": TEST_BASE_SEED,
                       "n_boot": args.n_boot, "bootstrap_seed": BOOTSTRAP_SEED, "primary_mask": PRIMARY_MASK, "selection_criterion": "RMSE_HU",
                       "grids_mm": method_grid(), "display_window": [b2.DISPLAY_WINDOW_CENTER, b2.DISPLAY_WINDOW_WIDTH], "inner_margin_px": b2.INNER_MARGIN_PX,
                       "body_threshold_hu": b2.BODY_THRESHOLD_HU, "padding_hu": b2.PADDING_HU, "soft_tissue_hu": list(b2.SOFT_TISSUE_HU),
                       "soft_tissue_erosion_px": b2.SOFT_TISSUE_EROSION_PX, "min_soft_pixels": MIN_SOFT_PIXELS,
                       "gaussian_truncate": 4.0, "boundary_mode": "reflect", "padding_handling": "normalised convolution over voxels above padding_hu"},
        "dicom_conversion": b2.dicom_conversion_facts(args.dicom_series), "packages": b2.package_versions(),
        "source_files_sha256": b2.source_file_hashes(Path(__file__).resolve().parent, SOURCE_FILES), "source_files_hash_rule": b2.SOURCE_HASH_RULE,
        "input_series": b2.series_input_record(args.dicom_series), "limitations": LIMITATIONS,
        "figures_sha256": {p.name: b2.sha256_of(p) for p in figures},
    }
    paths = b2.write_outputs(tables, out, metadata)
    print("written:", ", ".join(sorted(p.name for p in paths.values())), "+ run_metadata.json +", ", ".join(p.name for p in figures), "->", out)


if __name__ == "__main__":
    main()
