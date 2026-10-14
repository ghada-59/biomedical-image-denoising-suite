"""Interactive Plotly volume rendering for CT DICOM data."""
from __future__ import annotations

import math

import numpy as np
import plotly.graph_objects as go


def create_ct_volume_figure(
    volume: np.ndarray,
    spacing_xyz_mm,
    origin_xyz_mm=None,
    direction_matrix=None,
    intensity_min: float = -1000,
    intensity_max: float = 400,
    max_axis: int = 48,
) -> go.Figure:
    """Create a browser-interactive CT volume figure from a (z, y, x) array.

    The array is sampled down along its longest dimension for browser performance.
    DICOM spacing, origin and direction preserve the physical geometry. Values are
    modality values (HU for conventional CT data).
    """
    if not isinstance(volume, np.ndarray) or volume.ndim != 3 or volume.size == 0:
        raise ValueError("volume must be a non-empty 3D NumPy array.")
    if not np.isfinite(volume).all():
        raise ValueError("volume must contain only finite values.")
    if isinstance(max_axis, bool) or not isinstance(max_axis, int) or max_axis < 2:
        raise ValueError("max_axis must be an integer >= 2.")
    if not np.isfinite(intensity_min) or not np.isfinite(intensity_max):
        raise ValueError("The display intensity range must be finite.")
    if intensity_max <= intensity_min:
        raise ValueError("intensity_max must be greater than intensity_min.")

    spacing = np.asarray(spacing_xyz_mm, dtype=float)
    if spacing.shape != (3,) or not np.isfinite(spacing).all() or np.any(spacing <= 0):
        raise ValueError("spacing_xyz_mm must contain three positive finite values.")

    origin = (
        np.zeros(3, dtype=float)
        if origin_xyz_mm is None
        else np.asarray(origin_xyz_mm, dtype=float)
    )
    if origin.shape != (3,) or not np.isfinite(origin).all():
        raise ValueError("origin_xyz_mm must contain three finite values.")

    direction = (
        np.eye(3, dtype=float)
        if direction_matrix is None
        else np.asarray(direction_matrix, dtype=float)
    )
    if direction.shape != (3, 3) or not np.isfinite(direction).all():
        raise ValueError("direction_matrix must be a finite 3x3 matrix.")
    if not np.allclose(direction.T @ direction, np.eye(3), atol=1e-3):
        raise ValueError("direction_matrix must be orthonormal.")

    stride = max(1, math.ceil(max(volume.shape) / max_axis))
    sampled = np.asarray(volume[::stride, ::stride, ::stride], dtype=np.float32)
    nz, ny, nx = sampled.shape

    x = np.arange(nx, dtype=np.float32) * float(spacing[0]) * stride
    y = np.arange(ny, dtype=np.float32) * float(spacing[1]) * stride
    z = np.arange(nz, dtype=np.float32) * float(spacing[2]) * stride
    grid_z, grid_y, grid_x = np.meshgrid(z, y, x, indexing="ij")
    local_coordinates = np.vstack(
        (grid_x.ravel(), grid_y.ravel(), grid_z.ravel())
    ).astype(np.float64, copy=False)
    patient_coordinates = origin[:, None] + direction @ local_coordinates

    figure = go.Figure(
        data=[
            go.Volume(
                x=patient_coordinates[0],
                y=patient_coordinates[1],
                z=patient_coordinates[2],
                value=sampled.ravel(),
                isomin=float(intensity_min),
                isomax=float(intensity_max),
                opacity=0.10,
                opacityscale="extremes",
                surface_count=16,
                colorscale="Greys",
                caps={"x_show": False, "y_show": False, "z_show": False},
                colorbar={"title": "CT value"},
                name="CT volume",
            )
        ]
    )
    figure.update_layout(
        title=f"Interactive CT Volume — {volume.shape[2]} × {volume.shape[1]} × {volume.shape[0]} voxels",
        margin={"l": 0, "r": 0, "t": 48, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        scene={
            "xaxis_title": "Patient X (mm)",
            "yaxis_title": "Patient Y (mm)",
            "zaxis_title": "Patient Z (mm)",
            "aspectmode": "data",
            "bgcolor": "rgba(0,0,0,0)",
        },
    )
    return figure



def create_ct_html_report(figure: go.Figure, metadata: dict[str, str]) -> str:
    """Build a self-contained HTML report with the interactive figure and metadata."""
    from html import escape

    if not isinstance(figure, go.Figure):
        raise TypeError("figure must be a Plotly Figure.")
    if not isinstance(metadata, dict):
        raise TypeError("metadata must be a dictionary of labels and values.")

    rows = []
    for label, value in metadata.items():
        rows.append(
            "<tr><th>" + escape(str(label)) + "</th><td>" + escape(str(value)) + "</td></tr>"
        )
    table = "\\n".join(rows)
    figure_html = figure.to_html(
        full_html=False,
        include_plotlyjs=True,
        config={"displaylogo": False, "scrollZoom": True, "responsive": True},
    )
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Interactive CT Volume Report</title>
<style>
body { margin: 0; background: #f4f6f8; color: #17212b; font-family: Arial, Helvetica, sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 28px 22px 40px; }
header, section { background: #fff; border: 1px solid #dfe5eb; border-radius: 12px; padding: 22px; margin-bottom: 18px; }
h1 { margin: 0 0 8px; font-size: 26px; }
.subtitle { color: #536273; margin: 0; }
h2 { margin-top: 0; font-size: 18px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #e8edf2; vertical-align: top; }
th { width: 38%; color: #34465a; font-weight: 600; }
tr:last-child th, tr:last-child td { border-bottom: 0; }
.notice { border-left: 4px solid #d49b32; padding: 10px 14px; background: #fff8e8; color: #624b1d; line-height: 1.5; }
footer { color: #536273; font-size: 12px; line-height: 1.5; padding: 4px 2px; }
@media (max-width: 650px) { main { padding: 12px; } header, section { padding: 14px; } th, td { padding: 8px 6px; } }
</style>
</head>
<body>
<main>
<header>
<h1>Interactive CT Volume Report</h1>
<p class="subtitle">Biomedical Image Denoising Suite · Interactive 3D visualization</p>
</header>
<section>
<h2>Volume metadata</h2>
<table><tbody>""" + table + """</tbody></table>
</section>
<section>
<h2>Interactive 3D volume</h2>
<p class="subtitle">Drag to rotate, scroll to zoom, and use the Plotly controls to explore the rendered volume.</p>
""" + figure_html + """
</section>
<p class="notice"><strong>Research and educational use only.</strong> This visualization is not a diagnostic tool. The displayed volume may contain sensitive medical information; store and share this HTML report securely.</p>
<footer>Values and geometry are based on the selected DICOM series. The rendering may be downsampled for browser performance; it is intended for visualization and not for diagnostic interpretation.</footer>
</main>
</body>
</html>"""
