# React Biomedical Imaging Dashboard

This frontend is a React + Vite application with a FastAPI backend. The existing Streamlit application (`app.py`) is retained as a legacy interface while the React dashboard is validated.

## Requirements

- Python environment with the packages from the repository's `requirements.txt`
- Node.js 18+ and npm

## Start the API

From the repository root, activate the Python environment and run:

```bash
python -m pip install -r requirements.txt
python -m uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

## Start the React interface

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173/.

## Workflows

- **2D Denoising Lab:** previews PNG/JPEG/DICOM input, runs the existing spatial and frequency filters, and displays PSNR/SSIM.
- **3D CT Explorer:** a single DICOM slice is previewed in 2D. Select multiple slices from one consistent series for the interactive Plotly volume.
- **Results & Reports:** reads `reports/denoising_summary.csv` when present, otherwise the committed snapshot at `docs/results/denoising_summary.csv`.
- **Methods & Guide:** summarizes the algorithms, metrics, and limitations.

The API binds to loopback for local use. Medical images can contain sensitive information; do not expose the server publicly or share exported data without authorization. This is a research and educational project, not a diagnostic tool.
