# React Biomedical Imaging Dashboard

This frontend is a React + Vite application with a FastAPI backend. The original Streamlit application (`app.py`) remains available as an alternative interface.

## Local development

Requirements: Python and the packages in the repository's `requirements.txt`, plus Node.js 20+ and npm.

From the repository root, start the API:

```bash
python -m pip install -r requirements.txt
python -m uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173/. The Vite development server proxies `/api` requests to the local FastAPI service.

## Deployment

The root `render.yaml` defines a Render static site for this frontend and a separate Python web service for the API. The frontend reads `VITE_API_BASE_URL` at build time; the Blueprint sets it from the API service hostname. The API uses `CORS_ORIGINS` to allow requests from the hosted frontend.

For the public setup instructions, see the deployment section in the repository's root README.

## Workflows

- **2D Denoising Lab:** previews PNG/JPEG/DICOM input, runs spatial and frequency filters, and displays PSNR/SSIM.
- **3D CT Explorer:** a single DICOM slice is previewed in 2D. Select multiple slices from one consistent series for the interactive Plotly volume.
- **Results & Reports:** reads `reports/denoising_summary.csv` when present, otherwise the committed snapshot at `docs/results/denoising_summary.csv`.
- **Methods & Guide:** summarizes the algorithms, metrics, and limitations.

Medical images can contain sensitive information; do not upload identifiable patient data to a public demo. This is a research and educational project, not a diagnostic tool.
