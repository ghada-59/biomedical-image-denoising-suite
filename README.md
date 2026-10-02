# 🔬 Biomedical Image Denoising Suite

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.30%2B-FF4B4B?logo=streamlit&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-4.8%2B-5C3EE8?logo=opencv&logoColor=white)
![PyTest](https://img.shields.io/badge/PyTest-26%20Passed-success?logo=pytest&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)


An interactive Streamlit application dedicated to **medical image restoration and low-pass filtering** (X-rays, MRI, DICOM CT scans). This platform quantitatively evaluates (PSNR, SSIM) **spatial** (*Mean, Median, Gaussian*) and **frequency** (*Ideal, Gaussian, Butterworth* via 2D FFT) low-pass filters, including DICOM handling based on relevant metadata and standard concepts (Hounsfield unit conversion, VOI LUT windowing, photometric interpretation handling).

---

## 📌 Table of Contents

- [Overview & Architecture](#-overview--architecture)
- [Scientific Foundations & Algorithms](#-scientific-foundations--algorithms)
- [Complete DICOM Pipeline](#-complete-dicom-pipeline)
- [Tech Stack](#-tech-stack)
- [Installation & Usage](#-installation--usage)
- [Test Suite & CI/CD](#-test-suite--cicd)

---

## 🏗️ Overview & Architecture

The project enforces a **strict Separation of Concerns (SoC)** between scientific computation and the user interface:

```text
biomedical-image-denoising-suite/
├── .github/
│   └── workflows/
│       └── pytest.yml       # Automated test workflow on pushes and pull requests
├── app.py                   # Streamlit UI (Layout, widgets, and visualization)
├── filters.py               # Scientific engine (NumPy/OpenCV/scikit-image/pydicom)
├── download_data.py         # Data acquisition script (Kaggle dataset & synthetic DICOM)
├── test_filters.py          # PyTest unit test suite (34 tests)
├── requirements.txt         # Project dependencies with pinned versions
└── samples/                 # Medical image samples (generated dynamically)

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

## 🩺 Complete DICOM Pipeline

Medical image ingestion (`.dcm`) handles common DICOM metadata used in this project:

1. **Photometric Interpretation**: Dynamic inversion for `MONOCHROME1` files (where minimum pixel value corresponds to white) based on exact stored bit depth (`BitsStored`).
2. **Modality LUT (HU Conversion)**: Rescale slope and intercept application:

$$\text{HU} = \text{PixelValue} \times \text{RescaleSlope} + \text{RescaleIntercept}$$


3. **Windowing**: Application of Window Center ($\text{WC}$) and Window Width ($\text{WW}$) parameters extracted from DICOM metadata:

$$\text{Range} = \left[ \text{WC} - \frac{\text{WW}}{2}, \text{WC} + \frac{\text{WW}}{2} \right]$$



---

## 🧰 Tech Stack

* **Web Interface**: `Streamlit`
* **Matrix Computation & Image Processing**: `NumPy`, `OpenCV` (`cv2`), `scikit-image`
* **Medical Imaging**: `pydicom`
* **Visualization & Benchmarking**: `Matplotlib`, `Pandas`
* **Quality & Integration**: `pytest`, `pytest-cov`, `GitHub Actions`

---

## ⚡ Installation & Usage

### 1. Clone & Environment Setup

```bash
git clone 
cd biomedical-image-denoising-suite

conda create -n biomed-env python=3.10 -y
conda activate biomed-env
pip install -r requirements.txt

```

### 2. Sample Generation & Application Launch

```bash
# Generate sample data (Synthetic DICOM + COVID-19 dataset subset)
python download_data.py

# Launch the interactive Streamlit dashboard
streamlit run app.py

```

---

## 🧪 Test Suite & CI/CD

The scientific core contains **34 unit tests** covering noise generation, input validation, matrix shapes and ranges, numerical metrics, and the DICOM-loading paths implemented in the project. GitHub Actions runs this test suite automatically on pushes and pull requests targeting `main`.

```bash
# Run unit tests with terminal coverage report
pytest --cov=filters --cov-report=term-missing


### Important evaluation note

PSNR and SSIM are computed against the **loaded reference image**. When synthetic noise is added in the application, that reference is the original image before degradation, so the comparison has a known reference. For an already-noisy real image uploaded without a ground-truth clean counterpart, these metrics measure similarity to the uploaded image rather than objective restoration accuracy.

The included DICOM samples are public test samples or locally generated synthetic data. No patient dataset is committed to the repository. The optional Kaggle download is performed locally by the data-generation script.
