import vtk

from src.dicom_volume import load_dicom_volume
from src.vtk_viewer import numpy_to_vtk_volume


SERIES_DIR = r"data\tcia\LIDC-IDRI-0709"


volume, spacing, origin = load_dicom_volume(SERIES_DIR)
image = numpy_to_vtk_volume(volume, spacing, origin)

mapper = vtk.vtkSmartVolumeMapper()
mapper.SetInputData(image)

property_ = vtk.vtkVolumeProperty()
property_.ShadeOn()
property_.SetInterpolationTypeToLinear()

color = vtk.vtkColorTransferFunction()
color.AddRGBPoint(-1000, 0.0, 0.0, 0.0)
color.AddRGBPoint(-500, 0.7, 0.7, 0.7)
color.AddRGBPoint(0, 0.9, 0.9, 0.9)
color.AddRGBPoint(500, 1.0, 1.0, 1.0)

opacity = vtk.vtkPiecewiseFunction()
opacity.AddPoint(-1000, 0.0)
opacity.AddPoint(-500, 0.01)
opacity.AddPoint(-200, 0.03)
opacity.AddPoint(0, 0.08)
opacity.AddPoint(300, 0.15)
opacity.AddPoint(700, 0.25)

property_.SetColor(color)
property_.SetScalarOpacity(opacity)

volume_actor = vtk.vtkVolume()
volume_actor.SetMapper(mapper)
volume_actor.SetProperty(property_)

renderer = vtk.vtkRenderer()
renderer.AddVolume(volume_actor)
renderer.SetBackground(0.1, 0.1, 0.1)

render_window = vtk.vtkRenderWindow()
render_window.AddRenderer(renderer)
render_window.SetSize(1000, 800)
render_window.SetWindowName("LIDC-IDRI CT Volume")

interactor = vtk.vtkRenderWindowInteractor()
interactor.SetRenderWindow(render_window)

renderer.ResetCamera()
render_window.Render()
interactor.Start()