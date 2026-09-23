"""Streamlit interface for the `biomedical-image-denoising-suite` project."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from filters import (
    FREQUENCY_FILTERS,
    NOISE_TYPES,
    add_noise,
    apply_frequency_lowpass,
    apply_spatial_filters,
    calculate_metrics,
    load_medical_image,
)

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
SAMPLE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".dcm"}

st.set_page_config(
    page_title="Biomedical Image Denoising Suite v2", page_icon="🔬", layout="wide"
)

st.title("🔬 Biomedical Image Low-Pass Filtering & Benchmarking")
st.markdown(
    "Advanced analysis suite: Spatial filtering, frequency domain (2D FFT), and"
    " quantitative evaluation (PSNR / SSIM)."
)


@st.cache_data(show_spinner="Loading image…")
def _load_image_cached(source) -> np.ndarray:
    if hasattr(source, "seek"):
        source.seek(0)
    return load_medical_image(source)


def _discover_samples() -> dict[str, Path]:
    if not SAMPLES_DIR.exists():
        return {}
    found = {}
    for path in sorted(SAMPLES_DIR.rglob("*")):
        if path.is_file() and path.suffix.lower() in SAMPLE_EXTENSIONS:
            found[path.relative_to(SAMPLES_DIR).as_posix()] = path
    return found


def _format_psnr(value: float) -> str:
    return "∞" if np.isinf(value) else f"{value:.2f}"


def _show_benchmark_table(rows: list[dict], baseline_label: str | None = None) -> None:
    df = pd.DataFrame(rows)
    candidates = df if baseline_label is None else df[df["Filter"] != baseline_label]

    styler = df.style.format({"PSNR (dB)": _format_psnr, "SSIM": "{:.4f}"})
    if not candidates.empty:
        styler = styler.highlight_max(
            subset=pd.IndexSlice[candidates.index, ["SSIM"]], color="#c8e6c9"
        )
    st.dataframe(styler, use_container_width=True, hide_index=True)

    if not candidates.empty:
        best_name = candidates.loc[candidates["SSIM"].idxmax(), "Filter"]
        st.caption(f"🏆 Best quality tradeoff (SSIM) among filters: **{best_name}**")


def _show_spectrum(container, spectrum: np.ndarray, title: str, vmin: float, vmax: float) -> None:
    fig, ax = plt.subplots(figsize=(4, 4))
    im = ax.imshow(spectrum, cmap="viridis", vmin=vmin, vmax=vmax)
    ax.set_title(title, fontsize=11)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="log(1 + |F|)")
    fig.tight_layout()
    container.pyplot(fig, use_container_width=True)
    plt.close(fig)


st.sidebar.header("1. Load an Image")
samples = _discover_samples()
source_mode = st.sidebar.radio(
    "Image Source", ["Upload a file", "Use a sample"], horizontal=True
)

image_source = None
if source_mode == "Upload a file":
    image_source = st.sidebar.file_uploader(
        "Accepted formats: PNG, JPG, DICOM (.dcm)", type=["png", "jpg", "jpeg", "dcm"]
    )
elif samples:
    sample_label = st.sidebar.selectbox("Sample", list(samples.keys()))
    image_source = samples[sample_label]
    if "covid19_radiography" in Path(sample_label).parts:
        st.sidebar.caption(
            "Sample from *COVID-19 Radiography Database* "
            "(Chowdhury et al. 2020; Rahman et al. 2020) — full citation in the README."
        )
else:
    st.sidebar.info(
        "No samples found. Run `python download_data.py` to generate them, "
        "or upload your own file."
    )

if image_source is not None:
    try:
        clean_image = _load_image_cached(image_source)
    except ValueError as exc:
        st.error(f"❌ {exc}")
        st.stop()

    st.sidebar.header("2. Noise Simulation")
    noise_type = st.sidebar.selectbox("Noise Type", ["None", *NOISE_TYPES])

    if noise_type == "None":
        noisy_image = clean_image.copy()
    elif noise_type == "Salt & Pepper":
        amount = st.sidebar.slider(
            "Fraction of affected pixels", 0.001, 0.2, 0.02, 0.005,
            help="Fraction of pixels replaced by white or black.",
        )
        noisy_image = add_noise(clean_image, noise_type, amount=amount)
    else:
        var = st.sidebar.slider(
            "Noise Variance", 0.001, 0.2, 0.02, 0.005,
            help="Variance of the noise distribution added to each pixel.",
        )
        noisy_image = add_noise(clean_image, noise_type, var=var)

    st.sidebar.header("3. Filter Settings")
    kernel_size = st.sidebar.slider("Spatial Kernel Size", 3, 15, 5, step=2)
    sigma = st.sidebar.slider(
        "Gaussian Standard Deviation (0 = auto)", 0.0, 5.0, 0.0, 0.1,
        help="0 lets OpenCV calculate the standard deviation from kernel size.",
    )
    cutoff_ratio = st.sidebar.slider("FFT Cutoff Frequency", 0.01, 0.5, 0.1, 0.01)

    tab1, tab2 = st.tabs(["📊 Spatial Domain", "🌊 Frequency Domain (2D FFT)"])

    with tab1:
        st.subheader("Comparative Analysis of Spatial Filters")

        mean_res, median_res, gauss_res = apply_spatial_filters(
            noisy_image, kernel_size=kernel_size, sigma=sigma
        )

        col1, col2, col3, col4 = st.columns(4)
        p_noisy, s_noisy = calculate_metrics(clean_image, noisy_image)
        p_mean, s_mean = calculate_metrics(clean_image, mean_res)
        p_median, s_median = calculate_metrics(clean_image, median_res)
        p_gauss, s_gauss = calculate_metrics(clean_image, gauss_res)

        with col1:
            st.image(noisy_image, caption="Noisy Image", clamp=True, use_container_width=True)
            st.metric("Baseline PSNR", f"{_format_psnr(p_noisy)} dB")
            st.metric("Baseline SSIM", f"{s_noisy}")
        with col2:
            st.image(mean_res, caption="Mean Filter", clamp=True, use_container_width=True)
            st.metric("PSNR", f"{_format_psnr(p_mean)} dB")
            st.metric("SSIM", f"{s_mean}")
        with col3:
            st.image(median_res, caption="Median Filter", clamp=True, use_container_width=True)
            st.metric("PSNR", f"{_format_psnr(p_median)} dB")
            st.metric("SSIM", f"{s_median}")
        with col4:
            st.image(gauss_res, caption="Gaussian Filter", clamp=True, use_container_width=True)
            st.metric("PSNR", f"{_format_psnr(p_gauss)} dB")
            st.metric("SSIM", f"{s_gauss}")

        st.divider()
        _show_benchmark_table(
            [
                {"Filter": "Noisy (Unfiltered)", "PSNR (dB)": p_noisy, "SSIM": s_noisy},
                {"Filter": "Mean", "PSNR (dB)": p_mean, "SSIM": s_mean},
                {"Filter": "Median", "PSNR (dB)": p_median, "SSIM": s_median},
                {"Filter": "Gaussian", "PSNR (dB)": p_gauss, "SSIM": s_gauss},
            ],
            baseline_label="Noisy (Unfiltered)",
        )

    with tab2:
        st.subheader("Low-Pass Filtering in Frequency Domain (2D FFT)")

        fft_type = st.radio(
            "Displayed Frequency Filter",
            FREQUENCY_FILTERS,
            format_func=lambda x: x.capitalize(),
            horizontal=True,
        )

        freq_results = {
            ftype: apply_frequency_lowpass(noisy_image, cutoff_ratio=cutoff_ratio, filter_type=ftype)
            for ftype in FREQUENCY_FILTERS
        }
        fft_res, spec_orig, spec_filt = freq_results[fft_type]

        c1, c2, c3 = st.columns(3)
        vmin, vmax = float(spec_orig.min()), float(spec_orig.max())
        with c1:
            _show_spectrum(c1, spec_orig, "Initial Fourier Spectrum", vmin, vmax)
        with c2:
            _show_spectrum(c2, spec_filt, "Filtered Spectrum (Low-Pass)", vmin, vmax)
        with c3:
            st.image(fft_res, caption="Reconstructed Image", clamp=True, use_container_width=True)
            p_fft, s_fft = calculate_metrics(clean_image, fft_res)
            st.metric("Reconstructed PSNR", f"{_format_psnr(p_fft)} dB")
            st.metric("Reconstructed SSIM", f"{s_fft}")

        st.divider()
        freq_rows = []
        for ftype, (res, _, _) in freq_results.items():
            p, s = calculate_metrics(clean_image, res)
            freq_rows.append({"Filter": ftype.capitalize(), "PSNR (dB)": p, "SSIM": s})
        _show_benchmark_table(freq_rows)

else:
    st.info("Please load a medical image (.PNG, .JPG, or DICOM .DCM) to get started.")