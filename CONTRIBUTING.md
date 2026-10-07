# Contributing to Biomedical Image Denoising Suite

Thank you for your interest in contributing! This document outlines guidelines for contributing.

## Code of Conduct

Be respectful, inclusive, and professional in all interactions.

## Development Setup

```bash
# Clone repository
git clone https://github.com/ghada-59/biomedical-image-denoising-suite.git
cd biomedical-image-denoising-suite

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install pytest pytest-cov

# Run tests
pytest -v
```

## Code Style

- Follow **PEP 8** guidelines
- Use **type hints** for all function signatures
- Add **docstrings** (Google style) to all public functions
- Maximum line length: 88 characters (Black formatter)

Example:
```python
def normalize_image(image: np.ndarray) -> np.ndarray:
    """
    Normalize image to [0.0, 1.0] float64 range.
    
    Args:
        image: Input image (any dtype)
        
    Returns:
        Normalized float64 image in [0.0, 1.0]
        
    Raises:
        ValueError: If image is None or empty
    """
    ...
```

## Testing Requirements

- All new code **must have tests**
- Minimum coverage: **80%**
- Run locally: `pytest --cov=filters --cov-report=term-missing`

## Pull Request Process

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make changes with descriptive commits
3. Add/update tests
4. Run: `pytest` and `flake8`
5. Push to your fork
6. Create PR with description of changes
7. Ensure CI passes

## Issue Reporting

Include:
- Python version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Error traceback (if applicable)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
