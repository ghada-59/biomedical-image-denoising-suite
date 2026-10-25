# Methods, metrics and design decisions

Scope: educational and experimental image processing. Nothing here is a diagnostic claim, and none of it has been clinically validated.

Evidence labels used below: **implemented** (code exists and is tested), **demonstrated** (a recorded run shows it, within the stated limits), **proposed** (not implemented, or not tested here). A reference being cited is not evidence that a method works on this data.

## 1. Denoising methods in the code

Nine classical (non-learned) methods. They are applied to the same noisy input, and "unfiltered" is always reported as the baseline. The six linear and rank filters are the baselines; bilateral, non-local means and wavelet shrinkage were added to test whether established edge-preserving and multi-resolution methods do better than the baselines under the same protocol.

| Method | Definition and tuned parameter | Assumes | Implementation | What to watch |
| --- | --- | --- | --- | --- |
| Mean | Box average; `kernel_size` (px; 1 = identity) | Independent noise, smooth image | `cv2.boxFilter`, reflected border | Blurs edges and small structures |
| Median | Median of a square window; `kernel_size` (px; 1 = identity) | Impulse-like outliers | `scipy.ndimage.median_filter`, reflected border | Non-linear; can flatten thin structures |
| Gaussian (spatial) | Gaussian kernel; `sigma` (px) and `kernel_size`; `sigma = 0` is an explicit identity in the benchmark | As for the mean filter | `cv2.GaussianBlur`, reflected border | OpenCV would pick a sigma itself for `sigma = 0`; the benchmark does not allow that |
| FFT ideal low-pass | Hard cutoff at `cutoff_ratio` × N/2 bins | High frequencies are noise | NumPy FFT | Ringing near edges; periodic borders; exact identity only from ratio √2 |
| FFT Gaussian low-pass | `exp(-r²/2c²)`, `c = cutoff_ratio × N/2` | As above | NumPy FFT | Strength depends on the cutoff |
| FFT Butterworth low-pass | Order 2, same cutoff convention | As above | NumPy FFT | Between the ideal and Gaussian roll-offs |
| **Bilateral** | Average over pixels close in space **and** similar in intensity; tuned: `sigma_color` (HU in the benchmark); fixed: spatial scale 1.5 px (window 11 px, a disc of radius 5) | Noise small relative to the edges to keep | `cv2.bilateralFilter` (float32), reflected border | Noise on an edge is not removed; huge `sigma_color` is a Gaussian filter |
| **Non-local means** | Average over pixels whose surrounding patches look alike; tuned: `h` (HU); fixed: patch 5×5, search distance 6 | Repeating structure; independent, roughly Gaussian noise | `skimage.restoration.denoise_nl_means`, `fast_mode=True`, `sigma=0` | The true noise level is deliberately **not** supplied; too large an `h` erases texture |
| **Wavelet (BayesShrink)** | Soft thresholding of wavelet coefficients, thresholds per sub-band, averaged over 16 circular shifts (cycle spinning); tuned: the noise level `sigma` that BayesShrink *assumes* (HU); fixed: `sym4`, 3 levels | White Gaussian noise; image sparse in the wavelet basis | `skimage.restoration.denoise_wavelet` with PyWavelets, shift loop in `filters.py` | The tuned sigma is a strength control, not a measurement of the noise; correlated and impulse noise are poorly modelled |

Why these three. Non-local means (Buades et al. 2005) is the standard patch-based classical denoiser, bilateral filtering (Tomasi and Manduchi 1998) is the cheap edge-preserving baseline, and wavelet shrinkage (Donoho and Johnstone 1994; Chang, Yu and Vetterli 2000, with the shift averaging of Coifman and Donoho 1995) is the standard multi-resolution baseline. All three are in libraries the project already depends on (scikit-image, OpenCV) plus PyWavelets, so no extra compiled dependency was needed. Their stated assumptions are checked, not assumed: each method gets one tuned strength, selected on tuning slices only.

Parameter-selection strategy. Every family gets exactly **one tuned scalar** (kernel size, sigma, cutoff, or the strength of the added methods), so no family has a larger search budget than the others. The other hyper-parameters are fixed and recorded in every selected configuration:

- Bilateral spatial scale 1.5 px. Sweeps on the **tuning slices only** showed that the best spatial scale depends on the noise type (about 1 px for white noise, 3 px for correlated and impulse noise); 1.5 px is the compromise. It is a documented compromise, not an optimum.
- Non-local means patch 5×5 and search distance 6: the values used in the scikit-image documentation's example for the fast algorithm; not tuned.
- Wavelet `sym4` with 3 levels and 16 shifts: chosen a priori; not tuned. Three levels is scikit-image's default for this image size (three fewer than the maximum, which is 6 for a 512-pixel image with `sym4`); the code refuses a level the image cannot support.
- The strength grids (19, 17 and 18 values from 5 to 800, 3 to 260 and 5 to 500 HU, plus the identity) were fixed from sweeps over the three tuning slices **before** any test slice was scored with the new methods. The run was then executed once; a second full run from a clean clone reproduced every result file byte for byte.

Computational cost (this laptop, one 512×512 slice, single run): bilateral about 0.01–0.03 s, non-local means about 0.2 s, wavelet with 16 shifts about 0.2 s; in the interactive lab a 1024×1024 image takes about 0.9 s each for non-local means and wavelet shrinkage and under 0.5 s for bilateral. Memory in the hosted API is discussed in the README.

Checks in the test suite: identity settings return the input; the FFT transfer functions equal their analytic definitions; mean, median, Gaussian, FFT, bilateral, non-local means and wavelet filters commute with the affine HU normalisation used by the benchmark when their strength is expressed in the same units (this is what makes filtering a normalised image equal to filtering in HU); a very large bilateral intensity scale equals a disc-truncated Gaussian computed independently; the shift-averaged wavelet equals the mean of the individually shifted results; filters keep the image shape; invalid parameters are rejected. A test shows the six original families give **identical** tables inside a run that also contains the three added ones.

Not implemented, deliberately:

- **BM3D** (Dabov et al. 2007): the strongest classical benchmark for white Gaussian noise of *known* variance, but it needs an extra compiled dependency, assumes exactly the noise that two of the eight scenarios violate, and adds a fourth tuned method. It is a reasonable future baseline (proposed, not tested).
- Anisotropic diffusion and learned models (section 5).

## 2. Metrics

| Metric | Definition | Domain | Notes |
| --- | --- | --- | --- |
| RMSE_HU | `sqrt(mean((output − reference)²))` over the mask | Hounsfield units, unclipped | The tuning criterion |
| MAE_HU | `mean(|output − reference|)` over the mask | Hounsfield units, unclipped | |
| PSNR (dB) | `10 log10(1 / MSE)` over the mask, peak 1 | Images displayed with the window centre −600 HU, width 1500 HU, clipped to [0, 1] | Not a PSNR on HU values; saturation at the window limits is part of the definition |
| SSIM | Wang et al. (2004): 11×11 Gaussian window, σ = 1.5, K1 = 0.01, K2 = 0.03, `data_range` 1 | Same displayed images | Mean over pixels whose whole window lies inside the mask; the scikit-image default 7×7 uniform-window SSIM is also reported, and all-pixel variants are kept as sensitivity columns |

The interactive lab computes PSNR and SSIM (scikit-image, `data_range` 1, default 7×7 uniform window) on the image mapped to [0, 1]. For DICOM input that is the file's own window (or min–max), **not** Hounsfield units, and the lab says so.

The input functions reject NaN, Inf, mismatched shapes and non-2D arrays instead of returning a number.

A lower RMSE or a higher SSIM measures similarity to a reference that is itself a noisy clinical slice. It is not a measure of diagnostic quality or of preserved anatomy. RMSE_HU, PSNR and SSIM can prefer different settings (on the tuning slices SSIM chose the same parameters as RMSE_HU in only 6 of 48 cases of the extended-grid run). No metric of small-structure, edge or texture preservation is implemented, so **no claim about preserved detail is made**; the dashboard shows the error in a 3 px band along the mask edge versus deeper regions, which is a descriptive split, not such a metric.

## 3. Evaluation regions

- **Principal mask:** largest connected region above −500 HU, holes filled, computed once per slice from the clean reference.
- **Inner mask:** the principal mask without every pixel within 10 px of the scanner padding (≤ −1500 HU). An experimental sensitivity choice, not validated.
- **Boundary band:** the 3 px along the principal mask edge. It is about 2 % of the mask yet carries most of the squared error after smoothing, so RMSE_HU on the principal mask is largely a boundary criterion. The dashboard shows both masks and the band/core split rather than one averaged number.

## 4. Protocol (summary)

Tuning slices and test slices are disjoint slices of one series and use different noise seeds. Parameters are chosen with RMSE_HU on the principal mask using the tuning slices only, then frozen. Test results are paired differences over slices with percentile bootstrap intervals. Noise repetitions on one slice are averaged first; they are not independent observations. The test slices of the first run were inspected before the grid was extended, so the comparison between the two grids is not an independent validation. The three added families were evaluated on those test slices for the first time in the "methods" run, with grids fixed beforehand from the tuning slices; the slices themselves are not untouched, and the choice of which methods to add was made after the earlier results were known. See the README for the numbers and their limits.

### Noise levels, and what the reference already contains

The synthetic levels (10, 25, 50 HU) are **scenarios**. No source was found that supports calling them typical clinical levels, and none is claimed. Two facts about the reference slices matter for reading the results:

- The reference is a real reconstructed slice with its own noise, and the synthetic noise is **added to it**. A rough, white-noise-equivalent estimate of the reference's own high-frequency noise (median-based variant of the Laplacian-mask estimator of Immerkær 1996, on soft tissue, 11 slices) is **about 3.2 HU (range 2.7 to 4.2 HU)**. This is a lower bound for the reference's total noise: real CT noise is spatially correlated, so a high-pass estimate captures only part of it. A different statistic in an earlier read-only audit, the local standard deviation on slice 50, gave about 24 HU in soft tissue and 32 HU in lung, but that includes anatomy and low-frequency texture. Estimates of "the noise in this image" therefore differ by roughly an order of magnitude depending on the definition, and no single number is the noise level.
- Consequently the 10 HU scenario is small next to the reference's *total* variation but large next to its *high-frequency* noise. Rankings of methods are comparisons of similarity to this particular noisy reference; absolute noise statements are not supported.

## 5. Decision on deep learning

**Decision: no trained or pre-trained denoising network is included in this version.** The classical filters are the core of the project, and this is the conclusion the available data support. The decision was re-examined when the added methods were chosen and did not change.

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

Candidate approaches for a future version (proposed, not implemented), to be judged on their own protocol:

- **Supervised denoising with paired low-dose and normal-dose scans** (a residual CNN such as DnCNN, Zhang et al. 2017, is a typical baseline), only with a patient-level train/validation/test split and with training data from many patients. Public paired data exist: the AAPM/Mayo Low Dose CT Grand Challenge data (McCollough et al. 2017) and the TCIA "Low Dose CT Image and Projection Data" collection (Moen et al. 2021). Their licences, sizes and versions must be checked on the TCIA page before use; this was not done here.
- **Self-supervised approaches**: Noise2Noise (Lehtinen et al. 2018) needs independent noisy pairs; Noise2Void (Krull et al. 2019) assumes noise independent between pixels, which does not hold for correlated CT noise, so it would need to be tested, not assumed.
- Methods designed specifically for CT, if they come with a validated noise model and public data.
- Eulig et al. (2024) report that published low-dose CT denoisers are compared under inconsistent designs and that newer methods often perform similarly to or worse than older ones; this is the reason the comparison here is tuned and held out.

What would make a model scientifically meaningful here: many patients, real low-dose and normal-dose pairs or a validated noise simulator, a split by patient, a baseline comparison, evidence on small structures (not only on global metrics), and an analysis of failure cases. Without these, adding a network would make the repository look more advanced without making it more correct.

## 6. References

The bibliographic records below (title, authors, year, venue, volume, pages, DOI) were checked against Crossref, PubMed and the publishers' pages on 2026-10-25. **No full text was read**; what is said about each method comes from the libraries' official documentation (scikit-image 0.26, OpenCV 5.0) and from the code. A reference is listed to credit the method, not as evidence about this data. The verification log is kept with the final report.

Methods and software

- Tomasi C, Manduchi R. Bilateral filtering for gray and color images. *Proc. 6th ICCV*, 1998, pp. 839–846. doi:10.1109/ICCV.1998.710815
- Buades A, Coll B, Morel J-M. A non-local algorithm for image denoising. *Proc. CVPR*, 2005, vol. 2, pp. 60–65. doi:10.1109/CVPR.2005.38
- Donoho DL, Johnstone IM. Ideal spatial adaptation by wavelet shrinkage. *Biometrika* 1994;81(3):425–455. doi:10.1093/biomet/81.3.425
- Donoho DL. De-noising by soft-thresholding. *IEEE Trans Inf Theory* 1995;41(3):613–627. doi:10.1109/18.382009
- Coifman RR, Donoho DL. Translation-invariant de-noising. In: *Wavelets and Statistics*, Lecture Notes in Statistics 103, Springer, 1995, pp. 125–150. doi:10.1007/978-1-4612-2544-7_9
- Chang SG, Yu B, Vetterli M. Adaptive wavelet thresholding for image denoising and compression. *IEEE Trans Image Process* 2000;9(9):1532–1546. doi:10.1109/83.862633
- Dabov K, Foi A, Katkovnik V, Egiazarian K. Image denoising by sparse 3-D transform-domain collaborative filtering. *IEEE Trans Image Process* 2007;16(8):2080–2095. doi:10.1109/TIP.2007.901238 (considered, not implemented)
- Immerkær J. Fast noise variance estimation. *Comput Vis Image Underst* 1996;64(2):300–302. doi:10.1006/cviu.1996.0060 (the project uses a median-based variant)
- Wang Z, Bovik AC, Sheikh HR, Simoncelli EP. Image quality assessment: from error visibility to structural similarity. *IEEE Trans Image Process* 2004;13(4):600–612. doi:10.1109/TIP.2003.819861
- van der Walt S, Schönberger JL, Nunez-Iglesias J, et al. scikit-image: image processing in Python. *PeerJ* 2014;2:e453. doi:10.7717/peerj.453
- Lee GR, Gommers R, Waselewski F, Wohlfahrt K, O'Leary A. PyWavelets: a Python package for wavelet analysis. *J Open Source Softw* 2019;4(36):1237. doi:10.21105/joss.01237

Data and benchmarking context

- Armato SG III, McLennan G, Bidaut L, et al. The Lung Image Database Consortium (LIDC) and Image Database Resource Initiative (IDRI): a completed reference database of lung nodules on CT scans. *Med Phys* 2011;38(2):915–931. doi:10.1118/1.3528204
- Armato SG III et al. Data From LIDC-IDRI. The Cancer Imaging Archive, 2015. doi:10.7937/K9/TCIA.2015.LO9QL9SX (the DOI resolves to the TCIA collection page, which states the CC BY 3.0 licence)
- Clark K, Vendt B, Smith K, et al. The Cancer Imaging Archive (TCIA): maintaining and operating a public information repository. *J Digit Imaging* 2013;26(6):1045–1057. doi:10.1007/s10278-013-9622-7
- Eulig E, Ommer B, Kachelrieß M. Benchmarking deep learning-based low-dose CT image denoising algorithms. *Med Phys* 2024;51(12):8776–8788. doi:10.1002/mp.17379
- McCollough CH, Bartley AC, Carter RE, et al. Low-dose CT for the detection and classification of metastatic liver lesions: results of the 2016 Low Dose CT Grand Challenge. *Med Phys* 2017;44(10):e339–e352. doi:10.1002/mp.12345
- Moen TR, Chen B, Holmes DR III, et al. Low-dose CT image and projection dataset. *Med Phys* 2021;48(2):902–911 (online 2020). doi:10.1002/mp.14594

Learned denoisers (proposed future work, not implemented)

- Zhang K, Zuo W, Chen Y, Meng D, Zhang L. Beyond a Gaussian denoiser: residual learning of deep CNN for image denoising. *IEEE Trans Image Process* 2017;26(7):3142–3155. doi:10.1109/TIP.2017.2662206
- Krull A, Buchholz T-O, Jug F. Noise2Void – learning denoising from single noisy images. *Proc. CVPR*, 2019, pp. 2124–2132. doi:10.1109/CVPR.2019.00223
- Lehtinen J, Munkberg J, Hasselgren J, et al. Noise2Noise: learning image restoration without clean data. *Proc. 35th ICML*, PMLR 80:2965–2974, 2018 (no DOI).

Limits of the review: targeted, not systematic; PubMed, Elicit and Context7 connectors were not available in the session, so Crossref and PubMed records were read through web requests; the identity of the local DICOM series with the public TCIA release is still unverified.
