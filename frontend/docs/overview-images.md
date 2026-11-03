# Overview example images

Three 512 x 512 WebP images in `frontend/public/img/`, used by the Overview page. (This note lives here, not in `public/`, so that it is not copied into the deployed site.) They are **real outputs of the project's own pipeline**, not drawings, and they illustrate what the 2D lab does. **They are not benchmark results.**

| File | What it is | How it was made |
| --- | --- | --- |
| `ct-chest-reference.webp` | The bundled sample `backend/samples/chest_ct.png`: slice 50 of the chest CT series LIDC-IDRI-0709, 8-bit, display window -600/1500 HU | Converted from the PNG to WebP (quality 85) |
| `ct-chest-noisy.webp` | The same slice with synthetic Gaussian noise (variance 0.02 on the [0, 1] scale, seed 42) | The "Noisy input" image returned by `POST /api/denoise` for that sample and those settings (WebP, quality 76) |
| `ct-chest-denoised.webp` | The noisy slice after a 5 x 5 median filter | The "Median" image returned by the same call (WebP, quality 85) |

The call was a plain HTTP request to the unchanged API (`noise_type=Gaussian`, `noise_variance=0.02`, `seed=42`, `methods=median`, `kernel_size=5`). The WebP conversion is lossy but keeps what matters at the displayed size (about 500 px).

**Attribution and licence.** The source images derive from the LIDC-IDRI collection hosted by The Cancer Imaging Archive (TCIA), licensed **CC BY 3.0**. The images are adaptations (windowed, 8-bit, noise added, filtered, re-encoded); the licence requires attribution, which the Overview page prints next to the example and the repository README gives in full. Data citation: DOI 10.7937/K9/TCIA.2015.LO9QL9SX; Armato SG III et al., Medical Physics 38(2):915-931, 2011. The images carry no patient identifier.

The same slice is already published in this repository as `backend/samples/chest_ct.png`; see `backend/samples/README.md` for its provenance.
