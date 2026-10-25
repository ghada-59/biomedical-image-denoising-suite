import { useEffect, useState } from "react";
import { Activity, BarChart3, ChevronRight, FlaskConical, Layers3, ScanLine, ShieldCheck } from "lucide-react";
import { api } from "./api";

function WorkflowCard({ number, title, detail, icon: Icon, tag, onClick }) {
  return (
    <button type="button" className="workflow-card" onClick={onClick}>
      <div className="workflow-card-top"><span className="workflow-number">{number}</span><span className="workflow-icon"><Icon size={19} aria-hidden="true" /></span></div>
      <p className="eyebrow">{tag}</p>
      <h3>{title}</h3>
      <p className="workflow-detail">{detail}</p>
      <span className="workflow-link">Open workflow <ChevronRight size={15} aria-hidden="true" /></span>
    </button>
  );
}

export default function Overview({ setPage, benchmark, apiState, apiEpoch = 0 }) {
  const [methodCount, setMethodCount] = useState(null);
  const [v2, setV2] = useState({ status: "loading", runs: 0 });
  useEffect(() => {
    let alive = true;
    api("/api/methods").then(b => alive && setMethodCount(b.methods.length)).catch(() => alive && setMethodCount(null));
    api("/api/v2/runs").then(b => alive && setV2({ status: "ready", runs: b.runs.length })).catch(() => alive && setV2({ status: "error", runs: 0 }));
    return () => { alive = false; };
  }, [apiState, apiEpoch]);
  const count = benchmark.rows?.length || 0;
  const methodsText = methodCount ? `${methodCount} classical denoisers` : "classical denoisers";

  return (
    <section>
      <div className="hero">
        <div className="hero-copy">
          <p className="eyebrow hero-eyebrow"><span className="status-dot online" /> BIOMEDICAL IMAGE ANALYSIS</p>
          <h1>See the image.<br /><span>Measure the difference.</span></h1>
          <p>A focused workspace for classical denoising experiments, quantitative comparison and interactive CT volume exploration.</p>
          <div className="hero-actions">
            <button type="button" className="primary-button" onClick={() => setPage("lab")}><ScanLine size={17} aria-hidden="true" />Open Denoising Lab<ChevronRight size={16} aria-hidden="true" /></button>
            <button type="button" className="hero-link" onClick={() => setPage("v2")}>See the benchmark<ChevronRight size={16} aria-hidden="true" /></button>
          </div>
        </div>
        <div className="hero-visual" aria-hidden="true">
          <div className="scan-orbit orbit-one" /><div className="scan-orbit orbit-two" />
          <div className="scan-crosshair horizontal" /><div className="scan-crosshair vertical" />
          <div className="scan-center"><Activity size={46} /></div>
          <div className="scan-chip chip-top"><span className="scan-chip-dot" /> IMAGE ANALYSIS</div>
          <div className="scan-chip chip-bottom"><span>CT / 3D</span><strong>VOLUME VIEW</strong></div>
        </div>
        <div className="hero-bottom"><span><b>01</b> Classical filtering</span><span><b>02</b> PSNR / SSIM / RMSE</span><span><b>03</b> DICOM volume</span></div>
      </div>

      <div className="section-heading-row overview-section-title">
        <div><p className="eyebrow">WORKSPACE AT A GLANCE</p><h2>Analysis workspace</h2></div>
        <span className="muted tiny">Choose a workflow to begin</span>
      </div>
      <div className="workflow-grid">
        <WorkflowCard number="01" title="2D Denoising Lab" icon={ScanLine} tag="IMAGE PROCESSING" onClick={() => setPage("lab")}
          detail={`Upload an image or DICOM slice, or use a bundled sample. Add controlled noise and compare up to ${methodsText} with measured runtimes.`} />
        <WorkflowCard number="02" title="Benchmark V2" icon={FlaskConical} tag="TUNED COMPARISON" onClick={() => setPage("v2")}
          detail="Held-out CT slices, parameters tuned on separate slices, errors in Hounsfield units and bootstrap intervals, read from recorded runs." />
        <WorkflowCard number="03" title="3D CT Explorer" icon={Layers3} tag="VOLUME RENDERING" onClick={() => setPage("ct")}
          detail="Load a consistent DICOM series and inspect an interactive volume with a 2D slice preview." />
      </div>

      <div className="bottom-grid">
        <div className="panel pipeline-panel">
          <div className="panel-heading"><span>Processing pipeline</span><span className="mini-badge">5 STEPS</span></div>
          <div className="pipeline">
            {[["01", "Import", "Image / DICOM"], ["02", "Simulate", "Noise model"], ["03", "Filter", "Spatial / FFT / adaptive"], ["04", "Evaluate", "PSNR / SSIM / RMSE"], ["05", "Compare", "Tables / plots"]].map(([n, t, d], i) => (
              <div className="pipeline-step" key={n}>
                <div className="pipeline-number">{n}</div>
                <div><strong>{t}</strong><small>{d}</small></div>
                {i < 4 && <ChevronRight className="pipeline-arrow" size={15} aria-hidden="true" />}
              </div>
            ))}
          </div>
        </div>
        <div className="panel status-panel">
          <div className="panel-heading"><span>Project status</span><ShieldCheck size={17} aria-hidden="true" /></div>
          <div className="status-row"><span>API connection</span><strong className={apiState === "online" ? "status-good" : ""}>{apiState === "online" ? "Online" : apiState === "offline" ? "Offline" : "Checking…"}</strong></div>
          <div className="status-row"><span>Denoising methods</span><strong>{methodCount ?? "—"}</strong></div>
          <div className="status-row"><span>Benchmark V2 runs</span><strong className={v2.runs ? "status-good" : ""}>{v2.status === "loading" ? "Checking…" : v2.runs ? `${v2.runs} configured` : "None configured"}</strong></div>
          <div className="status-row"><span>Older 2D snapshot</span><strong className={benchmark.available ? "status-good" : ""}>{benchmark.available ? `${count} rows` : "Not found"}</strong></div>
        </div>
      </div>

      <div className="panel scope-panel">
        <div className="panel-heading"><span>Scope and limits</span><BarChart3 size={17} aria-hidden="true" /></div>
        <ul className="scope-list">
          <li><strong>What it is.</strong> A teaching and benchmarking tool for classical (non-learned) denoising of medical images, with CT/DICOM handling.</li>
          <li><strong>Where the noise comes from.</strong> Noise is added synthetically. A real clinical slice is never noise-free, so every score compares an output with a reference that is itself noisy.</li>
          <li><strong>What the scores mean.</strong> PSNR, SSIM and RMSE measure similarity to that reference. They do not show preserved anatomy, lesion detectability or any clinical benefit.</li>
          <li><strong>What the evidence covers.</strong> The recorded benchmark uses one public CT series from one patient. It is exploratory and not an independent validation.</li>
          <li><strong>What it is not.</strong> A diagnostic device. It has no clinical validation and must not be used to make clinical decisions.</li>
        </ul>
      </div>
    </section>
  );
}
