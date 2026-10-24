# Methods, metrics and design decisions

Scope: educational and experimental image processing. Nothing here is a diagnostic claim, and none of it has been clinically validated.

## 1. Denoising methods in the code

All six are classical, non-learned smoothing filters. They are applied to the same noisy input; "unfiltered" is always reported as the baseline.

| Method | Definition and parameter (unit) | Edge handling | What to watch |
| --- | --- | --- | --- |
| Mean | Box average, `kernel_size` (pixels; 1 = identity) | Reflected border | Blurs edges and small structures |
| Median | Median over a square window, `kernel_size` (pixels; 1 = identity) | Reflected border | Good for impulse noise; non-linear, can flatten thin structures |
| Gaussian (spatial) | Gaussian kernel, `sigma` (pixels) and `kernel_size`; `sigma = 0` is an explicit identity | Reflected border | OpenCV would pick a sigma automatically for `sigma = 0`; the benchmark does not allow that |
| FFT ideal low-pass | Hard cutoff at `cutoff_ratio` × N/2 frequency bins | Periodic (FFT) | Ringing near edges; exact identity only from ratio √2 |
| FFT Gaussian low-pass | `exp(-r²/2c²)` transfer function, `c = cutoff_ratio × N/2` | Periodic (FFT) | Smooth roll-off; strength depends on the cutoff |
| FFT Butterworth low-pass | Order 2, same cutoff convention | Periodic (FFT) | Intermediate roll-off |

Checks in the test suite: identity settings return the input; the FFT transfer functions equal their analytic definitions; mean, median, Gaussian and FFT filters commute with the affine HU normalisation used by the benchmark; filters keep the image shape; invalid parameters are rejected.

Not implemented, deliberately: bilateral, non-local means, anisotropic diffusion, wavelet shrinkage and learned models. They are reasonable future baselines. They were not added because each would need its own tuning grid, tests and a new benchmark run; adding them without a rerun would give untested numbers in the dashboard.

## 2. Metrics

| Metric | Definition | Domain | Notes |
| --- | --- | --- | --- |
| RMSE_HU | `sqrt(mean((output − reference)²))` over the mask | Hounsfield units, unclipped | The tuning criterion |
| MAE_HU | `mean(|output − reference|)` over the mask | Hounsfield units, unclipped | |
| PSNR (dB) | `10 log10(1 / MSE)` over the mask, peak 1 | Images displayed with the window centre −600 HU, width 1500 HU, clipped to [0, 1] | Not a PSNR on HU values; saturation at the window limits is part of the definition |
| SSIM | Wang et al. (2004): 11×11 Gaussian window, σ = 1.5, K1 = 0.01, K2 = 0.03, `data_range` 1 | Same displayed images | Mean over pixels whose whole window lies inside the mask; the scikit-image default 7×7 uniform-window SSIM is also reported, and all-pixel variants are kept as sensitivity columns |

The input functions reject NaN, Inf, mismatched shapes and non-2D arrays instead of returning a number.

A lower RMSE or a higher SSIM measures similarity to a reference that is itself a noisy clinical slice. It is not a measure of diagnostic quality or of preserved anatomy. RMSE_HU, PSNR and SSIM can prefer different settings (on the tuning slices SSIM chose the same parameters as RMSE_HU in only 6 of 48 cases of the extended-grid run).

## 3. Evaluation regions

- **Principal mask:** largest connected region above −500 HU, holes filled, computed once per slice from the clean reference.
- **Inner mask:** the principal mask without every pixel within 10 px of the scanner padding (≤ −1500 HU). An experimental sensitivity choice, not validated.
- **Boundary band:** the 3 px along the principal mask edge. It is about 2 % of the mask yet carries most of the squared error after smoothing, so RMSE_HU on the principal mask is largely a boundary criterion. The dashboard shows both masks and the band/core split rather than one averaged number.

## 4. Protocol (summary)

Tuning slices and test slices are disjoint slices of one series and use different noise seeds. Parameters are chosen with RMSE_HU on the principal mask using the tuning slices only, then frozen. Test results are paired differences over slices with percentile bootstrap intervals. Noise repetitions on one slice are averaged first; they are not independent observations. The test slices of the first run were inspected before the grid was extended, so the comparison between the two grids is not an independent validation. See the README for the numbers and their limits.

## 5. Decision on deep learning

**Decision: no trained or pre-trained denoising network is included in this version.** The classical filters are the core of the project, and this is the conclusion the available data support.

Reasoning, following the questions that must be answered before adding a model:

| Question | Situation here |
| --- | --- |
| Objective | Restore a CT slice contaminated by noise whose model is known. Only a synthetic Gaussian-like noise is available; the noise is not measured scanner noise. |
| Data | One local series labelled LIDC-IDRI-0709 (100 slices of one patient). Its identity with a public release has not been verified. |
| Clean reference | None. The reference is a noisy clinical slice. A network trained to invert synthetic noise learns that synthetic noise, which says little about real CT noise. |
| Diversity | One patient, one scanner and protocol. Slices of one scan, and patches cut from them, are strongly correlated and are not independent samples. |
| Independent validation | Not possible: no second patient, scanner or dose. Several test slices were already inspected during development. |
| Hardware | A laptop GPU with limited memory (GTX 1650 Max-Q) and 16 GB of RAM. Enough for small experiments, not a limiting factor for this decision. |
| Licences and weights | No pre-trained CT weights were examined. Models trained on natural photographs are not valid for CT and are not used. |
| Success criterion | A model would have to beat the tuned classical baselines on held-out patients, by patient-level split, with a diagnostic-task or reader-based check, not only RMSE/SSIM. |

Candidate approaches for a future version, to be judged on their own protocol:

- **Supervised denoising with paired low-dose and normal-dose scans** (a residual CNN such as DnCNN is a typical baseline), only with a patient-level train/validation/test split and with training data from many patients. Public paired data exist, for example the AAPM/Mayo Low Dose CT Grand Challenge data and the TCIA "Low Dose CT Image and Projection Data" collection (McCollough et al., Med Phys 2017;44(10):e339–e352; Moen et al., Med Phys 2021;48:902, DOI 10.1002/mp.14594 as given by TCIA). Their licences, sizes and versions must be checked on the TCIA page before use; this was not done here.
- **Self-supervised approaches** (Noise2Noise needs independent noisy pairs; Noise2Void assumes noise independent between pixels). The second assumption does not hold for correlated CT noise, so it would need to be tested, not assumed. Venue and details of these two works were not re-verified in this review beyond the Noise2Void CVPR 2019 record.
- Methods designed specifically for CT, if they come with a validated noise model and public data.

What would make a model scientifically meaningful here: many patients, real low-dose and normal-dose pairs or a validated noise simulator, a split by patient, a baseline comparison, evidence on small structures (not only on global metrics), and an analysis of failure cases. Without these, adding a network would make the repository look more advanced without making it more correct.

## 6. References

- Wang Z, Bovik AC, Sheikh HR, Simoncelli EP. Image quality assessment: from error visibility to structural similarity. IEEE Trans Image Process 2004;13(4):600–612. DOI 10.1109/TIP.2003.819861.
- Armato SG III et al. Data From LIDC-IDRI. The Cancer Imaging Archive. DOI 10.7937/K9/TCIA.2015.LO9QL9SX (the DOI resolves to the TCIA collection page).
- Eulig E, Ommer B, Kachelrieß M. Benchmarking deep learning-based low-dose CT image denoising algorithms. Med Phys 2024;51(12):8776–8788.
- McCollough CH et al. Low-dose CT for the detection and classification of metastatic liver lesions: results of the 2016 Low Dose CT Grand Challenge. Med Phys 2017;44(10):e339–e352.
- Moen TR et al. Low-dose CT image and projection dataset. Med Phys 2021;48:902 (DOI 10.1002/mp.14594 per TCIA).
- Krull A, Buchholz T-O, Jug F. Noise2Void – learning denoising from single noisy images. CVPR 2019.
- Lehtinen J et al. Noise2Noise: learning image restoration without clean data. 2018 (venue not re-verified here). Zhang K et al. Beyond a Gaussian denoiser: residual learning of deep CNN for image denoising (DnCNN), 2017 (details not re-verified here).
