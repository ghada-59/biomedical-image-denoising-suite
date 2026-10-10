"""Render a DICOM CT volume and save a PNG snapshot."""
from __future__ import annotations
import argparse
from pathlib import Path
import vtk
from src.dicom_volume import load_dicom_volume
from src.vtk_viewer import numpy_to_vtk_volume, save_render_window_png


def main():
    parser=argparse.ArgumentParser(description="Render a DICOM CT volume and export a snapshot.")
    parser.add_argument("series_dir")
    parser.add_argument("--output",type=Path,default=Path("reports/3D/original_ct_volume.png"))
    args=parser.parse_args()
    volume,spacing,origin,direction=load_dicom_volume(args.series_dir)
    image=numpy_to_vtk_volume(volume,spacing,origin,direction)
    mapper=vtk.vtkSmartVolumeMapper(); mapper.SetInputData(image)
    prop=vtk.vtkVolumeProperty(); prop.ShadeOn(); prop.SetInterpolationTypeToLinear()
    color=vtk.vtkColorTransferFunction()
    for value,rgb in [(-1000,(0,0,0)),(-500,(0.7,0.7,0.7)),(0,(0.9,0.9,0.9)),(500,(1,1,1))]:
        color.AddRGBPoint(value,*rgb)
    opacity=vtk.vtkPiecewiseFunction()
    for value,alpha in [(-1000,0),(-500,.01),(-200,.03),(0,.08),(300,.15),(700,.25)]:
        opacity.AddPoint(value,alpha)
    prop.SetColor(color); prop.SetScalarOpacity(opacity)
    actor=vtk.vtkVolume(); actor.SetMapper(mapper); actor.SetProperty(prop)
    renderer=vtk.vtkRenderer(); renderer.AddVolume(actor); renderer.SetBackground(.1,.1,.1)
    window=vtk.vtkRenderWindow(); window.AddRenderer(renderer); window.SetSize(1000,800)
    window.SetWindowName("DICOM CT Volume")
    interactor=vtk.vtkRenderWindowInteractor(); interactor.SetRenderWindow(window)
    renderer.ResetCamera()
    save_render_window_png(window,args.output)
    interactor.Start()

if __name__=="__main__":
    main()
