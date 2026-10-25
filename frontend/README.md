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

- **Overview:** scope and limits, API and benchmark status read from the API.
- **2D Denoising Lab:** upload an image or DICOM slice, or pick a bundled sample (with provenance, licence and cautions); choose noise and any of the nine methods; parameters come from the API's method catalogue (`/api/methods`), so the controls always match what the server accepts. Results show PSNR/SSIM, the parameters that were actually used, measured runtimes and a before/after comparison viewer. Slower methods are limited by image size, and the page says so before the request is sent.
- **Benchmark V2:** recorded runs with their provenance and file integrity, metrics with bootstrap intervals for both masks, tuned parameters, and (when a CT series is configured on the server) images recomputed from the recorded seeds.
- **3D CT Explorer:** a single DICOM slice is previewed in 2D; select all slices of one series for the interactive Plotly volume.
- **Older 2D results:** the earlier benchmark file found by the API, labelled with its provenance status.
- **Methods & Guide:** the method descriptions are read from the API.

Plotly (about 4.7 MB) is loaded only when a page that draws a chart is opened.

## Checks

```bash
npm run lint      # ESLint (React hook rules), must pass with no warnings
npm test          # Vitest + Testing Library (56 tests); the API is mocked with fixtures generated from the real backend
npm run build     # production build into dist/
npm run e2e       # Playwright against the real API and the installed Chrome (see playwright.config.js for the environment variables)
```

The end-to-end tests also fail on console errors and run axe-core (WCAG 2 A and AA rules) in both colour themes.

## Deployment

The root `render.yaml` defines a static site for this frontend (built with `npm ci && npm run build` on Node 22) and the API service. `VITE_API_BASE_URL` is read at build time; the API's `CORS_ORIGINS` must list the site's origin. Nothing has been deployed from this repository by the tooling that produced it; see the root README for the steps and the limits.

Medical images can contain sensitive information; do not upload identifiable patient data to a public deployment. This is a research and educational project, not a diagnostic tool.
