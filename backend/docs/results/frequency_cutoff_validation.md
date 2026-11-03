# Frequency-filter cutoff validation

## Why the default changed

The frequency low-pass cutoff controls how much high-frequency image content is retained. A small cutoff can suppress noise, but it can also erase edges and fine structures. The previous default was 0.10 in the filtering function, benchmark script, Streamlit interface, FastAPI endpoint, and React dashboard.

The default is now 0.15 across these entry points. This is a more conservative starting point, not a universally optimal setting. The cutoff should still be adjusted for the image and noise model.

## Controlled synthetic test

A local synthetic grayscale fixture from `test_filters.py` was degraded with Gaussian noise (variance 0.02, seed 1). The Gaussian frequency filter was applied at several cutoffs. PSNR and SSIM were measured against the fixture before noise was added.

| Cutoff ratio | PSNR (dB) | SSIM |
| ---: | ---: | ---: |
| Noisy input | 18.385 | 0.1970 |
| 0.10 | 25.227 | 0.7589 |
| 0.15 | 26.986 | 0.8076 |
| 0.20 | 27.794 | 0.7952 |
| 0.25 | 27.979 | 0.7523 |

For this synthetic test image, 0.15 produced better PSNR and SSIM than 0.10, and had higher SSIM than the tested larger cutoffs. A cutoff of 0.25 gave the highest PSNR in this small sweep but lower SSIM, illustrating why one metric alone is not enough.

## Scope and limitations

- This is a synthetic unit-test image, not a clinical CT benchmark.
- These values do not establish that 0.15 is optimal for every CT slice or every noise type.
- The committed `docs/results/denoising_summary.csv` contains previously generated benchmark results from the earlier 0.10 cutoff. It has deliberately not been regenerated from a guessed or substituted dataset.
- To refresh the CT benchmark, rerun `evaluate_denoising.py` against the intended local DICOM series. Only then should the generated `reports/denoising_summary.csv` and `reports/denoising_benchmark.csv` be treated as results for the new setting.
- PSNR and SSIM assess similarity to the pre-noise reference in this controlled experiment; they do not demonstrate diagnostic suitability or preservation of every clinically important structure.
