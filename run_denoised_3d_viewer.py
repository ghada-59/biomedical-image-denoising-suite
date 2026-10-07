import vtk

from src.dicom_volume import load_dicom_volume
from src.volume_denoising import gaussian_denoise_volume
from src.vtk_viewer import numpy_to_vtk_volume


SERIES_DIR = r"data\tcia\LIDC-IDRI-0709"
SIGMA = 1.0


# ============================================================
# Load DICOM series and reconstruct 3D volume
# ============================================================

volume, spacing, origin = load_dicom_volume(SERIES_DIR)


# ============================================================
# Apply 3D Gaussian denoising
# ============================================================

denoised = gaussian_denoise_volume(
    volume,
    sigma=SIGMA,
)


# ============================================================
# Convert NumPy volumes to VTK ImageData
# ============================================================

original_image = numpy_to_vtk_volume(
    volume,
    spacing,
    origin,
)

denoised_image = numpy_to_vtk_volume(
    denoised,
    spacing,
    origin,
)


# ============================================================
# Create VTK volume renderer
# ============================================================

def create_volume(image):
    mapper = vtk.vtkSmartVolumeMapper()
    mapper.SetInputData(image)

    volume_property = vtk.vtkVolumeProperty()

    volume_property.ShadeOn()
    volume_property.SetInterpolationTypeToLinear()

    # --------------------------------------------------------
    # Pseudo-color mapping of CT intensity values
    # --------------------------------------------------------

    color = vtk.vtkColorTransferFunction()

    color.AddRGBPoint(
        -1000,
        0.05, 0.05, 0.10
    )

    color.AddRGBPoint(
        -700,
        0.10, 0.25, 0.80
    )

    color.AddRGBPoint(
        -400,
        0.10, 0.70, 0.95
    )

    color.AddRGBPoint(
        -100,
        0.20, 0.90, 0.70
    )

    color.AddRGBPoint(
        100,
        0.95, 0.85, 0.20
    )

    color.AddRGBPoint(
        300,
        1.00, 0.45, 0.10
    )

    color.AddRGBPoint(
        700,
        0.90, 0.10, 0.10
    )

    # --------------------------------------------------------
    # Opacity mapping
    # --------------------------------------------------------

    opacity = vtk.vtkPiecewiseFunction()

    opacity.AddPoint(-1000, 0.00)
    opacity.AddPoint(-700, 0.005)
    opacity.AddPoint(-400, 0.015)
    opacity.AddPoint(-100, 0.035)
    opacity.AddPoint(100, 0.08)
    opacity.AddPoint(300, 0.18)
    opacity.AddPoint(700, 0.30)

    volume_property.SetColor(color)
    volume_property.SetScalarOpacity(opacity)

    # --------------------------------------------------------
    # Create volume actor
    # --------------------------------------------------------

    volume_actor = vtk.vtkVolume()
    volume_actor.SetMapper(mapper)
    volume_actor.SetProperty(volume_property)

    return volume_actor


# ============================================================
# Create original and denoised volume actors
# ============================================================

original_actor = create_volume(original_image)
denoised_actor = create_volume(denoised_image)


# ============================================================
# Original CT renderer
# ============================================================

renderer_original = vtk.vtkRenderer()

renderer_original.AddVolume(
    original_actor
)

renderer_original.SetBackground(
    0.03, 0.03, 0.05
)

renderer_original.SetViewport(
    0.0, 0.0, 0.5, 1.0
)


# ============================================================
# Denoised CT renderer
# ============================================================

renderer_denoised = vtk.vtkRenderer()

renderer_denoised.AddVolume(
    denoised_actor
)

renderer_denoised.SetBackground(
    0.03, 0.03, 0.05
)

renderer_denoised.SetViewport(
    0.5, 0.0, 1.0, 1.0
)


# ============================================================
# Use the same camera for both volumes
# ============================================================

renderer_original.ResetCamera()

shared_camera = renderer_original.GetActiveCamera()

renderer_denoised.SetActiveCamera(
    shared_camera
)

renderer_denoised.ResetCameraClippingRange()


# ============================================================
# Render window
# ============================================================

render_window = vtk.vtkRenderWindow()

render_window.AddRenderer(
    renderer_original
)

render_window.AddRenderer(
    renderer_denoised
)

render_window.SetSize(
    1400,
    800
)

render_window.SetWindowName(
    "LIDC-IDRI CT - Original vs Denoised"
)


# ============================================================
# Interaction
# ============================================================

interactor = vtk.vtkRenderWindowInteractor()

interactor.SetRenderWindow(
    render_window
)


# ============================================================
# Start visualization
# ============================================================

render_window.Render()

interactor.Start()