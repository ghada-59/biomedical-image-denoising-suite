# 🔬 Biomedical Image Denoising Suite

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.30%2B-FF4B4B?logo=streamlit&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-4.8%2B-5C3EE8?logo=opencv&logoColor=white)
![License](https://img.shields.io/badge/License-not%20specified-lightgrey.svg)


An interactive Streamlit application dedicated to **medical image denoising experiments and low-pass filtering** (X-rays, MRI, DICOM CT scans). This platform quantitatively evaluates (PSNR, SSIM) **spatial** (*Mean, Median, Gaussian*) and **frequency** (*Ideal, Gaussian, Butterworth* via 2D FFT) low-pass filters, including DICOM handling based on relevant metadata and standard concepts (Hounsfield unit conversion, DICOM windowing using Window Center / Window Width, photometric interpretation handling).

---

## 📌 Table of Contents

- [Overview & Architecture](#-overview--architecture)
- [Scientific Foundations & Algorithms](#-scientific-foundations--algorithms)
- [Complete DICOM Pipeline](#-complete-dicom-pipeline)
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
├── app.py                   # Streamlit interface for 2D experiments
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
# Windows
.venv\\Scripts\\activate
# Linux/macOS
# source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

```

### 2. Sample Generation & Application Launch

```bash
# Generate the built-in sample images and DICOM test files
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

The small set of chest X-ray examples in `samples/covid19_radiography/` comes from the [COVID-19 Radiography Database on Kaggle](https://www.kaggle.com/tawsifurrahman/covid19-radiography-database), maintained by Tawsifur Rahman and collaborators. These images are included as interface examples only; they are not used in the CT denoising benchmark. The dataset page states that the data files remain © their original authors and describes academic/non-commercial use. Check the current dataset terms and cite the associated publications before reusing or redistributing these images. This repository does not claim ownership of third-party sample data.

The two DICOM test files in `samples/clinical_dicom/` are downloaded from the [pydicom test-file collection](https://github.com/pydicom/pydicom/tree/main/src/pydicom/data/test_files). `samples/synthetic_ct_scan.dcm` is generated locally by `download_data.py` and contains fictional data.

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

The included DICOM samples are public test files or locally generated synthetic data. The larger CT dataset used for the 3D experiments is not committed to the repository. Dataset access, attribution, and redistribution terms must be respected.


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

![3D CT comparison before and after Gaussian smoothing](docs/images/original_vs_smoothed_ct_color.png)

This visualization compares an original thoracic CT volume with the same volume after 3D Gaussian smoothing using a standard deviation of σ = 1 mm.

* **Voxel spacing:** 0.54 × 0.54 × 3.0 mm, according to the source series metadata.
* **Visualization:** Both volumes use the same CT intensity-to-color mapping.
* **Interpretation:** The colors represent CT intensity only; they do not represent functional activity.
* **Limitation:** Smoothing may reduce small intensity variations but can also blur fine anatomical details.

This is an educational image-processing experiment, not a clinical performance assessment.

