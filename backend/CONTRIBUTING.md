# Contributing

## Development setup

```bash
git clone https://github.com/ghada-59/biomedical-image-denoising-suite.git
cd biomedical-image-denoising-suite/backend
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Linux/macOS
# source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Code changes

- Keep image-processing functions independent of the Streamlit interface where practical.
- Validate image dimensions, numeric ranges, and DICOM geometry at input boundaries.
- Use descriptive names and focused functions; add type hints where they clarify interfaces.
- Document assumptions that affect medical-image interpretation, including units, pixel spacing, intensity transforms, and display windowing.
- Avoid describing synthetic-noise experiments as clinical validation or as evidence of diagnostic benefit.

## Tests

Run the test suite from the `backend/` directory before submitting a change:

```bash
python -m pytest -q
```

Add or update tests when changing filtering, metric calculations, DICOM loading, volume geometry, or rendering behavior. For numerical changes, include tests for invalid inputs as well as expected outputs.

Other checks, all of which the GitHub workflows also run (they have not been executed on GitHub yet):

```bash
python -m pip install "ruff==0.17.2"
ruff check .                      # from backend/: pyflakes-class errors (configuration in ruff.toml)

cd ../frontend                    # Node.js 22.12 or newer
npm ci
npm run lint                      # ESLint with the React hook rules
npm test                          # Vitest + Testing Library, API mocked with fixtures taken from the real backend
npm run build                     # production build
E2E_PYTHON=path/to/python npm run e2e   # Playwright: real Chrome, real API (needs Chrome and the API requirements installed)
```

Adding a denoising method to the lab means one entry in `backend/methods.py` (label, parameters with limits and defaults, assumptions, reference) and, if the endpoint needs a new form field, the same limits in `api.py`; a test fails if the catalogue and the endpoint disagree. If the response of `/api/methods` or `/api/samples` changes, regenerate `frontend/src/test/fixtures/api_contract.json` (the command is printed by `test_frontend_contract.py`). Adding a method to the benchmark also needs a tuning grid fixed on the tuning slices, tests, and a new run in a new directory.

Recorded benchmark runs under `backend/docs/results/benchmark_v2_*` are byte-exact records: their SHA-256 values are stored in `run_metadata.json` and verified by a test and by the API. Do not edit, re-save or re-wrap them; add a new run directory instead.

## Pull requests

Include a short description of the change, the reason for it, and the tests you ran. For changes to benchmark results, state the dataset/series used, selected slices, noise settings, random seed, and how the reported metrics were calculated. Do not commit local datasets, private medical data, virtual environments, or generated reports unless there is a clear reason and the data's terms permit redistribution.

## Reporting a problem

Include the Python version, operating system, command used, expected behavior, actual behavior, and relevant traceback. Do not attach identifiable patient data.

## Licensing and sample data

No repository-wide license is currently declared. Do not assume that the source code is available for reuse under an open-source license unless a license is added. Third-party sample images and DICOM files may have their own terms; check those terms before redistributing them.
