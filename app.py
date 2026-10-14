"""Streamlit interface for the `biomedical-image-denoising-suite` project."""

from __future__ import annotations

from pathlib import Path
import hashlib
import tempfile

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from src.dicom_volume import load_dicom_volume
from src.plotly_ct_viewer import create_ct_volume_figure

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
    page_title="Biomedical Image Denoising Suite",
    page_icon="🔬",
    layout="wide"
)

st.title("🔬 Biomedical Image Denoising Suite")
st.caption(
    "Classical image filtering with seed-controlled synthetic-noise experiments."
)

workspace = st.sidebar.radio(
    "Workspace",
    ["2D Image Denoising", "3D CT Volume"],
    key="workspace_mode",
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
    st.dataframe(styler, width="stretch", hide_index=True)

    if not candidates.empty:
        best_name = candidates.loc[candidates["SSIM"].idxmax(), "Filter"]
        st.caption(f"Highest SSIM among displayed filters: **{best_name}**")


def _show_spectrum(container, spectrum: np.ndarray, title: str, vmin: float, vmax: float) -> None:
    fig, ax = plt.subplots(figsize=(4, 4))
    im = ax.imshow(spectrum, cmap="viridis", vmin=vmin, vmax=vmax)
    ax.set_title(title, fontsize=11)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="log(1 + |F|)")
    fig.tight_layout()
    container.pyplot(fig, width="stretch")
    plt.close(fig)



if workspace == "3D CT Volume":
    st.subheader("Interactive 3D CT Volume")
    st.caption(
        "Reconstruct a volume from one DICOM series and explore it interactively."
    )
    st.info(
        "A single 2D CT slice cannot reconstruct a faithful anatomical volume. "
        "Use a complete set of slices from the same DICOM series."
    )

    source_mode = st.radio(
        "CT series source",
        ["Use a local DICOM folder", "Upload DICOM slices"],
        horizontal=True,
        key="ct_source_mode",
    )

    series_dir = None
    file_payloads = []
    signature = hashlib.sha256()
    signature.update(source_mode.encode("utf-8"))

    if source_mode == "Use a local DICOM folder":
        local_path_text = st.text_input(
            "Path to one DICOM series folder",
            placeholder=r"D:\myprojects\data\ct-series",
            help="Choose the folder that contains the slices for one CT series.",
        )
        if not local_path_text.strip():
            st.info("Enter a local folder path or switch to uploading DICOM slices.")
            st.stop()

        series_dir = Path(local_path_text.strip()).expanduser()
        if not series_dir.exists() or not series_dir.is_dir():
            st.error("The selected local path is not an existing folder.")
            st.stop()

        local_files = sorted(path for path in series_dir.rglob("*") if path.is_file())
        if not local_files:
            st.error("The selected folder does not contain any files.")
            st.stop()

        signature.update(str(series_dir.resolve()).encode("utf-8", errors="replace"))
        for path in local_files:
            try:
                stat = path.stat()
                signature.update(path.name.encode("utf-8", errors="replace"))
                signature.update(str(stat.st_size).encode("ascii"))
                signature.update(str(stat.st_mtime_ns).encode("ascii"))
            except OSError as exc:
                st.error(f"Could not inspect a file in the selected folder: {exc}")
                st.stop()

    else:
        dicom_files = st.file_uploader(
            "Select all DICOM slices from one CT series",
            type=["dcm"],
            accept_multiple_files=True,
            key="ct_series_upload",
            help="Do not mix files from different series or different studies.",
        )
        if not dicom_files:
            st.info("Select the DICOM slices to begin.")
            st.stop()

        for item in dicom_files:
            payload = item.getvalue()
            file_payloads.append((Path(item.name).name, payload))
            signature.update(Path(item.name).name.encode("utf-8", errors="replace"))
            signature.update(payload)

    series_signature = signature.hexdigest()
    cached_volume = st.session_state.get("_ct_volume_cache")

    if cached_volume is None or cached_volume["signature"] != series_signature:
        try:
            with st.spinner("Reading and assembling the DICOM volume..."):
                if series_dir is not None:
                    volume, spacing, origin, direction = load_dicom_volume(series_dir)
                else:
                    with tempfile.TemporaryDirectory(prefix="ct-series-") as temp_dir:
                        temp_path = Path(temp_dir)
                        for index, (filename, payload) in enumerate(file_payloads):
                            safe_name = Path(filename).name or "slice.dcm"
                            target = temp_path / f"{index:05d}_{safe_name}"
                            target.write_bytes(payload)
                        volume, spacing, origin, direction = load_dicom_volume(temp_path)

                st.session_state["_ct_volume_cache"] = {
                    "signature": series_signature,
                    "volume": volume,
                    "spacing": spacing,
                    "origin": origin,
                    "direction": direction,
                }
        except Exception as exc:
            st.error(
                "The DICOM series could not be loaded. Check that the files belong "
                "to one complete series with consistent image geometry and spacing."
            )
            st.caption(f"Technical details: {exc}")
            st.stop()

    cached_volume = st.session_state["_ct_volume_cache"]
    volume = cached_volume["volume"]
    spacing = cached_volume["spacing"]
    origin = cached_volume["origin"]
    direction = cached_volume["direction"]

    sample_step = max(1, int(np.ceil(max(volume.shape) / 48)))
    sampled_for_range = volume[::sample_step, ::sample_step, ::sample_step]
    range_min = int(np.floor(np.percentile(sampled_for_range, 1)))
    range_max = int(np.ceil(np.percentile(sampled_for_range, 99)))
    if range_max <= range_min:
        range_min = int(np.min(volume))
        range_max = int(np.max(volume))
    if range_max <= range_min:
        st.error("The CT volume has no intensity variation to render.")
        st.stop()

    default_min = int(np.clip(-1000, range_min, range_max - 1))
    default_max = int(np.clip(400, default_min + 1, range_max))
    intensity_min, intensity_max = st.slider(
        "CT intensity display range",
        min_value=range_min,
        max_value=range_max,
        value=(default_min, default_max),
        help=(
            "Adjust the visible intensity interval. For conventional CT data, "
            "modality values are typically expressed in Hounsfield units (HU)."
        ),
    )

    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("DICOM slices", f"{volume.shape[0]:,}")
    metric_b.metric(
        "Volume dimensions (X × Y × Z)",
        f"{volume.shape[2]} × {volume.shape[1]} × {volume.shape[0]}",
    )
    metric_c.metric(
        "Voxel spacing (X × Y × Z)",
        f"{spacing[0]:.2f} × {spacing[1]:.2f} × {spacing[2]:.2f} mm",
    )

    try:
        with st.spinner("Preparing the interactive 3D rendering..."):
            figure = create_ct_volume_figure(
                volume=volume,
                spacing_xyz_mm=spacing,
                origin_xyz_mm=origin,
                direction_matrix=direction,
                intensity_min=intensity_min,
                intensity_max=intensity_max,
            )
        st.plotly_chart(
            figure,
            width="stretch",
            config={"displaylogo": False, "scrollZoom": True},
        )
        st.caption(
            "Rotate by dragging and zoom with the mouse wheel. The browser rendering "
            "uses a downsampled voxel grid to remain responsive."
        )

        download_col, save_col = st.columns(2)
        with download_col:
            st.download_button(
                "Download interactive HTML report",
                data=lambda: figure.to_html(
                    full_html=True,
                    include_plotlyjs=True,
                    config={"displaylogo": False, "scrollZoom": True},
                ).encode("utf-8"),
                file_name="ct_volume_interactive.html",
                mime="text/html",
                on_click="ignore",
                width="stretch",
                help="A self-contained HTML report that remains interactive offline.",
            )

        with save_col:
            if st.button(
                "Save a copy to reports/3D",
                width="stretch",
                help="Save the current interactive view locally. The reports folder is excluded from Git.",
            ):
                report_dir = Path(__file__).resolve().parent / "reports" / "3D"
                report_dir.mkdir(parents=True, exist_ok=True)
                report_path = report_dir / "ct_volume_interactive.html"
                figure.write_html(
                    str(report_path),
                    full_html=True,
                    include_plotlyjs=True,
                    config={"displaylogo": False, "scrollZoom": True},
                )
                st.success(f"Saved interactive report to {report_path}")
    except (ValueError, ImportError, OSError) as exc:
        st.error("The CT volume could not be rendered or exported.")
        st.caption(f"Technical details: {exc}")

    st.warning(
        "This visualization is for research and educational use. It is not a "
        "diagnostic tool. Keep exported reports containing medical-image data private."
    )
    st.stop()


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
            "Sample from the public *COVID-19 Radiography Database* "
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
    seed = int(
        st.sidebar.number_input(
            "Random seed",
            min_value=0,
            max_value=2**32 - 1,
            value=42,
            step=1,
            help="Keep the same seed and settings to reproduce a synthetic-noise run.",
        )
    )
    noise_type = st.sidebar.selectbox("Noise Type", ["None", *NOISE_TYPES])

    if noise_type == "None":
        noisy_image = clean_image.copy()
    elif noise_type == "Salt & Pepper":
        amount = st.sidebar.slider(
            "Fraction of affected pixels", 0.001, 0.2, 0.02, 0.005,
            help="Fraction of pixels replaced by white or black.",
        )
        noisy_image = add_noise(clean_image, noise_type, amount=amount, seed=seed)
    else:
        var = st.sidebar.slider(
            "Noise Variance", 0.001, 0.2, 0.02, 0.005,
            help="Variance of the noise distribution added to each pixel.",
        )
        noisy_image = add_noise(clean_image, noise_type, var=var, seed=seed)

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
            st.image(noisy_image, caption="Noisy Image", clamp=True, width="stretch")
            st.metric("Baseline PSNR", f"{_format_psnr(p_noisy)} dB")
            st.metric("Baseline SSIM", f"{s_noisy}")
        with col2:
            st.image(mean_res, caption="Mean Filter", clamp=True, width="stretch")
            st.metric("PSNR", f"{_format_psnr(p_mean)} dB")
            st.metric("SSIM", f"{s_mean}")
        with col3:
            st.image(median_res, caption="Median Filter", clamp=True, width="stretch")
            st.metric("PSNR", f"{_format_psnr(p_median)} dB")
            st.metric("SSIM", f"{s_median}")
        with col4:
            st.image(gauss_res, caption="Gaussian Filter", clamp=True, width="stretch")
            st.metric("PSNR", f"{_format_psnr(p_gauss)} dB")
            st.metric("SSIM", f"{s_gauss}")

        if noise_type == "None":
            st.info("No synthetic noise was added. PSNR/SSIM therefore measure fidelity to the uploaded/sample image, not denoising accuracy against a ground-truth clean image.")
        else:
            st.caption("Because the noise is synthetically added to the original image, PSNR/SSIM can be compared with that original reference.")

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
        if noise_type == "None":
            st.info("No synthetic noise was added. PSNR/SSIM describe similarity to the loaded image, not denoising accuracy against an independent clean reference.")
        else:
            st.caption("The noise is synthetic and the loaded image is the reference; these metrics do not establish performance on unknown clinical noise.")

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
            st.image(fft_res, caption="Reconstructed Image", clamp=True, width="stretch")
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