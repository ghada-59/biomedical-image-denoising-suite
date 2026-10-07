import matplotlib.pyplot as plt

from src.dicom_volume import load_dicom_volume
from src.volume_denoising import gaussian_denoise_volume


SERIES_DIR = r"data\tcia\LIDC-IDRI-0709"

volume, spacing, _ = load_dicom_volume(SERIES_DIR)
denoised = gaussian_denoise_volume(volume, sigma=1.0)

index = volume.shape[0] // 2

fig, axes = plt.subplots(1, 2, figsize=(10, 5))

axes[0].imshow(volume[index], cmap="gray")
axes[0].set_title("Original")
axes[0].axis("off")

axes[1].imshow(denoised[index], cmap="gray")
axes[1].set_title("Gaussian denoised")
axes[1].axis("off")

fig.suptitle(
    f"CT slice comparison — sigma={1.0}"
)

plt.tight_layout()
plt.show()