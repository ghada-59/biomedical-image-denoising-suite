# Biomedical Image Denoising Suite

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.30%2B-FF4B4B?logo=streamlit&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-4.8%2B-5C3EE8?logo=opencv&logoColor=white)
![License](https://img.shields.io/badge/License-not%20specified-lightgrey.svg)


An interactive Streamlit application dedicated to **medical image denoising experiments and low-pass filtering** (X-rays, MRI, DICOM CT scans). This platform quantitatively evaluates (PSNR, SSIM) **spatial** (*Mean, Median, Gaussian*) and **frequency** (*Ideal, Gaussian, Butterworth* via 2D FFT) low-pass filters, including DICOM handling based on relevant metadata and standard concepts (Hounsfield unit conversion, DICOM windowing using Window Center / Window Width, photometric interpretation handling).

---

## React dashboard

The React + Vite dashboard uses the FastAPI API in `api.py`. The original Streamlit interface remains available locally with `streamlit run app.py`.

The React dashboard can be deployed with the included [Render Blueprint](render.yaml), which defines two services:

- **Frontend:** static React site built from `frontend/`.
- **API:** Python web service running FastAPI and the existing image-processing functions.

### Deploy the live dashboard

1. Push or merge the deployment configuration into `main`.
2. Sign in to [Render](https://render.com/) and choose **New → Blueprint**.
3. Connect this repository and select the `main` branch.
4. Review the two services defined in `render.yaml`, then create them.
5. Wait for both services to finish deploying. Open the frontend service's public URL and check that the API status is online.

The Blueprint sets `VITE_API_BASE_URL` from the API service hostname and configures the API's allowed frontend origin. If you rename either service or use a custom domain, update `CORS_ORIGINS` to match the frontend's exact HTTPS origin and redeploy.

For local development, install the packages in `requirements.txt`, run `python -m uvicorn api:app --reload --host 127.0.0.1 --port 8000` from the repository root, then run `npm install` and `npm run dev` from `frontend/`. The Vite development proxy continues to send `/api` requests to the local API.

The hosted API uses the smaller `requirements-api.txt` dependency set and the `/api/health` health check. Free hosting may sleep while idle and take a little time to wake up. This is an educational research interface, not a diagnostic tool; use only authorized, de-identified images and do not upload identifiable patient data to a public demo.

## 📌 Table of Contents

- [Overview & Architecture](#-overview--architecture)
- [Scientific Foundations & Algorithms](#-scientific-foundations--algorithms)
- [DICOM and 3D CT Pipeline](#-dicom-and-3d-ct-pipeline)
- [Tech Stack](#-tech-stack)
- [Installation & Usage](#-installation--usage)
- [Test Suite & Continuous Integration](#-test-suite--continuous-integration)

---

## 🏗️ Overview & Architecture

The project separates the 2D processing pipeline from the Streamlit interface and keeps the optional 3D DICOM workflow in `src/`. No repository-wide license is currently declared; check third-party dataset and sample-file terms separately before redistribution.

```text
biomedical-image-denoising-suite/
├── .github/
│   └── workflows/
│       └── pytest.yml       # Automated test workflow on pushes and pull requests
├── app.py                   # Multi-page Streamlit project dashboard
├── filters.py               # 2D image loading, filtering, and metrics
├── evaluate_denoising.py    # DICOM CT slice benchmark + 2D figure exports
├── download_data.py         # Local sample generation and downloads
├── test_filters.py          # 2D unit tests
├── test_volume_denoising.py # 3D denoising unit tests
├── src/                     # DICOM volume, denoising, and visualization code
├── requirements.txt         # Project dependencies
└── samples/                 # Optional UI/demo images; not the main CT benchmark

```

### Design Conventions

* **Unified Normalization**: All images processed by `filters.py` are represented as 2D `float64` NumPy arrays bounded within the $[0.0, 1.0]$ range.
* **Decoupled Computation**: The `filters.py` module has zero dependencies on Streamlit. Metrics (PSNR, SSIM) and Fourier spectra (unnormalized 2D FFT) can be directly integrated into batch processing workflows or Jupyter notebooks.

---

## 🔬 Scientific Foundations & Algorithms

### Low-Pass Filtering Mechanism

Different noise processes have different spatial and frequency characteristics. Low-pass filtering can attenuate high-frequency components, but it may also remove fine anatomical or image structure, so the result depends on the image and noise model.

### Spatial vs. Frequency Domain

| Domain | Algorithm | Characteristics |
| --- | --- | --- |
| **Spatial** | **Mean (Box)** | Uniform smoothing via $O(K^2)$ spatial convolution. Significantly blurs anatomical edges. |
| **Spatial** | **Median** | Non-linear filter. Effective for impulse outliers such as Salt & Pepper noise and can preserve edges better than simple averaging in some cases. |
| **Spatial** | **Gaussian** | Weighted spatial kernel. Smoothes noise while minimizing structural artifacts. |
| **Frequency** | **Ideal** | Sharp circular binary mask on 2D FFT. Introduces prominent **ringing artifacts (Gibbs phenomenon)** around edges. |
| **Frequency** | **Butterworth** | Smooth attenuation controlled by filter order $n$. Balances roll-off steepness and ringing suppression. |
| **Frequency** | **Gaussian** | Smooth frequency attenuation without the sharp cutoff of the Ideal filter. |

### Evaluation Metrics

* **PSNR (Peak Signal-to-Noise Ratio)**: Derived from the Mean Squared Error (MSE) relative to the clean reference image.
* **SSIM (Structural Similarity Index)**: Evaluates luminance, contrast, and local structural similarity between a reference and processed image.

---

## 🩺 DICOM and 3D CT Pipeline

Medical image ingestion (`.dcm`) handles common DICOM metadata used in this project:

1. **Photometric Interpretation**: The quantitative DICOM modality values are not inverted for `MONOCHROME1`. The 2D display loader applies display-polarity inversion only after modality transformation and window normalization.
2. **Modality LUT (HU Conversion)**: Rescale slope and intercept application:

$$\text{HU} = \text{PixelValue} \times \text{RescaleSlope} + \text{RescaleIntercept}$$


3. **Windowing**: Application of Window Center ($\text{WC}$) and Window Width ($\text{WW}$) parameters extracted from DICOM metadata:

The default linear VOI window follows the DICOM convention (including the `-0.5` center offset and `WW - 1` scaling); invalid widths are rejected.



---

## 🧰 Tech Stack

* **Web Interface**: `Streamlit`
* **Image processing**: `NumPy`, `OpenCV`, `scikit-image`, `SciPy`
* **Medical imaging**: `pydicom`
* **3D visualization**: `VTK`, `Matplotlib`
* **Benchmarking**: `Pandas`
* **Testing and CI**: `pytest`, `pytest-cov`, `GitHub Actions`

---

## ⚡ Installation & Usage

### 1. Clone & Environment Setup

```bash
git clone https://github.com/ghada-59/biomedical-image-denoising-suite.git
cd biomedical-image-denoising-suite

python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Windows Command Prompt
.venv\Scripts\activate.bat

# Linux/macOS
# source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

```


### Interactive 3D CT volume in the Streamlit dashboard

Run the dashboard with streamlit run app.py and choose **3D CT Volume** in the sidebar. You can point it to a local folder containing one DICOM series or upload the series slices. The application validates and assembles the slices using the existing geometry-aware DICOM loader, then renders an interactive volume with Plotly. Adjust the intensity range to explore the CT values.

Use **Download interactive HTML report** to save a self-contained report that remains interactive in a browser, including offline. The HTML includes the 3D view plus a metadata table with slice count, volume dimensions, voxel spacing, selected intensity range, and a note that the rendering is downsampled. **Save a copy to reports/3D** writes the same report to the local project folder. The reports directory is Git-ignored, so generated medical-image reports are not committed automatically. The HTML may contain sensitive medical-image information; share it only when authorized.

A single 2D slice cannot reconstruct a faithful anatomical volume; a multi-slice DICOM series is required. The browser rendering is downsampled for responsiveness. The existing VTK desktop viewer remains available for a separate 3D visualization workflow.


### Project dashboard

The Streamlit interface is organized as a project workspace with five sections:

- **Project Overview** — summarizes the implemented workflows, methods, metrics, and analysis pipeline.
- **2D Denoising Lab** — interactive image loading, synthetic-noise experiments, spatial/frequency filtering, and PSNR/SSIM comparisons.
- **3D CT Volume** — interactive Plotly volume rendering from one consistent multi-slice DICOM series, with standalone HTML export.
- **Results & Reports** — reads locally generated benchmark CSVs, displays summary charts and tables, and lists saved report files. It shows file modification timestamps rather than inventing experiment dates; if benchmark outputs are absent, it explains how to generate them.
- **Project Guide** — summarizes the methods, metrics, and reproducible benchmark command.

The overview and report pages do not fabricate performance values. Benchmark charts appear only after the local benchmark has produced its CSV outputs. The displayed PSNR/SSIM values belong to controlled synthetic-noise experiments and should not be interpreted as clinical validation.

### 2. Sample Generation & Application Launch

```bash
# Generate local examples without optional third-party downloads
python download_data.py --skip-kaggle --skip-dicom-test-files

# Optional: also download public pydicom test fixtures and a small
# Kaggle image subset (check dataset terms before use or redistribution)
python download_data.py

# Launch the interactive Streamlit dashboard
streamlit run app.py

```

---

## 📈 Reproducible 2D CT benchmark

The primary 2D benchmark uses representative axial slices from a local DICOM CT series, rather than treating the two sample PNG files as the project's clinical reference set. The `brain_mri.png` and `cells_tissue.png` files remain optional examples for the Streamlit interface only.

On CT, the script converts modality values to a fixed lung display window (default: center -600 HU, width 1500 HU), normalizes the displayed slice to [0, 1], adds reproducible synthetic noise, and compares classical spatial/frequency filters with the original windowed source slice. These metrics measure recovery from a controlled synthetic perturbation; the clinical CT slice is not claimed to be a noise-free ground truth.

```bash
# Use a single DICOM series directory
python evaluate_denoising.py --dicom-series data/tcia/LIDC-IDRI-0709/1.3.6.1.4.1.14519.5.2.1.6279.6001.309707676674808510671394142910

# Optional: select exact zero-based axial slice indices
python evaluate_denoising.py --dicom-series path/to/one_dicom_series --slice-indices 20 35 50 65 80 --repeats 3 --seed 42
```

The script selects up to five spread-out slices by default and evaluates three independently seeded synthetic-noise realizations per slice and noise type (configurable with `--repeats`). The summary CSV includes means and standard deviations across runs. It creates:

- `reports/denoising_benchmark.csv`: per-slice and per-filter metrics and gains relative to the unfiltered noisy input.
- `reports/denoising_summary.csv`: mean PSNR/SSIM and mean gains by filter and noise type.
- `reports/2D/`: image comparisons for spatial and frequency-domain filters.

The `reports/` directory is generated locally and is intentionally ignored by Git. The committed benchmark snapshot and selected figures under `docs/` provide a reproducible reference for the results shown here.

### Representative Visual Results

The following figures illustrate representative results from the controlled
synthetic-noise benchmark on axial CT slices. Each comparison includes the
original windowed reference, the synthetically degraded image, and the filtered
outputs.

#### Gaussian Synthetic Noise — Spatial Filtering

![Gaussian noise spatial-filter comparison](docs/images/ct_gaussian_spatial.png)

#### Salt-and-Pepper Noise — Spatial Filtering

![Salt-and-pepper noise spatial-filter comparison](docs/images/ct_salt_pepper_spatial.png)

#### Salt-and-Pepper Noise — Frequency-Domain Filtering

![Salt-and-pepper noise frequency-filter comparison](docs/images/ct_salt_pepper_frequency.png)

#### Synthetic Speckle Noise — Spatial Filtering

![Synthetic speckle spatial-filter comparison](docs/images/ct_speckle_spatial.png)

### Quantitative Results — Current Multi-Run Benchmark

The table below summarizes the updated benchmark (mean ± standard deviation across repeated synthetic-noise runs). Metrics are computed on CT slices after applying the fixed display window (center = -600 HU, width = 1500 HU) and normalizing intensities to [0, 1]. They are **display-domain image metrics**, not HU-domain accuracy measures.

| Synthetic noise | Noisy baseline PSNR (dB) | Noisy baseline SSIM | Spatial median PSNR (dB) | Spatial median SSIM | Frequency Gaussian PSNR (dB) | Frequency Gaussian SSIM |
|---|---:|---:|---:|---:|---:|---:|
| Gaussian | 18.385 ± 0.293 | 0.1702 ± 0.0160 | 27.884 ± 0.192 | 0.6074 ± 0.0175 | 23.087 ± 0.373 | 0.6499 ± 0.0185 |
| Salt & Pepper | 21.033 ± 0.240 | 0.6231 ± 0.0063 | 34.559 ± 0.289 | 0.9714 ± 0.0038 | 24.473 ± 0.525 | 0.7496 ± 0.0173 |
| Speckle (synthetic) | 22.451 ± 0.619 | 0.4845 ± 0.0559 | 30.661 ± 0.300 | 0.8179 ± 0.0409 | 24.050 ± 0.445 | 0.8155 ± 0.0168 |

The benchmark snapshot is committed with the repository:

- [Per-run measurements](docs/results/denoising_benchmark.csv)
- [Aggregated results](docs/results/denoising_summary.csv)
- [Gaussian-noise spatial comparison](docs/images/benchmark_gaussian_spatial.png)
- [Salt-and-pepper spatial comparison](docs/images/benchmark_salt_pepper_spatial.png)
- [Synthetic-speckle spatial comparison](docs/images/benchmark_speckle_spatial.png)


These are selected comparisons, not a claim that either filter is best under every metric. For example, the mean filter has a higher average SSIM than the median filter for the synthetic speckle condition in the spatial-filter results. Filter choice therefore depends on the noise model and the metric being considered.

**Reproducibility settings:** base seed = 42; up to five spread-out slices from one local CT series; three separately seeded noise realizations per slice and noise type; salt-and-pepper amount = 0.02; Gaussian/synthetic-speckle variance = 0.02; spatial kernel = 5 × 5; frequency cutoff ratio = 0.10; Butterworth order = 2. With five valid slices and three repeats, each filter/noise configuration is summarized over 15 runs.

**Interpretation limits:** Repeats are noise realizations, not additional patients or independent CT studies. The reference is the same CT slice before synthetic noise is added; this is a controlled experiment, not a clean-ground-truth clinical denoising study. Results from one series do not establish generalization to other patients, scanners, acquisition protocols, or real clinical noise, and they do not demonstrate clinical diagnostic benefit.

### Sample data sources

Third-party datasets are **not bundled** in this repository. Running `python download_data.py` optionally downloads a small subset of the [COVID-19 Radiography Database on Kaggle](https://www.kaggle.com/tawsifurrahman/covid19-radiography-database) for the interface only; these images are not used in the CT denoising benchmark. Review the dataset's current terms and associated publications before downloading, using, or redistributing them. The project does not claim ownership of third-party data.

Optional DICOM test fixtures are downloaded from the [pydicom test-file collection](https://github.com/pydicom/pydicom/tree/main/src/pydicom/data/test_files) into `samples/dicom_test_files/`. They are software test fixtures, not clinical data. The committed `samples/synthetic_ct_scan.dcm` is generated locally by `download_data.py` and contains fictional data.

### Dataset attribution

The local TCIA LIDC-IDRI CT series is not bundled in this repository. The 3D volume loader rejects mixed-series directories, inconsistent orientations and non-uniform slice spacing rather than silently constructing a misleading regular grid. When using LIDC-IDRI, follow the dataset's attribution and data-use requirements. Reference: Armato SG III et al., *Data From LIDC-IDRI*, The Cancer Imaging Archive (2015), DOI: [10.7937/K9/TCIA.2015.LO9QL9SX](https://doi.org/10.7937/K9/TCIA.2015.LO9QL9SX). See the [official TCIA collection page](https://www.cancerimagingarchive.net/collection/lidc-idri/).

## 🧪 Test Suite & Continuous Integration

The test suite covers noise generation, input validation, filtering, numerical metrics, DICOM loading/sorting, physical spacing, geometry checks, CT window normalization, and reproducible seed derivation. GitHub Actions runs this test suite automatically on pushes and pull requests targeting `main`.

```bash
# Run the full test suite
python -m pytest -q

# Optional coverage report
python -m pytest --cov=filters --cov-report=term-missing
```

### Important evaluation note

PSNR and SSIM are computed against the **loaded reference image**. When synthetic noise is added in the application, that reference is the original image before degradation, so the comparison has a known reference. For an already-noisy real image uploaded without a ground-truth clean counterpart, these metrics measure similarity to the uploaded image rather than objective restoration accuracy.

The committed DICOM sample is locally generated synthetic data. Optional pydicom test fixtures and Kaggle interface examples can be downloaded separately; the larger CT dataset used for the 3D experiments is not committed to the repository. Dataset access, attribution, and redistribution terms must be respected.


## ⚠️ Scope and limitations

This is an educational image-processing project, not a clinical diagnostic tool. The implemented methods are classical spatial/frequency-domain filters and 3D Gaussian smoothing; they are not presented as state-of-the-art medical denoising methods.

PSNR and SSIM are meaningful here when synthetic noise is added to a known reference image. For real clinical images without a clean reference, the project reports descriptive changes rather than claiming denoising accuracy.

The 3D reconstruction code expects a consistent DICOM series with `ImageOrientationPatient`, `ImagePositionPatient`, `PixelSpacing`, and compatible image dimensions/series metadata.


### 3D workflow

The optional 3D tools are separate from the Streamlit app and require VTK. They preserve the DICOM direction matrix in VTK, validate single-series identity and uniform slice spacing, apply Gaussian sigma in physical millimetres, and save PNG snapshots. They operate on a local DICOM series directory:

```bash
# Orthogonal slice views
python -m src.slice_viewer path/to/dicom_series

# Original CT volume (neutral grayscale is the default)
python run_3d_viewer.py path/to/dicom_series --output reports/3D/original_ct_volume.png

# Optional pseudo-colour maps CT intensity only; it is not functional activity
python run_3d_viewer.py path/to/dicom_series --color-mode hu-pseudocolor

# Original vs. 3D Gaussian-smoothed volume, using the same camera and intensity mapping
python run_denoised_3d_viewer.py path/to/dicom_series --sigma-mm 1.0 --output reports/3D/original_vs_smoothed_ct.png

# Optional pseudo-colour comparison (same mapping on both volumes)
python run_denoised_3d_viewer.py path/to/dicom_series --sigma-mm 1.0 --color-mode hu-pseudocolor

# Orthogonal slice/difference figure and descriptive smoothing report
python -m src.evaluate_volume_denoising path/to/dicom_series --sigma-mm 1.0
```

The volume viewer annotates the volume dimensions, voxel spacing and display mode, and includes an orientation marker. The original/smoothed comparison shares a camera and the same intensity transfer function so that visual differences are easier to interpret. Grayscale is the default; pseudo-colour is an intensity mapping only, not a PET-like functional overlay. The 3D workflow is intended for compatible single-frame CT series and is not a clinical visualization system. Smoothing can remove small structures, so a smoother appearance alone is not evidence of improved diagnostic quality.

## 3D CT Volume Rendering: Original vs Gaussian-Smoothed

![Original CT volume rendered in grayscale](docs/images/ct_volume_3d_grayscale.png)

![3D CT comparison before and after Gaussian smoothing](docs/images/original_vs_smoothed_ct_3d_pseudocolor.png)

Validation details: [3D viewer validation report](docs/results/3d_viewer_validation.md).

This visualization compares an original thoracic CT volume with the same volume after 3D Gaussian smoothing using a standard deviation of σ = 1 mm.

* **Voxel spacing:** 0.54 × 0.54 × 3.0 mm, according to the source series metadata.
* **Visualization:** Both volumes use the same CT intensity-to-color mapping.
* **Interpretation:** The colors represent CT intensity only; they do not represent functional activity.
* **Limitation:** Smoothing may reduce small intensity variations but can also blur fine anatomical details.

This is an educational image-processing experiment, not a clinical performance assessment.

