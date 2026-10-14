import { useEffect, useMemo, useRef, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";
const Plot = createPlotlyComponent(Plotly);
import { Activity, ArrowDownToLine, BarChart3, Check, ChevronRight, CircleHelp, FileImage, FileText, FlaskConical, Layers3, LayoutDashboard, Menu, Moon, ScanLine, Settings2, ShieldCheck, Sun, UploadCloud, Waves, X } from "lucide-react";

const NAV = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "lab", label: "2D Denoising Lab", icon: ScanLine },
  { id: "ct", label: "3D CT Explorer", icon: Layers3 },
  { id: "results", label: "Results & Reports", icon: BarChart3 },
  { id: "guide", label: "Methods & Guide", icon: CircleHelp },
];
const NOISE = ["Gaussian", "Salt & Pepper", "Speckle (synthetic)", "None"];
const COLORS = ["#7188ff", "#22a699", "#e3a64f", "#b18aff", "#5ca8e8", "#e27d9b", "#8d9aa8"];

async function api(path, options) {
  const response = await fetch(path, options || {});
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "The request could not be completed.");
  return payload;
}
function PageHeading({ eyebrow, title, description, action }) {
  return <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="page-description">{description}</p></div>{action && <div>{action}</div>}</div>;
}
function EmptyState({ icon: Icon = FileImage, title, detail }) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={25}/></div><h3>{title}</h3><p>{detail}</p></div>;
}
function ImagePanel({ title, image, badge, large }) {
  return <article className={"image-panel" + (large ? " image-panel-large" : "")}><div className="panel-heading"><span>{title}</span>{badge && <span className="mini-badge">{badge}</span>}</div>{image ? <img className="result-image" src={image} alt={title}/> : <div className="image-placeholder"><FileImage size={24}/><span>Run an experiment to display this image</span></div>}</article>;
}
function MetricCard({ label, value, hint, icon: Icon }) {
  return <article className="metric-card"><div className="metric-top"><span>{label}</span><span className="metric-icon"><Icon size={17}/></span></div><strong>{value}</strong><small>{hint}</small></article>;
}
function DataTable({ rows }) {
  if (!rows || !rows.length) return <EmptyState title="No measurements yet" detail="Run an experiment or load a benchmark to populate this table."/>;
  const keys = Object.keys(rows[0]);
  return <div className="table-wrap"><table><thead><tr>{keys.map(k => <th key={k}>{k.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{keys.map(k => <td key={k}>{row[k] === null || row[k] === undefined ? "—" : String(row[k])}</td>)}</tr>)}</tbody></table></div>;
}
function RangeField({ label, value, min, max, step, display, onChange }) {
  return <div className="field range-field"><div className="range-label"><label className="field-label">{label}</label><strong>{display}</strong></div><input type="range" value={value} min={min} max={max} step={step} onChange={e => onChange(Number(e.target.value))}/></div>;
}
function WorkflowCard({ number, title, detail, icon: Icon, tag, onClick }) {
  return <button className="workflow-card" onClick={onClick}><div className="workflow-card-top"><span className="workflow-number">{number}</span><span className="workflow-icon"><Icon size={19}/></span></div><p className="eyebrow">{tag}</p><h3>{title}</h3><p className="workflow-detail">{detail}</p><span className="workflow-link">Open workflow <ChevronRight size={15}/></span></button>;
}
function MetricBars({ title, rows, field }) {
  const values = rows.filter(row => Number.isFinite(Number(row[field]))).sort((a,b) => Number(b[field])-Number(a[field]));
  const max = Math.max(...values.map(row => Number(row[field])), 0.001);
  return <div className="bar-chart"><h3>{title}</h3>{values.map((row,i) => <div className="bar-row" key={String(row.Filter)+String(row.Domain)}><div className="bar-label">{row.Filter}</div><div className="bar-track"><div className="bar-fill" style={{width: Math.max(2, Number(row[field])/max*100)+"%", background: COLORS[i%COLORS.length]}}/></div><strong>{Number(row[field]).toFixed(field === "Mean_SSIM" ? 4 : 2)}</strong></div>)}</div>;
}

export default function App() {
  const [page, setPage] = useState("overview");
  const [theme, setTheme] = useState(() => localStorage.getItem("biomed-theme") || "dark");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [health, setHealth] = useState("checking");
  const [benchmark, setBenchmark] = useState({available:false, rows:[], noise_types:[]});
  const [benchNoise, setBenchNoise] = useState("Gaussian");
  const [imageFile, setImageFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const previewObjectUrl = useRef(null);
  const [denoise, setDenoise] = useState(null);
  const [noiseType, setNoiseType] = useState("Gaussian");
  const [amount, setAmount] = useState(0.02);
  const [variance, setVariance] = useState(0.02);
  const [kernel, setKernel] = useState(5);
  const [sigma, setSigma] = useState(0);
  const [cutoff, setCutoff] = useState(0.1);
  const [seed, setSeed] = useState(42);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ctFiles, setCtFiles] = useState([]);
  const [ctData, setCtData] = useState(null);
  const [ctPreview, setCtPreview] = useState(null);
  const [ctBusy, setCtBusy] = useState(false);
  const [ctError, setCtError] = useState("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("biomed-theme", theme);
  }, [theme]);
  useEffect(() => {
    api("/api/health").then(() => setHealth("online")).catch(() => setHealth("offline"));
    api("/api/results").then(setBenchmark).catch(() => setBenchmark({available:false, rows:[], noise_types:[]}));
  }, []);
  const benchRows = useMemo(() => (benchmark.rows || []).filter(row => String(row.Noise) === benchNoise), [benchmark.rows, benchNoise]);
  const best = useMemo(() => benchRows.reduce((a,b) => !a || Number(b.Mean_SSIM)>Number(a.Mean_SSIM) ? b : a, null), [benchRows]);

  useEffect(() => () => {
    if (previewObjectUrl.current) URL.revokeObjectURL(previewObjectUrl.current);
  }, []);

  async function selectImage(file) {
    setImageFile(file || null); setPreview(null); setDenoise(null); setError("");
    if (previewObjectUrl.current) {
      URL.revokeObjectURL(previewObjectUrl.current);
      previewObjectUrl.current = null;
    }
    if (!file) return;

    const isDicom = file.name.toLowerCase().endsWith(".dcm");
    const isBrowserImage = file.type.startsWith("image/") && !isDicom;
    if (isBrowserImage) {
      const localUrl = URL.createObjectURL(file);
      previewObjectUrl.current = localUrl;
      setPreview({
        filename: file.name,
        preview: localUrl,
        format: "Selected image",
        width: null,
        height: null,
        local: true,
      });
    }

    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await api("/api/image/preview", { method: "POST", body });
      setPreview(response);
      if (previewObjectUrl.current) {
        URL.revokeObjectURL(previewObjectUrl.current);
        previewObjectUrl.current = null;
      }
    } catch (e) {
      // Keep the browser preview visible for PNG/JPEG files even if the API is offline.
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function runDenoising() {
    if (!imageFile) { setError("Choose an image or DICOM slice first."); return; }
    setBusy(true); setError("");
    try {
      const body = new FormData(); body.append("file", imageFile); body.append("noise_type", noiseType);
      body.append("noise_amount", String(amount)); body.append("noise_variance", String(variance));
      body.append("seed", String(seed)); body.append("kernel_size", String(kernel));
      body.append("sigma", String(sigma)); body.append("cutoff_ratio", String(cutoff));
      setDenoise(await api("/api/denoise", {method:"POST", body}));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function selectCtFiles(list) {
    const files = Array.from(list || []); setCtFiles(files); setCtData(null); setCtPreview(null); setCtError("");
    if (!files.length) return;
    if (files.length === 1) {
      setCtBusy(true);
      try { const body = new FormData(); body.append("file", files[0]); setCtPreview(await api("/api/image/preview", {method:"POST", body})); setCtError("One DICOM slice selected. The 2D preview is shown below; select the complete set of slices from the same CT series to reconstruct a 3D volume."); }
      catch (e) { setCtError(e.message); } finally { setCtBusy(false); }
      return;
    }
    setCtBusy(true);
    try { const body = new FormData(); files.forEach(file => body.append("files", file)); setCtData(await api("/api/ct/volume", {method:"POST", body})); }
    catch (e) { setCtError(e.message); } finally { setCtBusy(false); }
  }
  const currentNav = NAV.find(n => n.id === page);
  const count = benchmark.rows?.length || 0;

  return <div className="app-shell">
    {sidebarOpen && <button className="sidebar-scrim" onClick={() => setSidebarOpen(false)} aria-label="Close navigation"/>}
    <aside className={"sidebar" + (sidebarOpen ? " sidebar-open" : "")}>
      <div className="brand"><div className="brand-mark"><Activity size={23}/></div><div className="brand-copy"><strong>MED<span>LAB</span></strong><small>IMAGING WORKSPACE</small></div><button className="icon-button mobile-close" onClick={() => setSidebarOpen(false)} aria-label="Close"><X size={18}/></button></div>
      <div className="workspace-tag"><span className="status-dot"/> RESEARCH WORKSPACE</div><p className="nav-label">WORKSPACE</p>
      <nav className="main-nav">{NAV.map(({id,label,icon:Icon}) => <button key={id} className={"nav-item"+(page===id?" active":"")} onClick={() => {setPage(id);setSidebarOpen(false);}}><Icon size={18}/><span>{label}</span>{page===id && <ChevronRight className="nav-chevron" size={15}/>}</button>)}</nav>
      <div className="sidebar-spacer"/>
      <div className="sidebar-status"><div className="status-head"><span className={"status-dot "+(health==="online"?"online":health==="offline"?"offline":"")}/> API {health.toUpperCase()}</div><p>Image analysis · CT volume rendering</p><div className="privacy-note"><ShieldCheck size={16}/><span>Research and education only. Not for diagnosis.</span></div></div>
      <div className="sidebar-footer"><span>BIOMEDICAL IMAGE DENOISING SUITE</span><span>v1.0</span></div>
    </aside>

    <main className="main-area">
      <header className="topbar"><div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><Menu size={20}/></button><span className="breadcrumb">Workspace</span><ChevronRight size={14}/><strong>{currentNav?.label}</strong></div><div className="topbar-right"><span className="live-pill"><span className="status-dot online"/> LOCAL SESSION</span><button className="theme-toggle" onClick={() => setTheme(theme==="dark"?"light":"dark")}>{theme==="dark"?<><Sun size={17}/>Light mode</>:<><Moon size={17}/>Dark mode</>}</button></div></header>
      <div className="page-content">
        {page==="overview" && <section>
          <div className="hero"><div className="hero-copy"><p className="eyebrow hero-eyebrow"><span className="status-dot online"/> BIOMEDICAL IMAGE ANALYSIS</p><h1>See the image.<br/><span>Measure the difference.</span></h1><p>A focused workspace for classical denoising experiments, quantitative comparison and interactive CT volume exploration.</p><div className="hero-actions"><button className="primary-button" onClick={() => setPage("lab")}><ScanLine size={17}/>Open Denoising Lab<ChevronRight size={16}/></button><button className="hero-link" onClick={() => setPage("ct")}>Explore CT volume<ChevronRight size={16}/></button></div></div><div className="hero-visual"><div className="scan-orbit orbit-one"/><div className="scan-orbit orbit-two"/><div className="scan-crosshair horizontal"/><div className="scan-crosshair vertical"/><div className="scan-center"><Activity size={46}/></div><div className="scan-chip chip-top"><span className="scan-chip-dot"/> IMAGE ANALYSIS</div><div className="scan-chip chip-bottom"><span>CT / 3D</span><strong>VOLUME VIEW</strong></div></div><div className="hero-bottom"><span><b>01</b> Classical filtering</span><span><b>02</b> PSNR / SSIM</span><span><b>03</b> DICOM volume</span></div></div>
          <div className="section-heading-row overview-section-title"><div><p className="eyebrow">WORKSPACE AT A GLANCE</p><h2>Analysis workspace</h2></div><span className="muted tiny">Choose a workflow to begin</span></div>
          <div className="workflow-grid"><WorkflowCard number="01" title="2D Denoising Lab" detail="Upload an image or DICOM slice, add controlled noise and compare six classical filters." icon={ScanLine} tag="IMAGE PROCESSING" onClick={() => setPage("lab")}/><WorkflowCard number="02" title="3D CT Explorer" detail="Load a consistent DICOM series and inspect an interactive volume with a 2D slice preview." icon={Layers3} tag="VOLUME RENDERING" onClick={() => setPage("ct")}/><WorkflowCard number="03" title="Results & Reports" detail={"Review the benchmark snapshot, compare filter metrics and export results. "+count+" benchmark rows loaded."} icon={BarChart3} tag="QUANTITATIVE EVALUATION" onClick={() => setPage("results")}/></div>
          <div className="bottom-grid"><div className="panel pipeline-panel"><div className="panel-heading"><span>Processing pipeline</span><span className="mini-badge">5 STEPS</span></div><div className="pipeline">{[["01","Import","Image / DICOM"],["02","Simulate","Noise model"],["03","Filter","Spatial / FFT"],["04","Evaluate","PSNR / SSIM"],["05","Compare","Tables / plots"]].map(([n,t,d],i)=><div className="pipeline-step" key={n}><div className="pipeline-number">{n}</div><div><strong>{t}</strong><small>{d}</small></div>{i<4&&<ChevronRight className="pipeline-arrow" size={15}/>}</div>)}</div></div><div className="panel status-panel"><div className="panel-heading"><span>Project status</span><ShieldCheck size={17}/></div><div className="status-row"><span>Benchmark snapshot</span><strong className={benchmark.available?"status-good":""}>{benchmark.available?"Loaded":"Not found"}</strong></div><div className="status-row"><span>Processing methods</span><strong>6 filters</strong></div><div className="status-row"><span>Evaluation metrics</span><strong>PSNR · SSIM</strong></div><p className="status-note">Metrics need a known reference. Clinical CT is not a noise-free ground truth.</p></div></div>
        </section>}

        {page==="lab" && <section><PageHeading eyebrow="IMAGE PROCESSING / 01" title="2D Denoising Lab" description="Load a grayscale image or DICOM slice, simulate noise and compare filters using PSNR and SSIM." action={<span className="pill"><FlaskConical size={14}/> Interactive experiment</span>}/><div className="lab-layout">
          <aside className="settings-panel"><div className="section-title"><Settings2 size={17}/><h2>Experiment settings</h2></div><label className="field-label">Input image</label><label className="upload-box compact-upload"><UploadCloud size={22}/><strong>{imageFile?imageFile.name:"Choose image or DICOM"}</strong><small>PNG, JPG, DICOM (.dcm)</small><input type="file" accept=".png,.jpg,.jpeg,.dcm" onChange={e=>selectImage(e.target.files?.[0])}/></label>
            <div className="field"><label className="field-label" htmlFor="noise">Noise model</label><select id="noise" value={noiseType} onChange={e=>setNoiseType(e.target.value)}>{NOISE.map(n=><option key={n}>{n}</option>)}</select></div>
            {noiseType==="Salt & Pepper"?<RangeField label="Affected pixels" value={amount} min={0.001} max={0.2} step={0.005} display={amount.toFixed(3)} onChange={setAmount}/>:noiseType!=="None"&&<RangeField label="Noise variance" value={variance} min={0.001} max={0.2} step={0.005} display={variance.toFixed(3)} onChange={setVariance}/>}
            <div className="field"><label className="field-label" htmlFor="kernel">Spatial kernel</label><select id="kernel" value={kernel} onChange={e=>setKernel(Number(e.target.value))}>{[3,5,7,9,11,13,15].map(n=><option key={n} value={n}>{n} × {n}</option>)}</select></div>
            <RangeField label="Gaussian sigma" value={sigma} min={0} max={5} step={0.1} display={sigma===0?"Auto":sigma.toFixed(1)} onChange={setSigma}/><RangeField label="FFT cutoff" value={cutoff} min={0.01} max={0.5} step={0.01} display={cutoff.toFixed(2)} onChange={setCutoff}/>
            <div className="field"><label className="field-label" htmlFor="seed">Random seed</label><input id="seed" type="number" min="0" value={seed} onChange={e=>setSeed(Number(e.target.value))}/></div><button className="primary-button full-width" disabled={!imageFile||busy} onClick={runDenoising}>{busy?<span className="spinner"/>:<Activity size={17}/>} {busy?"Processing image…":"Run denoising"}</button>{error&&<div className="error-box"><X size={16}/><span>{error}</span></div>}</aside>
          <div className="lab-results"><div className="section-heading-row"><div><p className="eyebrow">VISUAL COMPARISON</p><h2>Image outputs</h2></div>{preview&&<span className="file-tag"><Check size={13}/>{preview.width} × {preview.height} px</span>}</div>
            {!preview&&!busy?<EmptyState title="Start with an image" detail="Choose a PNG, JPEG or DICOM file. The preview appears here before processing."/>:<div className="image-grid"><ImagePanel title="Input image" image={preview?.preview} badge={preview?.format}/><ImagePanel title="Noisy input" image={denoise?.images?.["Noisy input"]} badge={denoise?.noise_type}/><ImagePanel title="Median filter" image={denoise?.images?.Median}/><ImagePanel title="Gaussian filter" image={denoise?.images?.Gaussian}/><ImagePanel title="Frequency · Gaussian" image={denoise?.images?.["Frequency Gaussian"]}/><ImagePanel title="Frequency · Butterworth" image={denoise?.images?.["Frequency Butterworth"]}/></div>}
            <div className="panel results-table-panel"><div className="panel-heading"><span>Quantitative measurements</span>{denoise&&<span className="mini-badge">LIVE RUN</span>}</div>{denoise?<><p className="muted tiny">{denoise.note}</p><DataTable rows={denoise.results}/></>:<EmptyState icon={BarChart3} title="Results will appear here" detail="Run denoising to calculate PSNR and SSIM for each filter."/>}</div>
          </div></div></section>}

        {page==="ct" && <section><PageHeading eyebrow="VOLUME VISUALIZATION / 02" title="3D CT Explorer" description="Load one complete DICOM series to reconstruct a volume, inspect its central slice and explore the interactive 3D rendering." action={<span className="pill"><Layers3 size={14}/> DICOM series</span>}/>
          <div className="ct-upload-card"><div className="upload-symbol"><UploadCloud size={24}/></div><div className="upload-copy"><h2>Import CT series</h2><p>Select multiple .dcm slices from the same study and series. Files are processed locally by the Python API.</p><div className="file-status">{ctFiles.length?<><Check size={14}/>{ctFiles.length} file(s) selected</>:"No files selected"}</div></div><label className="secondary-button">{ctFiles.length?"Change files":"Select DICOM files"}<input type="file" multiple accept=".dcm" onChange={e=>selectCtFiles(e.target.files)}/></label></div>
          {ctBusy&&<div className="loading-card"><span className="spinner"/> Reading DICOM metadata and building volume…</div>}
          {ctError&&<div className={ctPreview?"notice-box":"error-box wide-error"}><CircleHelp size={18}/><span>{ctError}</span></div>}
          {ctPreview&&<div className="ct-preview-grid"><ImagePanel title="Selected DICOM slice · 2D preview" image={ctPreview.preview} badge={ctPreview.width+" × "+ctPreview.height} large/><div className="panel preview-info"><p className="eyebrow">SLICE METADATA</p><h2>{ctPreview.filename}</h2><p>This file is readable as a 2D image. For a real 3D reconstruction, select the full stack of slices belonging to one series.</p><div className="info-line"><span>Input type</span><strong>{ctPreview.format}</strong></div><div className="info-line"><span>Dimensions</span><strong>{ctPreview.width} × {ctPreview.height}</strong></div></div></div>}
          {ctData&&<><div className="ct-metrics"><MetricCard label="DICOM slices" value={ctData.slices} hint="Instances in loaded series" icon={FileImage}/><MetricCard label="Volume dimensions" value={ctData.dimensions_xyz.join(" × ")} hint="X × Y × Z voxels" icon={Layers3}/><MetricCard label="Voxel spacing" value={ctData.spacing_xyz_mm.join(" × ")+" mm"} hint="X × Y × Z" icon={Activity}/></div><div className="ct-viewer-panel"><div className="panel-heading"><span>Interactive CT volume</span><span className="mini-badge">3D · PLOTLY</span></div><Plot data={ctData.figure.data} layout={{...ctData.figure.layout,autosize:true,paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",font:{color:"var(--text)"}}} config={{responsive:true,displaylogo:false,scrollZoom:true}} useResizeHandler style={{width:"100%",height:"610px"}}/></div><div className="ct-preview-grid"><ImagePanel title="Central axial slice" image={ctData.middle_slice} large/><div className="panel preview-info"><p className="eyebrow">DISPLAY SETTINGS</p><h2>Intensity range</h2><div className="info-line"><span>Minimum</span><strong>{ctData.intensity_range[0]} HU</strong></div><div className="info-line"><span>Maximum</span><strong>{ctData.intensity_range[1]} HU</strong></div><div className="info-line"><span>Series files</span><strong>{ctData.filename_count}</strong></div><p className="muted tiny">{ctData.note}</p></div></div></>}
          {!ctData&&!ctPreview&&!ctBusy&&<EmptyState icon={Layers3} title="No CT volume loaded" detail="Select a complete multi-slice DICOM series to see the 3D viewer and axial slice preview."/>}
          <div className="notice-box"><ShieldCheck size={18}/><span>Research and educational use only. This visualization is not intended for diagnostic interpretation. Do not upload or share identifiable patient data without authorization.</span></div>
        </section>}

        {page==="results"&&<section><PageHeading eyebrow="EXPERIMENT SUMMARY / 03" title="Results & Reports" description="Explore the benchmark snapshot or locally generated measurements. Filter by noise model and compare PSNR and SSIM." action={<span className="pill"><BarChart3 size={14}/>{benchmark.available?"Benchmark loaded":"No benchmark"}</span>}/>
          {benchmark.available?<><div className="benchmark-toolbar"><div><label className="field-label" htmlFor="bench-noise">Noise model</label><select id="bench-noise" value={benchNoise} onChange={e=>setBenchNoise(e.target.value)}>{(benchmark.noise_types?.length?benchmark.noise_types:NOISE).map(n=><option key={n}>{n}</option>)}</select></div><div className="source-label"><FileText size={15}/> Source: {benchmark.source}</div></div>
            <div className="metrics-grid"><MetricCard label="Highest mean SSIM" value={best?.Filter||"—"} hint="Within selected noise model" icon={Activity}/><MetricCard label="Mean SSIM" value={best?Number(best.Mean_SSIM).toFixed(4):"—"} hint="Structural similarity" icon={ScanLine}/><MetricCard label="Mean PSNR" value={best?Number(best.Mean_PSNR_dB).toFixed(2)+" dB":"—"} hint="Peak signal-to-noise ratio" icon={Waves}/><MetricCard label="Runs evaluated" value={best?.Runs_Evaluated??"—"} hint="Repeated synthetic-noise runs" icon={BarChart3}/></div>
            <div className="panel chart-panel"><div className="panel-heading"><span>Filter comparison</span><span className="mini-badge">MEAN METRICS</span></div><div className="chart-grid"><MetricBars title="Mean SSIM" rows={benchRows} field="Mean_SSIM"/><MetricBars title="Mean PSNR (dB)" rows={benchRows} field="Mean_PSNR_dB"/></div></div>
            <div className="panel results-table-panel"><div className="panel-heading"><span>Benchmark data</span><span className="mini-badge">{benchRows.length} rows</span></div><DataTable rows={benchRows}/><button className="secondary-button download-button" onClick={()=>{const blob=new Blob([JSON.stringify(benchRows,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="denoising-benchmark.json";a.click();URL.revokeObjectURL(url);}}><ArrowDownToLine size={16}/> Export filtered data (JSON)</button></div>
            <p className="footnote">Benchmark values are from controlled experiments with synthetic noise on CT slices. Repeated noise realizations are not independent patients and do not establish clinical performance.</p>
          </>:<EmptyState icon={BarChart3} title="Benchmark results are not available" detail="Start the Python API and check docs/results/denoising_summary.csv or reports/denoising_summary.csv."/>}
        </section>}

        {page==="guide"&&<Guide/>}
      </div>
      <footer className="main-footer"><span>MEDLAB · BIOMEDICAL IMAGE DENOISING SUITE</span><span>RESEARCH SOFTWARE <b>/</b> NOT FOR DIAGNOSIS</span></footer>
    </main>
  </div>;
}

function Guide() {
  const items=[
    [ScanLine,"SPATIAL DOMAIN","Mean, median & Gaussian","Spatial filters operate on local neighborhoods. Mean filtering smooths broadly, median filtering is useful for impulse noise, and Gaussian filtering applies weighted smoothing."],
    [Waves,"FREQUENCY DOMAIN","Ideal, Gaussian & Butterworth","Frequency filters attenuate high spatial frequencies through a 2D Fourier transform. A sharp ideal cutoff may introduce ringing; smoother roll-offs reduce abrupt transitions."],
    [Activity,"METRICS","PSNR & SSIM","PSNR summarizes pixel-level error relative to a reference. SSIM compares luminance, contrast and local structure. Interpret both alongside the images and experimental setup."],
    [Layers3,"DICOM / 3D","One series, multiple slices","A single DICOM file can be previewed in 2D. A meaningful 3D voxel grid requires multiple slices from one series with consistent orientation, pixel spacing and geometry."]
  ];
  return <section><PageHeading eyebrow="DOCUMENTATION / 04" title="Methods & Guide" description="What this workspace implements, how to read the measurements and the limitations to keep in mind."/><div className="guide-grid">{items.map(([Icon,tag,title,detail])=><article className="panel guide-card" key={title}><div className="guide-icon"><Icon size={20}/></div><p className="eyebrow">{tag}</p><h2>{title}</h2><p>{detail}</p></article>)}</div><div className="notice-box"><ShieldCheck size={18}/><span>This project is for research and education, not diagnosis. Synthetic-noise results do not demonstrate clinical benefit or generalization across patients and scanners.</span></div></section>;
}
