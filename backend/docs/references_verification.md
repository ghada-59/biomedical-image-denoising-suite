# Verification of the scientific references (2026-10-25)

**What was checked.** Bibliographic records only: title, authors, year, venue, volume/issue/pages and DOI were read from the
Crossref REST API (`api.crossref.org/works/<DOI>`), PubMed E-utilities (`esummary`, PMID 29027235), the PMLR page of the ICML 2018 paper and the TCIA
collection page. **No paper's full text or abstract was read.** Statements about what a method does come from the official
documentation of the installed libraries (scikit-image 0.26.0 docstrings, OpenCV 5.0.0) and from the code itself, and are marked as such in the project documents.
The records were read from the public web interfaces named above. The review is targeted, not a systematic literature search.

| # | Reference | Verified fields | Used for | Notes |
|---|---|---|---|---|
| 1 | Wang Z, Bovik AC, Sheikh HR, Simoncelli EP. Image quality assessment: from error visibility to structural similarity. *IEEE Trans Image Process* 2004;13(4):600–612. doi:10.1109/TIP.2003.819861 | all | SSIM definition (11×11 Gaussian window, σ 1.5) | Crossref lists the first author's name in one field ("Zhou Wang") |
| 2 | Buades A, Coll B, Morel J-M. A non-local algorithm for image denoising. *CVPR 2005*, vol. 2, pp. 60–65. doi:10.1109/CVPR.2005.38 | title, authors, venue, volume, pages | non-local means | Crossref has no `issued` year; 2005 follows from the conference title and the deposit date |
| 3 | Tomasi C, Manduchi R. Bilateral filtering for gray and color images. *ICCV 1998*, pp. 839–846. doi:10.1109/ICCV.1998.710815 | title, authors, venue, pages | bilateral filter | Crossref has no `issued` year; 1998 follows from the conference title and DOI string |
| 4 | Chang SG, Yu B, Vetterli M. Adaptive wavelet thresholding for image denoising and compression. *IEEE Trans Image Process* 2000;9(9):1532–1546. doi:10.1109/83.862633 | all | BayesShrink | the scikit-image docstring cites it as the BayesShrink reference |
| 5 | Donoho DL, Johnstone IM. Ideal spatial adaptation by wavelet shrinkage. *Biometrika* 1994;81(3):425–455. doi:10.1093/biomet/81.3.425 | all | wavelet shrinkage theory | |
| 6 | Donoho DL. De-noising by soft-thresholding. *IEEE Trans Inf Theory* 1995;41(3):613–627. doi:10.1109/18.382009 | all | soft thresholding | |
| 7 | Coifman RR, Donoho DL. Translation-invariant de-noising. In: *Wavelets and Statistics* (Lecture Notes in Statistics 103). Springer; 1995:125–150. doi:10.1007/978-1-4612-2544-7_9 | all | cycle spinning (shift-averaging) | |
| 8 | Dabov K, Foi A, Katkovnik V, Egiazarian K. Image denoising by sparse 3-D transform-domain collaborative filtering. *IEEE Trans Image Process* 2007;16(8):2080–2095. doi:10.1109/TIP.2007.901238 | all | BM3D, **considered and not implemented** | |
| 9 | Immerkær J. Fast noise variance estimation. *Comput Vis Image Underst* 1996;64(2):300–302. doi:10.1006/cviu.1996.0060 | all | noise estimate of the reference slices | the project's estimator is a median-based variant, not the paper's mean-based formula |
| 10 | Eulig E, Ommer B, Kachelrieß M. Benchmarking deep learning-based low-dose CT image denoising algorithms. *Med Phys* 2024;51(12):8776–8788. doi:10.1002/mp.17379 | all | argument for fair, tuned comparisons | |
| 11 | Armato SG III et al. (56 authors). The Lung Image Database Consortium (LIDC) and Image Database Resource Initiative (IDRI): a completed reference database of lung nodules on CT scans. *Med Phys* 2011;38(2):915–931. doi:10.1118/1.3528204 | title, first six authors, count, venue, pages | data source | |
| 12 | Armato SG III et al. Data From LIDC-IDRI. TCIA, 2015. doi:10.7937/K9/TCIA.2015.LO9QL9SX | DOI resolves (HTTP 302) to the TCIA LIDC-IDRI collection page; licence on that page: CC BY 3.0; the page asks for this citation and the Medical Physics paper | data citation | the identity of the **local series** with the public release is still not verified |
| 13 | Clark K et al. (12 authors). The Cancer Imaging Archive (TCIA): maintaining and operating a public information repository. *J Digit Imaging* 2013;26(6):1045–1057. doi:10.1007/s10278-013-9622-7 | title, first six authors, count, venue, pages | TCIA citation | |
| 14 | McCollough CH et al. (15 authors). Low-dose CT for the detection and classification of metastatic liver lesions: results of the 2016 Low Dose CT Grand Challenge. *Med Phys* 2017;44(10):e339–e352. doi:10.1002/mp.12345 | Crossref has no pages; **pages confirmed in PubMed (PMID 29027235)** | paired low-/normal-dose data (future work) | |
| 15 | Moen TR et al. (9 authors). Low-dose CT image and projection dataset. *Med Phys* 2021;48(2):902–911 (issued online 2020). doi:10.1002/mp.14594 | all | paired data (future work) | the earlier document wrote "2021;48:902"; the complete record is now stated |
| 16 | Zhang K, Zuo W, Chen Y, Meng D, Zhang L. Beyond a Gaussian denoiser: residual learning of deep CNN for image denoising. *IEEE Trans Image Process* 2017;26(7):3142–3155. doi:10.1109/TIP.2017.2662206 | all | DnCNN (future work, not implemented) | previously "not re-verified" |
| 17 | Krull A, Buchholz T-O, Jug F. Noise2Void – learning denoising from single noisy images. *CVPR 2019*, pp. 2124–2132. doi:10.1109/CVPR.2019.00223 | all | future work, not implemented | |
| 18 | Lehtinen J et al. Noise2Noise: learning image restoration without clean data. *Proc 35th ICML*, PMLR 80:2965–2974, 2018 | title, 7 authors, volume, pages (PMLR page); **no DOI** (Crossref does not hold it) | future work, not implemented | previously "venue not re-verified" |
| 19 | van der Walt S et al. (8 authors). scikit-image: image processing in Python. *PeerJ* 2014;2:e453. doi:10.7717/peerj.453 | title, first six authors, count, venue | software citation | |
| 20 | Lee GR, Gommers R, Waselewski F, Wohlfahrt K, O'Leary A. PyWavelets: a Python package for wavelet analysis. *J Open Source Softw* 2019;4(36):1237. doi:10.21105/joss.01237 | all (Crossref and the JOSS page agree, including the spelling "Waselewski") | software citation | |

**Not verified / limits.** Full texts; the claim that CT noise of 10–50 HU is "typical" (no source was found and none is claimed: the 10/25/50 HU levels are *scenarios*);
the identity of the local DICOM series with the public TCIA release; licences of the sample images other than the generated synthetic DICOM.
