import { useState } from "react";
import { Activity, Check, CircleHelp, FileImage, Layers3, ShieldCheck, UploadCloud } from "lucide-react";
import { Plot } from "./plot";
import { api, apiHostLabel, apiIsLocal } from "./api";
import { EmptyState, ImagePanel, MetricCard, PageHeading } from "./components";

export default function CtExplorer({ apiState = "online" }) {
  const [files, setFiles] = useState([]);
  const [data, setData] = useState(null);
  const [slicePreview, setSlicePreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
            <Plot data={data.figure.data}
              layout={{ ...data.figure.layout, autosize: true, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { color: "var(--text)" } }}
              config={{ responsive: true, displaylogo: false, scrollZoom: true }} useResizeHandler style={{ width: "100%", height: "610px" }} />
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
    </section>
  );
}
