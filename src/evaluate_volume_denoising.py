from pathlib import Path

import numpy as np

from src.dicom_volume import load_dicom_volume
from src.volume_denoising import gaussian_denoise_volume


SERIES_DIR = r"data\tcia\LIDC-IDRI-0709"
SIGMA = 1.0

REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)

REPORT_FILE = REPORT_DIR / "volume_denoising_report.txt"


volume, spacing, origin = load_dicom_volume(SERIES_DIR)

denoised = gaussian_denoise_volume(
    volume,
    sigma=SIGMA,
)

difference = denoised - volume.astype(np.float32)

original_mean = float(np.mean(volume))
original_std = float(np.std(volume))

denoised_mean = float(np.mean(denoised))
denoised_std = float(np.std(denoised))

mean_absolute_difference = float(
    np.mean(np.abs(difference))
)

difference_std = float(np.std(difference))


report = f"""3D CT Denoising Evaluation
============================

Dataset: LIDC-IDRI
Series: LIDC-IDRI-0709

Volume
------
Shape: {volume.shape}
Voxel spacing (mm): {spacing[0]:.2f} x {spacing[1]:.2f} x {spacing[2]:.2f}

Denoising
---------
Method: Gaussian filter
Sigma: {SIGMA}

Original volume
---------------
Mean: {original_mean:.4f}
Std: {original_std:.4f}
Min: {float(np.min(volume)):.4f}
Max: {float(np.max(volume)):.4f}

Denoised volume
---------------
Mean: {denoised_mean:.4f}
Std: {denoised_std:.4f}
Min: {float(np.min(denoised)):.4f}
Max: {float(np.max(denoised)):.4f}

Difference
----------
Mean absolute difference: {mean_absolute_difference:.4f}
Std of difference: {difference_std:.4f}
"""


REPORT_FILE.write_text(
    report,
    encoding="utf-8",
)

print(report)
print(f"Report saved to: {REPORT_FILE}")