"""Benchmark 3D with noise that is correlated between neighbouring slices.

Companion of ``benchmark_3d.py`` (imported unchanged, so the recorded run of that script stays tied to its source hash). Same question, same
protocol, same grids, slices and seed bases; only the added noise differs. ``benchmark_3d.py`` adds white noise that is independent between
slices, which favours smoothing across slices. On the series used here the real noise is partly correlated between adjacent slices
(``python diagnostics.py noise-texture``: correlation of a high-pass residual about +0.29 for adjacent slices and about 0 two slices apart), so
this script repeats the experiment with that property.

Noise model. Independent white noise ``e`` is drawn for every voxel, with one extra slice, and the noise of slice k is
``(e[k] + c * e[k + 1]) / sqrt(1 + c**2)``. It has the requested standard deviation in every voxel, is white inside a slice, correlated
with the next slice with coefficient ``c / (1 + c**2)`` (the requested ``--correlation``) and independent beyond. The largest coefficient this
construction can give is 0.5. It models the one property measured on the series; it does not model the in-plane texture or the noise power
spectrum of a scanner and is not a validated CT noise model.

    python benchmark_3d_correlated.py --dicom-series "path/to/LIDC-IDRI-0709/<series folder>" --out "path/outside/repo/benchmark_3d_correlated_run"
"""

from __future__ import annotations

import argparse
import contextlib
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import benchmark_3d as b3
import benchmark_v2 as b2

SCHEMA_VERSION = 1
ADJACENT_SLICE_CORRELATION = 0.3
SOURCE_FILES = ("benchmark_3d_correlated.py", *b3.SOURCE_FILES)
LIMITATIONS = ("Synthetic noise: white inside each slice and correlated only with the adjacent slice (a model of one measured property, not of a scanner); "
               "noisy clinical reference; one patient, 8 test slices; Gaussian smoothing only; no clinical meaning.")


def mixing_weight(correlation: float) -> float:
    """Weight ``c`` of the next slice such that ``c / (1 + c**2) == correlation`` (the smaller root; correlation must lie in [0, 0.5])."""
    if not 0.0 <= correlation <= 0.5:
        raise ValueError("The correlation between adjacent slices must lie in [0, 0.5] for this construction.")
    return 0.0 if correlation == 0.0 else (1.0 - math.sqrt(max(0.0, 1.0 - 4.0 * correlation**2))) / (2.0 * correlation)


def slice_correlated_noise(shape: tuple[int, ...], sigma_hu: float, seed: int, correlation: float = ADJACENT_SLICE_CORRELATION) -> np.ndarray:
    """Noise of shape ``(slices, rows, columns)``: standard deviation ``sigma_hu`` everywhere, ``correlation`` between adjacent slices, 0 beyond."""
    if len(shape) != 3 or min(shape) < 1:
        raise ValueError("shape must be (slices, rows, columns) with positive sizes.")
    if not np.isfinite(sigma_hu) or sigma_hu < 0:
        raise ValueError("sigma_hu must be finite and non-negative.")
    c = mixing_weight(correlation)
    drawn = np.random.default_rng(seed).standard_normal((shape[0] + 1, *shape[1:]))
    return sigma_hu * (drawn[:-1] + c * drawn[1:]) / math.sqrt(1.0 + c * c)


@contextlib.contextmanager
def correlated_noise(correlation: float = ADJACENT_SLICE_CORRELATION):
    """Within the block, ``benchmark_3d`` adds slice-correlated noise instead of independent noise; the original generator is always restored."""
    mixing_weight(correlation)                       # validate before touching the module
    original = b3.white_noise
    b3.white_noise = lambda shape, sigma_hu, seed: slice_correlated_noise(shape, sigma_hu, seed, correlation)
    try:
        yield
    finally:
        b3.white_noise = original


def run_experiment(volume: np.ndarray, spacing, tune_slices: list[int], test_slices: list[int], tune_repeats: int, test_repeats: int, n_boot: int,
                   correlation: float = ADJACENT_SLICE_CORRELATION, log=lambda message: None) -> dict:
    """``benchmark_3d.run`` with slice-correlated noise; the tables have the same layout as those of ``benchmark_3d.py``."""
    with correlated_noise(correlation):
        return b3.run(volume, spacing, tune_slices, test_slices, tune_repeats, test_repeats, n_boot, log=log)


def main(argv: list[str] | None = None) -> None:
    from src.dicom_volume import load_dicom_volume

    parser = argparse.ArgumentParser(description="Benchmark 3D with noise correlated between adjacent slices.")
    parser.add_argument("--dicom-series", type=Path, required=True, help="Directory of ONE CT DICOM series (local data only).")
    parser.add_argument("--out", type=Path, required=True, help="Output directory outside the repository.")
    parser.add_argument("--correlation", type=float, default=ADJACENT_SLICE_CORRELATION, help="Correlation of the noise of adjacent slices, 0 to 0.5 (default 0.3).")
    parser.add_argument("--tune-repeats", type=int, default=2)
    parser.add_argument("--test-repeats", type=int, default=5)
    parser.add_argument("--n-boot", type=int, default=10000)
    parser.add_argument("--allow-inside-repo", action="store_true")
    parser.add_argument("--plan-only", action="store_true", help="Print the slice selection and exit.")
    args = parser.parse_args(argv)
    mixing_weight(args.correlation)

    repo = Path(__file__).resolve().parent.parent
    b2.ensure_outside_repository(args.out, repo, args.allow_inside_repo)
    b2.require_hounsfield_series(args.dicom_series)
    volume, spacing, _origin, _direction = load_dicom_volume(args.dicom_series)
    tune_slices, test_slices = b3.plan_slices(volume)
    print(f"series: {args.dicom_series.name} | volume {volume.shape} | spacing (x,y,z) mm {spacing}")
    print(f"tuning slices: {tune_slices} | test slices: {test_slices} | slab half-width {b3.HALF_SLAB} slices | adjacent-slice noise correlation {args.correlation}")
    if args.plan_only:
        return
    tables = run_experiment(volume, spacing, tune_slices, test_slices, args.tune_repeats, args.test_repeats, args.n_boot, args.correlation, log=print)
    figures = b3.make_figures(tables, args.out)
    metadata = {
        "schema_version": SCHEMA_VERSION, "benchmark": "3D smoothing: slice-wise versus volumetric, noise correlated between adjacent slices",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": b2.git_state(repo),
        "series_directory_name": args.dicom_series.name, "volume_shape_zyx": list(volume.shape), "voxel_spacing_xyz_mm": list(spacing),
        "parameters": {"tune_slices": tune_slices, "test_slices": test_slices, "min_gap_slices": b3.HALF_SLAB, "half_slab": b3.HALF_SLAB,
                       "noise_sigmas_hu": list(b3.NOISE_SIGMAS_HU), "tune_repeats": args.tune_repeats, "test_repeats": args.test_repeats,
                       "tune_base_seed": b3.TUNING_BASE_SEED, "test_base_seed": b3.TEST_BASE_SEED, "n_boot": args.n_boot, "bootstrap_seed": b3.BOOTSTRAP_SEED,
                       "primary_mask": b3.PRIMARY_MASK, "selection_criterion": "RMSE_HU", "grids_mm": b3.method_grid(),
                       "display_window": [b2.DISPLAY_WINDOW_CENTER, b2.DISPLAY_WINDOW_WIDTH], "inner_margin_px": b2.INNER_MARGIN_PX,
                       "body_threshold_hu": b2.BODY_THRESHOLD_HU, "padding_hu": b2.PADDING_HU, "soft_tissue_hu": list(b2.SOFT_TISSUE_HU),
                       "soft_tissue_erosion_px": b2.SOFT_TISSUE_EROSION_PX, "min_soft_pixels": b3.MIN_SOFT_PIXELS, "gaussian_truncate": 4.0,
                       "boundary_mode": "reflect", "padding_handling": "normalised convolution over voxels above padding_hu",
                       "noise_model": {"kind": "white inside a slice, correlated with the adjacent slice", "adjacent_slice_correlation": args.correlation,
                                       "mixing_weight": mixing_weight(args.correlation),
                                       "construction": "noise[k] = (e[k] + c * e[k + 1]) / sqrt(1 + c**2) with independent white e; correlation c / (1 + c**2) with the next slice, 0 beyond",
                                       "reference": "measured in this series with diagnostics.py noise-texture (high-pass residual, rough estimator)",
                                       "companion_of": "benchmark_3d.py (independent noise); same protocol, grids, slices and seed bases"}},
        "dicom_conversion": b2.dicom_conversion_facts(args.dicom_series), "packages": b2.package_versions(),
        "source_files_sha256": b2.source_file_hashes(Path(__file__).resolve().parent, SOURCE_FILES), "source_files_hash_rule": b2.SOURCE_HASH_RULE,
        "input_series": b2.series_input_record(args.dicom_series), "limitations": LIMITATIONS,
        "figures_sha256": {p.name: b2.sha256_of(p) for p in figures},
    }
    paths = b2.write_outputs(tables, args.out, metadata)
    print("written:", ", ".join(sorted(p.name for p in paths.values())), "+ run_metadata.json +", ", ".join(p.name for p in figures), "->", args.out)


if __name__ == "__main__":
    main()
