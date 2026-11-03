import { useMemo, useState } from "react";
import { Activity, Check, CircleHelp, FileImage, Info, Layers3, ShieldCheck, UploadCloud } from "lucide-react";
import { Plot } from "./plot";
import { api, apiHostLabel, apiIsLocal } from "./api";
import { EmptyState, ImagePanel, MetricCard, PageHeading } from "./components";
import { CHART_FONT, themeColors, useThemeTick, withWrappedTitle } from "./chartTheme";

/** The layout the API sends, drawn in the application's font and in the current theme's text colour (Plotly cannot read CSS variables). */
function chartLayout(layout) {
  const wrapped = withWrappedTitle(layout);
  const { text } = themeColors();
  const title = typeof wrapped.title === "string" ? { text: wrapped.title } : wrapped.title;
  return { ...wrapped, title: { ...title, font: { ...title?.font, size: 15, color: text } }, autosize: true, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { ...wrapped.font, family: CHART_FONT, color: text } };
}

// Plotly re-draws a chart whenever it is handed a new layout, data or config object, and drawing the volume is expensive. These do not change
// between renders, so unrelated re-renders (the page checks the API every few seconds) must not hand it new objects.
const CT_CONFIG = { responsive: true, displaylogo: false, scrollZoom: true };
const CT_STYLE = { width: "100%", height: "610px" };

export default function CtExplorer({ apiState = "online" }) {
  const themeTick = useThemeTick();                                     // changes with the theme and, by steps, the window width: the layout is made again then
  const [files, setFiles] = useState([]);
  const [data, setData] = useState(null);
  const [slicePreview, setSlicePreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // eslint-disable-next-line react-hooks/exhaustive-deps -- themeTick is not read inside, it is the signal that the theme or the width changed
  const layout = useMemo(() => (data ? chartLayout(data.figure.layout) : null), [data, themeTick]);

  async function selectFiles(list) {
    const chosen = Array.from(list || []);
    setFiles(chosen); setData(null); setSlicePreview(null); setError("");
    if (!chosen.length) return;
    setBusy(true);
    try {
      if (chosen.length === 1) {
        const body = new FormData();
        body.append("file", chosen[0]);
        setSlicePreview(await api("/api/image/preview", { method: "POST", body }));
        setError("One DICOM slice selected. The 2D preview is shown below; select the complete set of slices from the same CT series to reconstruct a 3D volume.");
      } else {
        const body = new FormData();
        chosen.forEach(file => body.append("files", file));
        setData(await api("/api/ct/volume", { method: "POST", body }));
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <PageHeading eyebrow="VOLUME VISUALIZATION / 02" title="3D CT Explorer"
        description="Load one complete DICOM series to reconstruct a volume, inspect its central slice and explore the interactive 3D rendering."
        action={<span className="pill"><Layers3 size={14} aria-hidden="true" /> DICOM series</span>} />
      <div className="ct-workspace">
        <aside className="ct-side" aria-label="Series import">
          <div className="ct-upload-card">
            <div className="upload-symbol"><UploadCloud size={24} aria-hidden="true" /></div>
            <div className="upload-copy">
              <h2>Import CT series</h2>
              <p>
                Select multiple .dcm slices from the same study and series.{" "}
                {apiIsLocal()
                  ? "The API runs on this computer; the files are not sent elsewhere."
                  : `The files are uploaded to the server at ${apiHostLabel()}; do not upload identifiable patient data.`}
              </p>
              <div className="file-status">{files.length ? <><Check size={14} aria-hidden="true" />{files.length} file(s) selected</> : "No files selected"}</div>
            </div>
            <label className="secondary-button">
              {files.length ? "Change files" : "Select DICOM files"}
              <input type="file" multiple accept=".dcm" aria-label="Select DICOM files" disabled={apiState === "offline"} onChange={e => selectFiles(e.target.files)} />
            </label>
          </div>
          <div className="panel preview-info">
            <p className="eyebrow">WHAT THE API ACCEPTS</p>
            <ul className="ct-guide">
              <li><Layers3 size={15} aria-hidden="true" /><span>One series: the same series UID, orientation, pixel spacing and image size. Slices are ordered by their position, not by file name.</span></li>
              <li><Info size={15} aria-hidden="true" /><span>Evenly spaced, untilted slices. A damaged, tilted or unevenly spaced series is refused with a message, never resampled.</span></li>
              <li><FileImage size={15} aria-hidden="true" /><span>This page shows the 3D rendering and the central axial slice the API returns. Coronal and sagittal views come from the command-line viewers described in the README.</span></li>
            </ul>
          </div>
        </aside>

        <div className="ct-main">
          {apiState === "offline" && <div className="error-box wide-error" role="alert"><CircleHelp size={18} aria-hidden="true" /><span>The API is not reachable, so a CT series cannot be processed right now. See the notice at the top of the page; this page works again as soon as the API answers.</span></div>}
          {busy && <div className="loading-card" role="status"><span className="spinner" aria-hidden="true" /> Reading DICOM metadata and building volume…</div>}
          {error && <div className={slicePreview ? "notice-box" : "error-box wide-error"} role={slicePreview ? "status" : "alert"}><CircleHelp size={18} aria-hidden="true" /><span>{error}</span></div>}
          {slicePreview && (
            <div className="ct-preview-grid">
              <ImagePanel title="Selected DICOM slice · 2D preview" image={slicePreview.preview} badge={slicePreview.width + " × " + slicePreview.height} large />
              <div className="panel preview-info">
                <p className="eyebrow">SLICE METADATA</p>
                <h2>{slicePreview.filename}</h2>
                <p>This file is readable as a 2D image. For a real 3D reconstruction, select the full stack of slices belonging to one series.</p>
                <div className="info-line"><span>Input type</span><strong>{slicePreview.format}</strong></div>
                <div className="info-line"><span>Dimensions</span><strong>{slicePreview.width} × {slicePreview.height}</strong></div>
              </div>
            </div>
          )}
          {data && (
            <>
              <div className="ct-metrics">
                <MetricCard label="DICOM slices" value={data.slices} hint="Instances in loaded series" icon={FileImage} />
                <MetricCard label="Volume dimensions" value={data.dimensions_xyz.join(" × ")} hint="X × Y × Z voxels" icon={Layers3} />
                <MetricCard label="Voxel spacing" value={data.spacing_xyz_mm.join(" × ") + " mm"} hint="X × Y × Z" icon={Activity} />
              </div>
              <div className="ct-viewer-panel">
                <div className="panel-heading"><span>Interactive CT volume</span><span className="mini-badge">3D · PLOTLY</span></div>
                <Plot data={data.figure.data} layout={layout} config={CT_CONFIG} useResizeHandler style={CT_STYLE} />
              </div>
              <div className="ct-preview-grid">
                <ImagePanel title="Central axial slice" image={data.middle_slice} large />
                <div className="panel preview-info">
                  <p className="eyebrow">DISPLAY SETTINGS</p>
                  <h2>Intensity range</h2>
                  <div className="info-line"><span>Minimum</span><strong>{data.intensity_range[0]} HU</strong></div>
                  <div className="info-line"><span>Maximum</span><strong>{data.intensity_range[1]} HU</strong></div>
                  <div className="info-line"><span>Series files</span><strong>{data.filename_count}</strong></div>
                  <p className="muted tiny">{data.note}</p>
                </div>
              </div>
            </>
          )}
          {!data && !slicePreview && !busy && (
            <EmptyState icon={Layers3} title="No CT volume loaded" detail="Select a complete multi-slice DICOM series to see the 3D viewer and axial slice preview." />
          )}
          <div className="notice-box"><ShieldCheck size={18} aria-hidden="true" /><span>Research and educational use only. This visualization is not intended for diagnostic interpretation.</span></div>
        </div>
      </div>
    </section>
  );
}
