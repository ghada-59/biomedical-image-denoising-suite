"""Render, compare and export original and 3D-smoothed CT volumes."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import vtk
from src.dicom_volume import load_dicom_volume
from src.volume_denoising import gaussian_denoise_volume
from src.vtk_viewer import numpy_to_vtk_volume, save_render_window_png


def make_actor(image):
    mapper=vtk.vtkSmartVolumeMapper(); mapper.SetInputData(image)
    prop=vtk.vtkVolumeProperty(); prop.ShadeOn(); prop.SetInterpolationTypeToLinear()
    color=vtk.vtkColorTransferFunction()
    for value,rgb in [(-1000,(.05,.05,.1)),(-700,(.1,.25,.8)),(-400,(.1,.7,.95)),(-100,(.2,.9,.7)),(100,(.95,.85,.2)),(300,(1,.45,.1)),(700,(.9,.1,.1))]:
        color.AddRGBPoint(value,*rgb)
    opacity=vtk.vtkPiecewiseFunction()
    for value,alpha in [(-1000,0),(-700,.005),(-400,.015),(-100,.035),(100,.08),(300,.18),(700,.3)]:
        opacity.AddPoint(value,alpha)
    prop.SetColor(color); prop.SetScalarOpacity(opacity)
    actor=vtk.vtkVolume(); actor.SetMapper(mapper); actor.SetProperty(prop)
    return actor


def main():
    parser=argparse.ArgumentParser(description="Compare original and Gaussian-smoothed CT volumes.")
    parser.add_argument("series_dir")
    parser.add_argument("--sigma-mm","--sigma",dest="sigma_mm",type=float,default=1.0,
                        help="Gaussian standard deviation in physical millimetres.")
    parser.add_argument("--output",type=Path,default=Path("reports/3D/original_vs_smoothed_ct.png"))
    args=parser.parse_args()
    if not np.isfinite(args.sigma_mm) or args.sigma_mm<=0:
        parser.error("--sigma-mm must be finite and greater than zero.")
    volume,spacing,origin,direction=load_dicom_volume(args.series_dir)
    smoothed=gaussian_denoise_volume(volume,sigma=args.sigma_mm,spacing_xyz_mm=spacing)
    left=vtk.vtkRenderer(); right=vtk.vtkRenderer()
    left.AddVolume(make_actor(numpy_to_vtk_volume(volume,spacing,origin,direction)))
    right.AddVolume(make_actor(numpy_to_vtk_volume(smoothed,spacing,origin,direction)))
    left.SetBackground(.03,.03,.05); right.SetBackground(.03,.03,.05)
    left.SetViewport(0,0,.5,1); right.SetViewport(.5,0,1,1)
    left.ResetCamera()
    right.SetActiveCamera(left.GetActiveCamera())
    window=vtk.vtkRenderWindow(); window.AddRenderer(left); window.AddRenderer(right)
    window.SetSize(1400,800); window.SetWindowName(f"CT Original vs Smoothed — sigma {args.sigma_mm:g} mm")
    interactor=vtk.vtkRenderWindowInteractor(); interactor.SetRenderWindow(window)
    save_render_window_png(window,args.output)
    interactor.Start()

if __name__=="__main__":
    main()
