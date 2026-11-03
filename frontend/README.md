# React dashboard

React 18 + Vite 6 interface for the FastAPI backend in `../backend`. The original Streamlit application (`backend/app.py`) remains available as an alternative interface. Requirements: **Node.js 22.12 or newer** and npm.

## Run it locally

From `backend/` (Python environment with `requirements.txt` or `requirements-api.txt` installed):

```bash
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173/ (`localhost` works as well). The complete installation, the configuration variables, the list of error messages and the optional Windows launcher (`.\dev.cmd`) are in the [root README](../README.md#quick-start-dashboard).

### How the page reaches the API

- In `npm run dev` and `npm run preview` the page calls its **own address** (`/api/...`); the Vite server forwards those calls to `http://127.0.0.1:8000` (`server.proxy` and `preview.proxy` in `vite.config.js`; set `VITE_DEV_API_TARGET` to forward elsewhere). The browser never talks to port 8000 directly, so no CORS setup is needed in development.
- A production build that is served by something else must be built with `VITE_API_BASE_URL` set to the API's address (and the API's `CORS_ORIGINS` must list the page's origin).
- The page asks `/api/health` every 2 seconds while the API is offline and every 5 seconds while it is online. When the API comes back the pages reload their data by themselves, and a user's settings in the lab are kept.
- Failures are reported by what actually failed, never as a generic "cannot reach localhost:5173": the proxy answers HTTP 502 with a JSON message when the API is down (*The API is not reachable*); if not even the dashboard server answers, the page says *The dashboard server is not responding*; an HTTP 200 that is not JSON (for example a static host's fallback page) is treated as "not the API", never as success. The pages that need the API show that state instead of data; nothing is filled in with placeholder values.

To see recorded benchmark results, start the API with `BENCHMARK_RUN_DIRS` pointing at a run directory (the run that ships with the repository is `backend/docs/results/benchmark_v2_methods_2026-10-25`); without it the Benchmark V2 page says that no run is configured and shows nothing.

## Pages

- **Overview:** an introduction with a before/after example, key figures read from the API (number of methods, recorded runs, how many result files match their SHA-256, connection), the four workflows, the recorded runs with their integrity status, the processing pipeline, and the scope and limits.
- **2D Denoising Lab:** upload an image or DICOM slice, or pick a bundled sample (with provenance, licence and cautions); choose noise and any of the nine methods; parameters come from the API's method catalogue (`/api/methods`), so the controls always match what the server accepts. Results show PSNR/SSIM, the parameters that were actually used, measured runtimes and a before/after comparison viewer (drag the divider on the image, or use the slider under it). Slower methods are limited by image size, and the page says so before the request is sent.
- **Benchmark V2:** recorded runs with their provenance and file integrity, metrics with bootstrap intervals for both masks, tuned parameters, and (when a CT series is configured on the server) images recomputed from the recorded seeds.
- **3D CT Explorer:** a single DICOM slice is previewed in 2D; select all slices of one series for the interactive Plotly volume and its central axial slice. The API returns those two views only; coronal and sagittal views are produced by the command-line viewers described in the root README.
- **Older 2D results:** the earlier benchmark file found by the API, labelled with its provenance status.
- **Methods & Guide:** the method descriptions are read from the API.

Plotly (about 4.7 MB) is loaded only when a page that draws a chart is opened. If a page fails to render (for example, that download fails), the other pages stay usable and the page shows what failed and a reload button.

## Design system

All of it is in `src/styles.css` (custom CSS, no framework). The identity colours are tokens at the top of the file: deep navy `#10243A` (sidebar), medical blue `#176B87` (actions and links), teal `#16A6A0` (accent, used for fills and decoration only: it is 3:1 on white), ice background `#F4F7FB`, text `#172B4D`, borders `#E2E8F0`; red, amber and green carry status only. A dark theme redefines the same tokens.

- **Contrast is tested.** `src/test/design.test.jsx` reads the real token values and require 4.5:1 for every text colour on every surface it can sit on, and 3:1 for the border of a form control, in both themes. The specified secondary text colour `#64748B` is 4.8:1 on white but only 4.4:1 on the ice background, so `--text-2` keeps that value for white surfaces and `--muted` (`#56667B`) is the standard secondary text colour.
- **Navigation.** The sidebar can be collapsed to a rail of icons (the choice is stored in the browser when storage is allowed); between 901 and 1100 px it is always a rail, and below 900 px it is a drawer. The labels stay in the page, visually hidden, so every button keeps its name.
- **Images on the Overview** are in `public/img/` (provenance and licence: `docs/overview-images.md`): real outputs of the lab for the bundled chest CT sample, CC BY 3.0 (The Cancer Imaging Archive), shown as an illustration and never as a result.
- **Chart colours** (`src/chartTheme.js`) are colour-blind-safe and identical for the same method on every page; they were not changed by the redesign.

## Checks

```bash
npm run lint      # ESLint (React hook rules), must pass with no warnings
npm test          # Vitest + Testing Library; the API is mocked with fixtures generated from the real backend (last measured counts: root README, "Tests and checks")
npm run build     # production build into dist/
npm run e2e       # Playwright against the real API and the installed Chrome (see playwright.config.js for the environment variables)
```

The end-to-end tests also fail on console errors and run axe-core (WCAG 2 A and AA rules) in both colour themes.

## Deployment

The root `render.yaml` defines a static site for this frontend (built with `npm ci && npm run build` on Node 22) and the API service. `VITE_API_BASE_URL` is read at build time; the API's `CORS_ORIGINS` must list the site's origin. Nothing has been deployed from this repository by the tooling that produced it; see the root README for the steps and the limits.

Medical images can contain sensitive information; do not upload identifiable patient data to a public deployment. This is a research and educational project, not a diagnostic tool.
