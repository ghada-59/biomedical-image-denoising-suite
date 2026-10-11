# 3D CT Viewer — Validation Report

## Objective

Validate 3D visualization of a local CT DICOM series and export documentation figures.

## Input data

- Dataset: local TCIA LIDC-IDRI-0709 series
- Modality: CT
- Number of DICOM files in the series: 100
- Input data remains local and is not included in this repository's documentation images.

## Generated figures

### Original CT volume

- File: `docs/images/ct_volume_3d_grayscale.png`
- Visualization: grayscale
- Status: generated successfully

### Original versus Gaussian-smoothed CT volume

- File: `docs/images/original_vs_smoothed_ct_3d_pseudocolor.png`
- Visualization: HU pseudo-color
- Gaussian sigma: 1.0 mm
- Status: generated successfully

## Warnings

VTK reported that text shadows are not supported with math text. Both rendering commands completed and saved their output figures. The warning did not prevent image generation.

## Interpretation and limitations

These figures demonstrate 3D CT visualization and Gaussian smoothing. Visual comparison alone does not establish improved diagnostic quality or clinical benefit. No quantitative 3D image-quality improvement is claimed here.

## Reproducibility

Run from the repository root with the local DICOM series available:

```powershell
python run_3d_viewer.py "data\tcia\LIDC-IDRI-0709\1.3.6.1.4.1.14519.5.2.1.6279.6001.309707676674808510671394142910" --output "outputs\ct_volume_3d.png" --color-mode grayscale

python run_denoised_3d_viewer.py "data\tcia\LIDC-IDRI-0709\1.3.6.1.4.1.14519.5.2.1.6279.6001.309707676674808510671394142910" --output "outputs\original_vs_smoothed_ct_3d_color.png" --color-mode hu-pseudocolor --sigma-mm 1.0
```

Generated runtime files are kept in `outputs/`. Only the selected figures are copied into `docs/images/` for publication.
