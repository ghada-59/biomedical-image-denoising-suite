# Dashboard screenshots

Six screenshots of the **redesigned** React dashboard, used in the main README. They are real captures of the running application with the real API behind it, not mock-ups.

| File | Page | Size | What is on it |
| --- | --- | --- | --- |
| `dashboard-overview.png` | Overview (light theme) | 1440 x 900 px, 581 KB | Hero with a before/after example of the 2D lab, key figures read from the API, the four workflows |
| `dashboard-overview-dark.png` | Overview (dark theme) | 1440 x 900 px, 568 KB | The same page in the dark theme |
| `dashboard-lab.png` | 2D Denoising Lab | 1440 x 1380 px, 868 KB | A finished run on the bundled chest CT sample: the settings (methods and parameters), the run summary, the draggable before/after comparison and the first outputs with their scores |
| `dashboard-3d-explorer.png` | 3D CT Explorer | 1440 x 1380 px, 459 KB | The real 100-slice series loaded: series figures, the interactive Plotly volume, the central axial slice and the intensity range |
| `dashboard-benchmark-v2.png` | Benchmark V2 | 1440 x 1740 px, 207 KB | Run facts, provenance and file integrity of the recorded run, the metric and scenario selectors, and the RMSE charts of the nine tuned methods with their legends |
| `dashboard-benchmark-3d.png` | Benchmark 3D | 1440 x 1900 px, 237 KB | Run facts and provenance of the first recorded 3D run, and the held-out RMSE of slice-wise, isotropic and anisotropic Gaussian smoothing |

## How they were made

- **Date and code:** 2026-11-03, from the dashboard of the branch `ui/dashboard-redesign` (based on `37d7cd1`).
- **Browser:** Chrome, headless, driven by Playwright; window 1440 px wide, no zoom. Only the page is captured, so no browser toolbar, tab, bookmark or account appears. The pages are as tall as needed to show their charts whole (900 to 1900 px).
- **Servers:** the production build served by `npm run preview` (the sidebar shows its address, `127.0.0.1:4173`) and the API started with `python -m uvicorn api:app` from `backend/`, with `BENCHMARK_RUN_DIRS`, `BENCHMARK_3D_RUN_DIRS` and `CT_SERIES_DIR` set, as in the README's quick start. No value in any image is typed by hand; every number is what the API returned.
- **Lab:** the sample *Chest CT slice (LIDC-IDRI, PNG)* was chosen in the page and *Run denoising* pressed with the default settings (Gaussian noise, variance 0.02, seed 42, the six default methods).
- **3D explorer:** the local 100-slice series was selected in the page (the series is not part of the repository).
- **Benchmark pages:** the recorded runs in `backend/docs/results/` (Benchmark V2: `benchmark_v2_methods_2026-10-25`; Benchmark 3D: `benchmark_3d_2026-10-26`, the first of the two runs).
- **File format:** the PNG files are exactly what the browser produced (a recompression with maximum settings was tried and was not smaller; no colour reduction or resizing was applied, so text, charts and CT images are unchanged). They carry no metadata chunks.

## Pixel data, attribution and what the images do not show

- The lab, 3D explorer and Overview images contain pixel data derived from the chest CT series **LIDC-IDRI-0709** (The Cancer Imaging Archive, **CC BY 3.0**; data citation DOI 10.7937/K9/TCIA.2015.LO9QL9SX; Armato SG III et al., Medical Physics 38(2):915-931, 2011). The lab shows slice 50 as `backend/samples/chest_ct.png`; the explorer shows a rendering of the whole series and its central slice; the Overview example is described in `frontend/docs/overview-images.md`. The attribution is also in the main README ("Data and privacy") and is printed by the application next to the images.
- No patient name, identifier, birth date or study date is visible in any image. The benchmark pages show the public TCIA series UID, which identifies a series, not a person.
- The only network address shown is the local preview address. No file path of the machine, token or credential appears.
- These screenshots illustrate the interface. They are not results, they are not an evaluation, and they do not show diagnostic performance or clinical benefit; the page texts visible in them say the same.

The screenshots are not regenerated automatically. After a visible change of the interface, take them again the same way and update this file.
