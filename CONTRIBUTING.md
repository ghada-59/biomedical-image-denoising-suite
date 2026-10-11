# Contributing

## Development setup

```bash
git clone https://github.com/ghada-59/biomedical-image-denoising-suite.git
cd biomedical-image-denoising-suite
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

Run the test suite before submitting a change:

```bash
python -m pytest -q
```

Add or update tests when changing filtering, metric calculations, DICOM loading, volume geometry, or rendering behavior. For numerical changes, include tests for invalid inputs as well as expected outputs.

## Pull requests

Include a short description of the change, the reason for it, and the tests you ran. For changes to benchmark results, state the dataset/series used, selected slices, noise settings, random seed, and how the reported metrics were calculated. Do not commit local datasets, private medical data, virtual environments, or generated reports unless there is a clear reason and the data's terms permit redistribution.

## Reporting a problem

Include the Python version, operating system, command used, expected behavior, actual behavior, and relevant traceback. Do not attach identifiable patient data.

## Licensing and sample data

No repository-wide license is currently declared. Do not assume that the source code is available for reuse under an open-source license unless a license is added. Third-party sample images and DICOM files may have their own terms; check those terms before redistributing them.
