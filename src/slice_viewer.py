import matplotlib.pyplot as plt

from src.dicom_volume import load_dicom_volume


SERIES_DIR = r"data\tcia\LIDC-IDRI-0709"


volume, spacing, _ = load_dicom_volume(SERIES_DIR)

axial_index = volume.shape[0] // 2
coronal_index = volume.shape[1] // 2
sagittal_index = volume.shape[2] // 2

axial = volume[axial_index, :, :]
coronal = volume[:, coronal_index, :]
sagittal = volume[:, :, sagittal_index]

fig, axes = plt.subplots(1, 3, figsize=(15, 5))

axes[0].imshow(
    axial,
    cmap="gray",
    aspect=spacing[1] / spacing[0],
)

axes[1].imshow(
    coronal,
    cmap="gray",
    aspect=spacing[2] / spacing[0],
)

axes[2].imshow(
    sagittal,
    cmap="gray",
    aspect=spacing[2] / spacing[1],
)

plt.tight_layout()
plt.show()