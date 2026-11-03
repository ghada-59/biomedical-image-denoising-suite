# Dashboard screenshots

Four screenshots of the React dashboard, used in the main README. They show the real application with the real API behind it, not a mock-up.

| File | Page | What is on it |
| --- | --- | --- |
| `dashboard-overview.png` | Overview | Scope statement, the four workflows, and the recorded benchmark runs with the result of their SHA-256 integrity check |
| `dashboard-lab.png` | 2D Denoising Lab | Bundled sample `chest_ct`, Gaussian noise (variance 0.02, seed 42), the six default methods, the comparison divider and the thumbnails of all outputs |
| `dashboard-benchmark-v2.png` | Benchmark V2 | Provenance and file integrity of the recorded run, RMSE in Hounsfield units of nine tuned methods under six noise conditions, two masks |
| `dashboard-benchmark-3d.png` | Benchmark 3D | Provenance of the first recorded 3D run and the held-out RMSE of slice-wise, isotropic and anisotropic Gaussian smoothing |

## How they were made

- Date: 2026-11-03, from the working tree of the branch that contains this folder.
- Browser: Chrome, headless, driven by Playwright; window 1366 px wide, light theme, no zoom.
- Servers: the API (`python -m uvicorn api:app`) started with `BENCHMARK_RUN_DIRS` and `BENCHMARK_3D_RUN_DIRS` set to the recorded runs in `backend/docs/results/`, and the dashboard dev server (`npm run dev`), as in the README's quick start.
- Lab: the sample was chosen in the page and *Run denoising* pressed with the default settings; nothing was edited afterwards. The Benchmark V2 page was captured with `CT_SERIES_DIR` set, which only adds the image viewer below the part shown here.
- The lab screenshot contains one image derived from the LIDC-IDRI-0709 series (slice 50, 8-bit, display-windowed; The Cancer Imaging Archive, CC BY 3.0, DOI 10.7937/K9/TCIA.2015.LO9QL9SX): the same slice as `backend/samples/chest_ct.png`. It carries no patient identifier. See the main README ("Data and privacy") for the attribution.
- Nothing was uploaded; no file from outside the repository appears in the lab screenshot.

The screenshots are not regenerated automatically. After a visible change of the interface, take them again the same way.
