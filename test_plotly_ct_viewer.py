import numpy as np
import plotly.graph_objects as go
import pytest

from src.plotly_ct_viewer import create_ct_html_report, create_ct_volume_figure


def test_create_ct_volume_figure_returns_interactive_volume():
    volume = np.arange(8 * 10 * 12, dtype=np.float32).reshape(8, 10, 12)
    figure = create_ct_volume_figure(
        volume,
        spacing_xyz_mm=(0.7, 0.7, 1.5),
        origin_xyz_mm=(10.0, 20.0, 30.0),
        direction_matrix=np.eye(3),
        intensity_min=0,
        intensity_max=float(volume.max()),
    )

    assert isinstance(figure, go.Figure)
    assert len(figure.data) == 1
    assert isinstance(figure.data[0], go.Volume)
    assert len(figure.data[0].value) == volume.size


def test_large_volume_is_downsampled_for_browser_rendering():
    volume = np.zeros((130, 130, 130), dtype=np.float32)
    volume[30:100, 30:100, 30:100] = 100
    figure = create_ct_volume_figure(
        volume,
        spacing_xyz_mm=(1.0, 1.0, 1.0),
        intensity_min=0,
        intensity_max=100,
        max_axis=32,
    )

    assert figure.data[0].value.size <= 32 ** 3


@pytest.mark.parametrize(
    "volume, spacing, low, high",
    [
        (np.zeros((10, 10)), (1, 1, 1), 0, 1),
        (np.zeros((4, 4, 4)), (1, 0, 1), 0, 1),
        (np.zeros((4, 4, 4)), (1, 1, 1), 2, 1),
    ],
)
def test_invalid_volume_or_display_parameters_raise(volume, spacing, low, high):
    with pytest.raises(ValueError):
        create_ct_volume_figure(
            volume,
            spacing_xyz_mm=spacing,
            intensity_min=low,
            intensity_max=high,
        )



def test_html_report_embeds_plot_and_escapes_metadata():
    volume = np.arange(4 * 5 * 6, dtype=np.float32).reshape(4, 5, 6)
    figure = create_ct_volume_figure(
        volume,
        spacing_xyz_mm=(0.8, 0.8, 1.2),
        intensity_min=0,
        intensity_max=float(volume.max()),
    )
    html = create_ct_html_report(
        figure,
        {
            "Number of slices": "4",
            "Study label": "<script>alert('x')</script>",
        },
    )

    assert "<!DOCTYPE html>" in html
    assert "Interactive CT Volume Report" in html
    assert "Number of slices" in html
    assert "<script>alert('x')</script>" not in html
    assert "&lt;script&gt;" in html
    assert "plotly" in html.lower()
