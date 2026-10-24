# Biomedical Image Denoising and Benchmarking

A biomedical image-processing project for **comparing classical denoising methods** on grayscale images and CT slices. It combines controlled synthetic-noise experiments, PSNR/SSIM measurements, a Streamlit application, a React dashboard with a FastAPI backend, and optional 3D DICOM CT visualization.

> **Scope:** educational and experimental image processing only. This project is not a diagnostic system and has not been clinically validated.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/tests-pytest-informational)
![Interface](https://img.shields.io/badge/interface-Streamlit%20%2B%20React-6b8e23)

## What the project does

The project compares the output of several classical filters under controlled conditions. For the quantitative 2D experiments, a source image is kept as the reference, synthetic noise is added, and the filtered outputs are compared with that pre-noise reference.

- **Spatial filters:** mean, median, and Gaussian.
- **Frequency-domain filters:** ideal, Gaussian, and Butterworth low-pass filters using a 2D Fourier transform.
- **Synthetic noise models:** Gaussian, salt-and-pepper, and synthetic speckle.
- **Metrics:** peak signal-to-noise ratio (PSNR) and structural similarity index (SSIM).
- **Medical image handling:** grayscale images and DICOM CT slices, including modality rescaling and display windowing.
- **Optional 3D workflow:** validation and visualization of a consistent multi-slice DICOM CT series, with Gaussian smoothing specified in millimetres.

The project does **not** claim that one filter is best for every image or noise type. A higher PSNR or SSIM is a measure of similarity to the selected reference, not proof of improved diagnostic quality.

## Interfaces

### Streamlit application

Run the main application with `streamlit run app.py`. It includes a project overview, 2D denoising lab, 3D CT volume viewer, results/reports section, and a project guide.

### React dashboard and FastAPI

The `frontend/` directory contains a React + Vite interface. `api.py` provides the FastAPI endpoints used by the dashboard, and `api_v2.py` serves recorded benchmark V2 runs (tables, interpretation statements and slice images recomputed from the recorded seeds). The dashboard has five pages plus the **Benchmark V2** page described below. The existing Render configuration is in `render.yaml`; it has not been deployed or validated as part of this work.

The Streamlit application is the exploratory 2D/3D lab; the React dashboard is the main interface for the recorded benchmark. They share the same filter code and do not duplicate the benchmark views.

The deployed URLs and service names are deployment settings; changing the GitHub repository name does not automatically rename Render services. Check the live deployment separately before describing it as operational.

## How the comparison works

1. Load a grayscale image or a supported DICOM image/series.
2. For a controlled 2D experiment, add reproducible synthetic noise to the reference image.
3. Apply spatial and frequency-domain filters to the same noisy input.
4. Compare each result against the **same pre-noise reference** using PSNR and SSIM.
5. Inspect visual comparisons and summary tables, then interpret both metrics and visible detail.

For an uploaded image without a clean ground-truth counterpart, PSNR/SSIM cannot establish objective restoration accuracy. If no synthetic noise is added, similarity to the input is not evidence that the image has been denoised.

## Methods at a glance

| Method | Main characteristic | Trade-off to inspect |
| --- | --- | --- |
| Mean | Local averaging | Can blur edges and fine structures |
| Median | Non-linear neighbourhood filter | Often useful for impulse noise; effect depends on the image |
| Gaussian (spatial) | Weighted local smoothing | Reduces high-frequency variation but may blur detail |
| Ideal low-pass | Sharp frequency cutoff | Can introduce ringing around edges |
| Gaussian low-pass | Smooth frequency attenuation | Cutoff affects the balance between smoothing and detail |
| Butterworth low-pass | Adjustable frequency roll-off | Behaviour depends on cutoff and filter order |

## Repository structure

```text
.
├── backend/                        # Python code, tests, documentation assets (run commands from here)
│   ├── app.py                      # Streamlit interface
│   ├── api.py                      # FastAPI endpoints for the React dashboard
│   ├── api_v2.py                   # Read-only /api/v2 endpoints over recorded benchmark V2 runs
│   ├── benchmark_v2.py             # Benchmark V2 (HU-domain noise, tuning/test split, two masks)
│   ├── provenance.py               # Provenance label for result files
│   ├── filters.py                  # 2D image loading, noise, filters, and metrics
│   ├── evaluate_denoising.py       # Reproducible 2D CT benchmark
│   ├── download_data.py            # Local synthetic examples and optional downloads
│   ├── src/
│   │   ├── dicom_volume.py         # DICOM series validation and volume loading
│   │   ├── volume_denoising.py     # 3D Gaussian smoothing
│   │   └── ...                     # Additional visualization and evaluation modules
│   ├── test_*.py                   # Automated tests
│   ├── samples/                    # Small example images and a synthetic DICOM file
│   ├── docs/images/                # Selected figures for documentation
│   ├── docs/results/               # Validation notes and historical result snapshots
│   ├── docs/methods_and_decisions.md  # Methods, metric definitions, protocol, decision on deep learning
│   ├── requirements.txt            # Full development / Streamlit / test dependencies
│   └── requirements-api.txt        # Runtime dependencies of the hosted API
├── frontend/                       # React + Vite dashboard
├── render.yaml                     # Render deployment (API uses rootDir: backend)
└── .github/workflows/              # pytest and frontend build workflows
```

Local datasets (`backend/data/`) and generated outputs (`backend/reports/`, `backend/outputs/`) are ignored by Git.

## Setup

Unless stated otherwise, the Python commands below are run from the `backend/` directory. Python 3.10 or 3.12 is covered by the configured GitHub Actions matrix; other environments may work but are not covered by that workflow.

### 1. Create an environment and install dependencies

**Windows (Anaconda Prompt or Command Prompt):**

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**macOS/Linux:**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Generate local examples and launch Streamlit

```bash
python download_data.py --skip-kaggle --skip-dicom-test-files
streamlit run app.py
```

The example-generation command avoids the optional Kaggle and pydicom-fixture downloads. Optional external downloads have separate terms and are not required to run the basic interface.

### 3. Run the React dashboard locally

Keep the FastAPI process running in one terminal (from `backend/`):

```bash
python -m uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal (from the repository root):

```bash
cd frontend
npm install
npm run dev
```

The Vite development configuration proxies local `/api` requests to the FastAPI service. The hosted API has a `/api/health` endpoint. Live deployment availability has to be checked independently.

## Exploratory benchmark V2

> **Status: exploratory, partly reproducible comparison study.** It compares six classical smoothing filters under *synthetic* noise on a *single* CT series. It does not show that any filter is best in general, has no clinical validation, and is not an independent external validation.

### Question and workflow

When synthetic noise of a stated size is added to a CT slice, how closely do filtered results return to the original slice, and how much does that depend on the filter settings, the image region and the metric?

1. Load one DICOM series and convert it to Hounsfield units (HU) with the modality rescale.
2. Fix two evaluation masks per slice from the original slice, before any noise exists.
3. Add synthetic noise in HU for 8 noise conditions, with reproducible seeds.
4. **Tuning:** for each noise condition and filter family, choose one setting on 3 tuning slices (RMSE_HU on the principal mask only).
5. **Test:** apply that frozen setting to 8 other slices (5 noise realisations each); report means with bootstrap intervals over slices.
6. Compare the filters with each other and with the unfiltered noisy image.

### Data and reference

- One local series labelled `LIDC-IDRI-0709` in its DICOM headers (100 slices, 512 × 512, 0.54 × 0.54 mm, 3.0 mm slice spacing, convolution kernel `FC01`); its folder carries the LIDC-IDRI licence text (CC BY 3.0). **Whether the local files are identical to the public TCIA release has not been verified**; the run metadata identifies the series only by folder name. The data are not part of this repository. Citation: Armato SG III et al., *Data From LIDC-IDRI*, TCIA, DOI [10.7937/K9/TCIA.2015.LO9QL9SX](https://doi.org/10.7937/K9/TCIA.2015.LO9QL9SX) (resolves to the TCIA collection page).
- **The reference is not clean ground truth.** It is a real, already-reconstructed clinical slice with its own noise. Errors measure the difference from this slice, not accuracy against the true anatomy.

### Methods, noise, masks, metrics

Six filters: mean, median, Gaussian (spatial) and FFT ideal, Gaussian and Butterworth (order 2) low-pass. Eight noise conditions, all added in HU: white Gaussian noise (10, 25, 50 HU), "correlated" noise (white noise smoothed by a 1-pixel Gaussian and renormalised; **an unvalidated construction**), and two robustness tests that are *not* CT noise models (2 % salt-and-pepper, multiplicative speckle). Noise levels are scenarios, not measurements of a scanner.

The *principal* mask is the largest body region above −500 HU. The *inner* mask removes everything within 10 px of the scanner padding; it is an experimental sensitivity choice, not clinically validated. Metrics: RMSE_HU and MAE_HU (HU, unclipped, over the mask); PSNR and SSIM on images displayed with a −600/1500 HU window (clipped to [0, 1]), SSIM averaged over windows fully inside the mask. Definitions and the list of what each metric cannot show are in [methods_and_decisions.md](backend/docs/methods_and_decisions.md).

### What the recorded runs show (illustration, not a ranking)

Mean test RMSE_HU over 8 slices with the 95 % bootstrap interval over slices (extended-grid run, tuned on the principal mask):

| Condition | Mask | Unfiltered | Mean | Median | Gaussian | FFT Gaussian |
|---|---|---|---|---|---|---|
| white 25 HU | principal | 25.00 [24.99, 25.02] | 25.00 (identity selected) | 15.23 [14.82, 15.64] | 22.52 [22.43, 22.60] | 22.63 [22.37, 22.86] |
| white 25 HU | inner | 25.00 [24.99, 25.01] | 25.00 (identity selected) | 15.21 [14.79, 15.60] | 21.27 [21.26, 21.29] | 18.82 [18.80, 18.84] |
| white 50 HU | principal | 49.98 [49.96, 50.02] | 48.40 [47.70, 49.04] | 24.37 [23.98, 24.69] | 37.09 [36.76, 37.37] | 36.83 [36.27, 37.31] |
| white 50 HU | inner | 49.99 [49.96, 50.02] | 21.00 [20.56, 21.37] | 24.26 [23.85, 24.59] | 32.35 [32.32, 32.39] | 26.73 [26.68, 26.79] |

At 50 HU the same 3 × 3 mean filter looks almost useless on the principal mask (49.98 → 48.40 HU) and strongly useful on the inner mask (49.99 → 21.00 HU). The preferred family changes with the mask in 5 of the 8 conditions.

**Why the mask matters.** A 3-pixel band along the mask edge is about 2.3 % of the mask pixels, yet after mean or Gaussian smoothing its RMSE_HU is 228–284 HU, and in a worked example it carried 87–89 % of the squared HU error. Tuning on RMSE_HU over the principal mask is therefore largely a criterion about the body boundary: where "no filter" scored best, that means no smoothing lowered the boundary-dominated error, not that smoothing is useless for the rest of the image. Tuning on the inner mask would change the choice in 34 of 48 cells (tuning slices only). The dashboard shows both masks and a boundary-band versus deeper-region split.

**RMSE_HU, PSNR and SSIM can prefer different settings.** On the tuning slices PSNR chose the same setting as RMSE_HU in 44 of 48 cases, SSIM in only 6 of 48.

### Two comparisons that must not be confused

**(a) Extended grid versus first grid (filtered versus filtered).** The first run used a smaller grid without a "no filter" option. Each cell compares the tuned result of both runs on the 8 test slices (48 cells):

| Metric (extended − first) | Mask | Better | Worse | Unresolved |
|---|---|---|---|---|
| RMSE_HU | principal (the tuning criterion) | **30** | 0 | 18 (same setting selected) |
| RMSE_HU | inner | 12 | **18** | 18 (same setting selected) |
| MAE_HU | principal | 15 | 15 | 18 (same setting selected) |
| PSNR | principal | 29 | 0 | 19 |
| SSIM (primary) | principal | 7 | **23** | 18 (same setting selected) |

"30 better, 0 worse" holds only for RMSE_HU on the principal mask, the criterion the grids were tuned for, and it reverses on the inner mask and for SSIM. This does not show that the extended grid is better; it shows that it changes which settings are chosen.

**(b) Filtered versus the unfiltered image.** For RMSE_HU on the principal mask, 34 of 48 cells show a material reduction (mean change larger than 10⁻⁶ HU with an interval entirely below zero; median −11.2 HU), none an increase, 13 are within 10⁻⁶ HU of the unfiltered image and 1 is unresolved; on the inner mask 35 reductions, none increase, 13 identical. The absence of increases is partly built in: the "no filter" setting is part of the grid, so a filter that would raise the error is simply not selected.

### Limits of the evidence

- **One CT series, 3 tuning and 8 test slices.** No generalisation across patients, scanners, doses or kernels is claimed; slices of one scan are not independent.
- **Test set not untouched.** The code keeps test data out of the selection (a test perturbs the test slices only and finds identical selections), but test results of the first run were read before the grid was extended, so the grid comparison is not an independent validation.
- **Bootstrap intervals** use 8 slices of one patient. In simulation with 8 slices the nominal 95 % interval covered the true mean in about 79–89 % of cases, so intervals are somewhat too narrow; read them as descriptive spread. No correction for multiple comparisons was applied.
- Of the 48 selections, 35 are interior minima and 13 are "no filter" choices; 11 of the 35 have a neighbour within 0.1 HU, so several optima are flat. Agreement of the chosen setting with a held-out tuning slice's own best is 86 % (124 of 144) in a leave-one-slice-out check.
- **Not comparable with the historical results** in `backend/docs/results/` (different noise, clipping before filtering, fixed settings, no split).
- **Provenance.** The recorded runs (2026-10-24) come from an uncommitted working tree (`d788e0c` plus local changes) and are stored outside the repository; the run metadata records no source-file hashes. Re-running 2 of the 8 conditions with the committed code reproduced the recorded test rows of both runs exactly (difference 0.0), but a complete clean-clone re-run of all conditions has not been done. Future runs should record source hashes and the series UID.

### Dashboard (Benchmark V2 page)

The page shows run provenance and CSV integrity (SHA-256 against the recorded values), test metrics with intervals for both masks, change relative to the unfiltered image, tuned parameters, the grid comparison per metric and mask, cautious statements computed from the tables, and a slice viewer (window/level, noisy image, filtered images or difference maps, mask outline, intensity profile, boundary-band versus deeper-region error). Slice images are recomputed from the recorded seed and the page states whether they reproduce the recorded rows. Nothing is displayed unless the API serves a real run.

Start the API from `backend/`, pointing it at one or more run directories (and, for images, at the local CT series). Windows (Command Prompt):

```bat
set BENCHMARK_RUN_DIRS=D:\path\to\run_one;D:\path\to\run_two
set CT_SERIES_DIR=D:\path\to\LIDC-IDRI-0709
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

macOS/Linux: `export BENCHMARK_RUN_DIRS="/path/run_one:/path/run_two"` (the separator is the platform path separator). Then, in a second terminal, `cd frontend && npm install && npm run dev` and open the Benchmark V2 page. The server never accepts paths from the browser: runs are addressed by directory name, and only the configured series is read.

### Reproduction

Prerequisites not provided by this repository: a local copy of the LIDC-IDRI series (obtain it from TCIA under its terms), Python with `backend/requirements.txt`, and an output directory **outside** the repository (the script refuses to write inside it). The recorded runs used Python 3.12.15, NumPy 2.5.4, SciPy 1.18.1, scikit-image 0.26.0, pandas 3.1.0, pydicom 3.0.2 and OpenCV 5.0.0; `requirements.txt` gives lower bounds only.

```bash
cd backend
python benchmark_v2.py --dicom-series "path/to/LIDC-IDRI-0709" --out "path/outside/repo/benchmark_v2_run" --plan-only
python benchmark_v2.py --dicom-series "path/to/LIDC-IDRI-0709" --out "path/outside/repo/benchmark_v2_run" --grid-version expanded
```

Status of these commands: the argument names were checked against the parser, and the benchmark functions were run on two of the eight conditions through a script (see above); **the command-line entry point itself was not executed end to end**, and runtime and memory were not measured. `--grid-version v1` selects the first run's grid.

## Historical 2D benchmark (`evaluate_denoising.py`)

The benchmark uses a **local DICOM CT series**; the larger series is not bundled in this repository. Place an authorized, single-series dataset locally, then pass the path to that series directory:

```bash
python evaluate_denoising.py --dicom-series "path/to/one_dicom_series" --repeats 3 --seed 42
```

The script selects up to five spread-out slices by default and creates local outputs under `backend/reports/` (when run from `backend/`), including per-run metrics, a summary CSV, and comparison figures. Generated reports are ignored by Git.

Current benchmark configuration in `evaluate_denoising.py` includes a frequency cutoff ratio of `0.15`. The committed files `backend/docs/results/denoising_benchmark.csv` and `backend/docs/results/denoising_summary.csv` are **historical snapshots from the earlier `0.10` cutoff configuration**. They must not be presented as results from the current default. Regenerate the benchmark against the intended local series before publishing updated numerical claims.

A controlled synthetic test of a separate fixture is documented in [frequency cutoff validation](backend/docs/results/frequency_cutoff_validation.md). It is a small parameter check, not evidence that `0.15` is optimal for all CT images.

## Optional 3D CT workflow

The 3D tools require a consistent multi-slice DICOM series with usable geometry metadata. Example commands, run from `backend/`:

```bash
python -m src.slice_viewer "path/to/one_dicom_series"
python run_3d_viewer.py "path/to/one_dicom_series" --output reports/3D/original_ct_volume.png
python run_denoised_3d_viewer.py "path/to/one_dicom_series" --sigma-mm 1.0 --output reports/3D/original_vs_smoothed_ct.png
python -m src.evaluate_volume_denoising "path/to/one_dicom_series" --sigma-mm 1.0
```

The loader checks series identity, slice orientation, image dimensions, and slice spacing. Volume smoothing may remove small structures; a smoother appearance alone does not establish better diagnostic quality. The 3D workflow is a visualization and image-processing experiment, not a clinical viewer.

## Tests

Run the test suite from `backend/`:

```bash
python -m pytest -q
```

Last local runs (2026-10-24, no GitHub Actions run): 503 passed and 1 skipped with Python 3.12.15 (Conda environment); with Python 3.10.21 an earlier state of the suite passed (491 passed, 1 skipped) before 12 metric tests were added. The skipped test is an optional comparison with an external metadata file (`BENCHMARK_V2_INITIAL_RUN_METADATA`). The GitHub Actions workflow is configured to run pytest on pushes and pull requests targeting `main`, using Python 3.10 and 3.12. The existence of a workflow does not by itself confirm that the latest commit passed; check the current Actions status on GitHub.

## Data and privacy

- The CT series used for benchmark development is local and is not included in this repository.
- The LIDC-IDRI collection is hosted by [The Cancer Imaging Archive (TCIA)](https://www.cancerimagingarchive.net/collection/lidc-idri/). Follow the collection's data-use and attribution requirements. Reference: Armato SG III et al., *Data From LIDC-IDRI*, DOI: [10.7937/K9/TCIA.2015.LO9QL9SX](https://doi.org/10.7937/K9/TCIA.2015.LO9QL9SX).
- `download_data.py` can generate a fictional synthetic DICOM example locally and optionally download third-party examples. Review the terms of any external dataset before use or redistribution.
- Use only images you are authorized to process. Do not upload identifiable patient data to a public deployment. DICOM files and exported HTML reports can contain sensitive metadata or image content.

## Limitations

- The quantitative 2D benchmark adds synthetic noise to a source slice and uses that same pre-noise slice as the reference. It does not provide a clean ground truth for real clinical noise.
- The documented CT benchmark is based on one local series and does not establish generalization across patients, scanners, protocols, or modalities. The identity of the local series with the public LIDC-IDRI release has not been verified.
- Benchmark V2 results are exploratory: noisy clinical reference, synthetic noise, few slices of one patient, test slices that were inspected during development, and intervals that under-cover (see the V2 section).
- No learned denoising model is included, because the available data (one patient, no clean reference) cannot support an honest training and validation protocol; see [methods_and_decisions.md](backend/docs/methods_and_decisions.md).
- Synthetic speckle is included as a mathematical noise model; it is not presented as a CT-specific noise model.
- PSNR and SSIM do not measure clinical usefulness, preservation of every anatomical structure, or diagnostic performance.
- The filters are classical image-processing methods, not a trained AI model.
- A repository-wide software license has not been declared. Do not assume the code is licensed for reuse; select and add an appropriate license before inviting redistribution.

## Selected figures

The following figures are committed examples from earlier experiments. Check their associated parameters and validation notes before treating them as results for the current default configuration.

### Spatial filtering

![Gaussian synthetic noise with spatial filters](backend/docs/images/ct_gaussian_spatial.png)

![Salt-and-pepper synthetic noise with spatial filters](backend/docs/images/ct_salt_pepper_spatial.png)

![Synthetic speckle with spatial filters](backend/docs/images/ct_speckle_spatial.png)

### Frequency-domain filtering

![Salt-and-pepper synthetic noise with frequency filters](backend/docs/images/ct_salt_pepper_frequency.png)

### 3D visualization

![Original CT volume in grayscale](backend/docs/images/ct_volume_3d_grayscale.png)

![Original and Gaussian-smoothed CT volume](backend/docs/images/original_vs_smoothed_ct_3d_pseudocolor.png)

See the [3D viewer validation report](backend/docs/results/3d_viewer_validation.md) for the recorded data source and interpretation limits.
