# Benchmark V2: nine classical denoisers on one CT series (full description)

This is the complete write-up of the recorded run `backend/docs/results/benchmark_v2_methods_2026-10-25`. The repository README gives the summary. Code: `backend/benchmark_v2.py`; tests: `backend/test_benchmark_v2.py`, `backend/test_benchmark_methods.py`, `backend/test_shipped_runs.py`.

> **Status: exploratory, partly reproducible comparison study.** It compares nine classical denoisers under *synthetic* noise on a *single* CT series. It does not show that any filter is best in general, has no clinical validation, and is not an independent external validation.

## Question and workflow

When synthetic noise of a stated size is added to a CT slice, how closely do filtered results return to the original slice, and how much does that depend on the method, its setting, the image region and the metric?

1. Load one DICOM series and convert it to Hounsfield units (HU) with the modality rescale.
2. Fix two evaluation masks per slice from the original slice, before any noise exists.
3. Add synthetic noise in HU for 8 noise conditions, with reproducible seeds.
4. **Tuning:** for each noise condition and method, choose one setting on 3 tuning slices (RMSE_HU on the principal mask only).
5. **Test:** apply that frozen setting to 8 other slices (5 noise realisations each); report means with bootstrap intervals over slices.
6. Compare the methods with each other and with the unfiltered noisy image.

## Data and reference

- One local series labelled `LIDC-IDRI-0709` in its DICOM headers (100 slices, 512 × 512, 0.54 × 0.54 mm, 3.0 mm slice spacing, convolution kernel `FC01`); its folder carries the LIDC-IDRI licence text (CC BY 3.0). The series agrees with TCIA's public record for it on every field compared (UIDs, modality, scanner, software version, image count, total size of the 100 files), but **its files were not hashed against a fresh download, so file-level identity with the public release has not been verified.** The run records the series UID and a SHA-256 manifest of its 101 files, so anyone can compare their copy. The data are not part of this repository. Citation: Armato SG III et al., *Data From LIDC-IDRI*, TCIA, DOI [10.7937/K9/TCIA.2015.LO9QL9SX](https://doi.org/10.7937/K9/TCIA.2015.LO9QL9SX) (resolves to the TCIA collection page); Clark K et al., *J Digit Imaging* 2013;26:1045.
- **The reference is not clean ground truth.** It is a real, already-reconstructed clinical slice with its own noise, and the synthetic noise is added to it. A rough white-noise-equivalent estimate of the reference's own high-frequency noise is about 3 HU (2.7 to 4.2 HU over the 11 slices), but CT noise is correlated, so that is a lower bound; estimates of the image's noise differ by an order of magnitude depending on the definition. Errors measure the difference from this slice, not accuracy against the true anatomy.

## Methods, noise, masks, metrics

Nine methods: the six original filters (mean, median, Gaussian, and the FFT ideal, Gaussian and Butterworth low-pass) and three added ones (bilateral, non-local means, wavelet BayesShrink). Eight noise conditions, all added in HU: white Gaussian noise (10, 25, 50 HU), "correlated" noise (white noise smoothed by a 1-pixel Gaussian and renormalised; **an unvalidated construction**), and two robustness tests that are *not* CT noise models (2 % salt-and-pepper, multiplicative speckle). Noise levels are scenarios, not measurements of a scanner, and no source was found that would support calling them typical.

The *principal* mask is the largest body region above −500 HU. The *inner* mask removes everything within 10 px of the scanner padding; it is an experimental sensitivity choice, not clinically validated. Metrics: RMSE_HU and MAE_HU (HU, unclipped, over the mask); PSNR and SSIM on images displayed with a −600/1500 HU window (clipped to [0, 1]), SSIM averaged over windows fully inside the mask. Definitions and what each metric cannot show are in [methods_and_decisions.md](methods_and_decisions.md).

## What the recorded run shows (illustration, not a ranking)

The run `backend/docs/results/benchmark_v2_methods_2026-10-25` (grid `methods`; the six original filters plus bilateral, non-local means and wavelet BayesShrink). Mean test RMSE_HU over 8 slices with the 95 % bootstrap interval over slices, principal mask (lowest of the nine in bold):

| Condition | Unfiltered | Best of the six original filters | Bilateral | Non-local means | Wavelet BayesShrink |
|---|---|---|---|---|---|
| white 10 HU | 10.00 [9.99, 10.00] | 9.80 [9.78, 9.81] (FFT Gaussian) | 8.13 [8.01, 8.27] | 7.85 [7.64, 8.12] | **6.68 [6.45, 6.97]** |
| white 25 HU | 25.00 [24.99, 25.02] | 15.23 [14.82, 15.64] (Median) | 14.56 [13.98, 15.01] | 13.36 [12.94, 13.72] | **12.49 [11.98, 13.30]** |
| white 50 HU | 49.98 [49.96, 50.01] | 24.37 [23.98, 24.69] (Median) | 20.80 [19.78, 21.63] | **19.89 [18.93, 20.63]** | 20.99 [20.79, 21.20] |
| correlated 10 HU | 10.00 [10.00, 10.01] | 10.00 [9.99, 10.00] (Gaussian) | 9.46 [9.40, 9.54] | **9.35 [9.27, 9.45]** | 9.78 [9.73, 9.83] |
| correlated 25 HU | 25.02 [24.99, 25.05] | 22.50 [22.27, 22.74] (Median) | 20.02 [19.65, 20.31] | **18.31 [17.76, 18.75]** | 22.57 [22.48, 22.70] |
| correlated 50 HU | 49.89 [49.87, 49.92] | 36.78 [35.86, 37.51] (Median) | 34.39 [33.76, 34.89] | **29.71 [28.66, 30.48]** | 44.63 [44.17, 45.19] |
| salt-and-pepper 2 % (robustness) | 130.74 [127.82, 133.95] | **13.62 [13.22, 14.05]** (Median) | 45.68 [44.23, 47.43] | 46.82 [44.06, 49.37] | 56.28 [54.04, 59.04] |
| speckle (robustness) | 119.19 [110.77, 128.67] | 40.17 [38.99, 41.56] (Median) | **35.69 [34.66, 36.98]** | 39.04 [36.49, 41.75] | 44.68 [43.39, 46.47] |

Paired over the same 8 slices, the added filter minus the best of the six original filters (negative = lower error; "lower" or "higher" only when the whole interval is on one side of zero):

| Condition | Bilateral | Non-local means | Wavelet BayesShrink |
|---|---|---|---|
| white 10 HU | −1.67 [−1.80, −1.51] lower | −1.94 [−2.17, −1.67] lower | −3.11 [−3.35, −2.82] lower |
| white 25 HU | −0.67 [−0.94, −0.42] lower | −1.87 [−2.03, −1.71] lower | −2.74 [−3.18, −2.15] lower |
| white 50 HU | −3.57 [−4.25, −2.98] lower | −4.48 [−5.08, −3.99] lower | −3.38 [−3.63, −3.12] lower |
| correlated 10 HU | −0.53 [−0.59, −0.46] lower | −0.65 [−0.73, −0.54] lower | −0.22 [−0.26, −0.16] lower |
| correlated 25 HU | −2.49 [−2.66, −2.33] lower | −4.20 [−4.53, −3.93] lower | +0.07 [−0.10, +0.25] unresolved |
| correlated 50 HU | −2.39 [−2.72, −2.05] lower | −7.07 [−7.28, −6.85] lower | +7.85 [+7.16, +8.62] higher |
| salt-and-pepper 2 % | +32.06 [+30.87, +33.55] higher | +33.21 [+30.67, +35.41] higher | +42.66 [+40.47, +45.44] higher |
| speckle | −4.49 [−4.75, −4.22] lower | −1.13 [−3.39, +0.62] unresolved | +4.51 [+3.04, +6.21] higher |

**How to read this.**

- Over the 8 conditions the added filters had a lower RMSE_HU than the best original filter in 7 (bilateral), 6 (non-local means) and 4 (wavelet) of them, with an interval entirely below zero. The pattern is consistent with what each method assumes (an interpretation; it was not tested separately): wavelet shrinkage, which models white Gaussian noise, is best on white noise at 10 and 25 HU and clearly worse on strongly correlated noise and on impulse noise; non-local means is lowest on correlated noise; bilateral is lowest on speckle; the median filter remains by far the best on salt-and-pepper noise.
- The lowest-RMSE method is the same on the principal and the inner mask in 7 of the 8 conditions; the exception is white 50 HU (non-local means on the principal mask, wavelet on the inner mask). Both masks are shown on the dashboard. At 50 HU the tuned 3 × 3 mean filter looks almost useless on the principal mask (49.98 → 48.40 HU) and strongly useful on the inner mask (49.98 → 21.00 HU), which is the boundary effect described below.
- RMSE_HU and PSNR name the same family in all 8 conditions; SSIM names a different one in 2 (white 50 HU and correlated 10 HU: bilateral instead of non-local means). The tuning minimum of each added method lies strictly inside its grid in 23 of the 24 (method, condition) cases; the exception is bilateral on salt-and-pepper noise, at the strongest end of the grid, where the filter has become a Gaussian filter.
- The tuned "assumed noise level" of the wavelet filter and the bilateral intensity scale are larger than the true noise (for example 50 HU assumed for 25 HU white noise): they are strength controls, not noise estimates.
- **None of this shows that the denoised images are better for any clinical purpose.** The error is measured against a noisy reference; smoothing more strongly can remove small structures, and no structure-preservation measure was computed.

**Why the mask matters.** A 3-pixel band along the mask edge is about 2.3 % of the mask pixels, yet after mean or Gaussian smoothing its RMSE_HU is 228–284 HU, and in a worked example it carried 87–89 % of the squared HU error. Tuning on RMSE_HU over the principal mask is therefore largely a criterion about the body boundary: where "no filter" scored best, that means no smoothing lowered the boundary-dominated error, not that smoothing is useless for the rest of the image. Tuning on the inner mask would change the choice in 34 of 48 cells of the earlier six-filter run (tuning slices only).

**RMSE_HU, PSNR and SSIM can prefer different settings.** In the earlier six-filter run PSNR chose the same setting as RMSE_HU in 44 of 48 cases on the tuning slices, SSIM in only 6 of 48.

## Earlier comparison: extended grid versus first grid

The first six-filter run used a smaller grid without a "no filter" option; the extended grid adds one. Comparing the tuned results of the two on the 8 test slices (48 cells, filtered versus filtered):

| Metric (extended − first) | Mask | Better | Worse | Unresolved |
|---|---|---|---|---|
| RMSE_HU | principal (the tuning criterion) | **30** | 0 | 18 (same setting selected) |
| RMSE_HU | inner | 12 | **18** | 18 (same setting selected) |
| MAE_HU | principal | 15 | 15 | 18 (same setting selected) |
| PSNR | principal | 29 | 0 | 19 (18 same setting, 1 unresolved) |
| SSIM (primary) | principal | 7 | **23** | 18 (same setting selected) |

"30 better, 0 worse" holds only for RMSE_HU on the principal mask, the criterion the grids were tuned for, and it reverses on the inner mask and for SSIM. For RMSE_HU on the principal mask, 34 of 48 filtered cells are materially below the unfiltered image and none above, but the absence of increases is partly built in: "no filter" is part of the grid.

## Limits of the evidence

- **One CT series, 3 tuning and 8 test slices.** No generalisation across patients, scanners, doses or kernels is claimed; slices of one scan are not independent.
- **Test slices are not untouched.** The code keeps test data out of the selection (a test perturbs the test slices only and finds identical selections), but the test slices were looked at in earlier runs, and the three added methods were chosen after those results were known. Their grids were fixed from the tuning slices before any test slice was scored with them, and the run was executed once, but this is not an independent validation.
- **Bootstrap intervals** use 8 slices of one patient. Percentile bootstrap intervals from only 8 values tend to be too narrow. A simulation done during development found a coverage of about 79 to 89 % for the nominal 95 % (its script is not kept in the repository, so that figure cannot be reproduced from it); read the intervals as descriptive spread over slices. No correction for multiple comparisons was applied.
- **Fixed hyper-parameters.** Each method has one tuned strength; the others (bilateral spatial scale 1.5 px, non-local-means patch 5 and search distance 6, wavelet `sym4` with 3 levels) were fixed, not tuned, and the bilateral scale is a compromise between noise types. A differently configured method could rank differently.
- **Not comparable with the historical results** in `backend/docs/results/` (different noise, clipping before filtering, fixed settings, no split).
- **No small-structure, edge or texture measure** and no task-based (for example detectability) evaluation.
- **The comparator "best of the six original filters"** in the paired table is picked from the test means themselves. That selection is not accounted for in the intervals and slightly favours the original filters.
- **Equal effort was not given to every family.** The grids have 6 to 19 candidate settings per family, and the three added methods have extra fixed hyper-parameters.

## Provenance and reproduction

The shipped run `benchmark_v2_methods_2026-10-25` was produced on 2026-10-25 from a **clean clone of commit `0b1380b048d0`**. Its `run_metadata.json` records the commit (no `+dirty`), package versions (Python 3.12.15, NumPy 2.5.4, SciPy 1.18.1, scikit-image 0.26.0, PyWavelets 1.10.0, OpenCV 5.0.0, pandas 3.1.0, pydicom 3.0.2), the SHA-256 of the source files that define the run (line-ending independent), the series UID and a SHA-256 manifest of the 101 input files, all parameters and grids, seeds, and the SHA-256 of every result file. What was checked:

- Two full runs from two different clean commits (`2fe94f6` and `0b1380b`) gave **byte-identical** result files (all 12 CSVs). The first run's metadata was superseded because it held non-standard JSON (`NaN`) that browsers cannot parse; that defect was fixed and covered by tests before the shipped run was made.
- For the six original filters and the unfiltered baseline, every result table is **byte-identical** to the run recorded on 2026-10-24 (which came from an uncommitted working tree, `d788e0c` plus local changes), so the extension changed nothing for them.
- The 101 input-file hashes equal the manifest recorded on 2026-10-24. This shows the same local files were used; it does not show they are identical to the TCIA release.
- The dashboard recomputes images from the recorded seeds and the recomputed RMSE_HU matched the stored rows for the ten outputs in each of the three conditions spot-checked (to better than 10⁻⁴ HU).

This demonstrates reproducibility on this machine and series; it does not validate the results on other data or platforms.

**Code changes after the run.** Three of the source files recorded in `run_metadata.json` no longer have the recorded SHA-256: `benchmark_v2.py` and `filters.py` (commits `ba97f1a` and `74f5a1a`: shared constants moved into `filters.py` with the same values, JSON helper extended to NumPy integers and booleans, imports reordered, two unused variables removed, a help text) and `src/dicom_volume.py` (2026-10-26: refusal of a gantry tilt above 0.1 degree and of an unreadable `*.dcm` file, which used to be skipped silently). None of these changes is meant to alter results. **Checked on 2026-10-26** (the 24-minute run itself was not repeated): (1) the complete benchmark pipeline, with the grid `methods`, 1 tuning slice (54), 2 test slices (16 and 93), 1 realisation each, 8 noise conditions, was run once with the code of commit `0b1380b` and once with the current code on the same series and seeds: **all 12 result files are byte-identical**; (2) 60 recorded per-run rows of the shipped run (3 conditions, 2 slices, all families, repeat 1) were recomputed with the current code with a largest difference of 0.0, and the 80 bootstrap intervals and the README tables recompute exactly from the recorded files; (3) for this series the old and the new loader return identical arrays, spacing, origin and direction. This supports, but does not prove, that the recorded run would be reproduced by the current code; the full repetition remains the definitive check.

```bash
cd backend
python benchmark_v2.py --dicom-series "path/to/LIDC-IDRI-0709" --out "path/outside/repo/benchmark_v2_run" --plan-only
python benchmark_v2.py --dicom-series "path/to/LIDC-IDRI-0709" --out "path/outside/repo/benchmark_v2_run" --grid-version methods
```

Prerequisites not provided by this repository: a local copy of the LIDC-IDRI series (from TCIA, under its terms) and an output directory **outside** the repository (the script refuses to write inside it). `--grid-version expanded` (the default) and `v1` reproduce the six-filter runs. The command refuses a series that is not CT or has no modality rescale. The full `methods` run took about 24 minutes (1,430 s) on a 16-thread laptop while other work was running; the peak memory of the benchmark script itself was not measured.

## Dashboard (Benchmark V2 page)

The page shows run provenance and CSV integrity (SHA-256 against the recorded values), test metrics with intervals for both masks, change relative to the unfiltered image, tuned parameters (with a note on what each added method's tuned value means), cautious statements computed from the tables, and, when the server has the CT series (`CT_SERIES_DIR`), a slice viewer with window/level, noisy and filtered images or difference maps, mask outline, intensity profile and boundary-band versus deeper-region error. Slice images are recomputed from the recorded seed and the page states whether they reproduce the recorded rows. Nothing is displayed unless the API serves a real run. The server never accepts paths from the browser: runs are addressed by directory name, and only the configured series is read.
