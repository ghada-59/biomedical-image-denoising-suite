import { useEffect, useState } from "react";
import { BarChart3, Box, ChevronRight, FlaskConical, Layers3, ScanLine, ShieldCheck } from "lucide-react";
import { api } from "./api";
import { PageHeading } from "./components";

function WorkflowCard({ number, title, detail, icon: Icon, tag, onClick }) {
  return (
    <button type="button" className="workflow-card" onClick={onClick}>
      <div className="workflow-card-top"><span className="workflow-number">{number}</span><span className="workflow-icon"><Icon size={18} aria-hidden="true" /></span></div>
      <p className="eyebrow">{tag}</p>
      <h3>{title}</h3>
      <p className="workflow-detail">{detail}</p>
      <span className="workflow-link">Open <ChevronRight size={15} aria-hidden="true" /></span>
    </button>
  );
}

function IntegrityTag({ integrity }) {
  if (integrity.status === "verified") return <span className="tag tag-ok">{integrity.files_checked} files match their SHA-256</span>;
  if (integrity.status === "mismatch") return <span className="tag tag-error">files differ from the record</span>;
  return <span className="tag tag-warn">{integrity.status.replaceAll("_", " ")}</span>;
}

function RecordedRuns({ runs, state }) {
  if (state === "loading") return <p className="footnote" role="status">Looking for recorded runs…</p>;
  if (!runs.length) {
    return <p className="footnote">No recorded run is configured on this server (<code>BENCHMARK_RUN_DIRS</code> for Benchmark V2, <code>BENCHMARK_3D_RUN_DIRS</code> for Benchmark 3D). Nothing is displayed until real results are available.</p>;
  }
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Recorded benchmark runs">
      <table className="run-table">
        <thead><tr><th scope="col">Run</th><th scope="col">Study</th><th scope="col">Noise</th><th scope="col">Test slices</th><th scope="col">Generated</th><th scope="col">Result files</th></tr></thead>
        <tbody>
          {runs.map(run => (
            <tr key={run.kind + run.id}>
              <th scope="row">{run.id}</th><td>{run.study}</td><td>{run.noise}</td><td className="mono">{run.testSlices}</td>
              <td className="mono">{run.generated ? String(run.generated).slice(0, 10) : "—"}</td><td><IntegrityTag integrity={run.integrity} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Overview({ setPage, benchmark, apiState, apiEpoch = 0 }) {
  const [methodCount, setMethodCount] = useState(null);
  const [v2, setV2] = useState({ status: "loading", runs: [] });
  const [d3, setD3] = useState({ status: "loading", runs: [] });
  useEffect(() => {
    let alive = true;
    api("/api/methods").then(b => alive && setMethodCount(b.methods.length)).catch(() => alive && setMethodCount(null));
    api("/api/v2/runs").then(b => alive && setV2({ status: "ready", runs: b.runs })).catch(() => alive && setV2({ status: "error", runs: [] }));
    api("/api/3d/runs").then(b => alive && setD3({ status: "ready", runs: b.runs })).catch(() => alive && setD3({ status: "error", runs: [] }));
    return () => { alive = false; };
  }, [apiState, apiEpoch]);
  const count = benchmark.rows?.length || 0;
  const methodsText = methodCount ? `${methodCount} classical denoisers` : "classical denoisers";
  const loading = v2.status === "loading" || d3.status === "loading";
  const recorded = [
    ...v2.runs.map(r => ({ kind: "v2", id: r.id, study: "Benchmark V2 (2D, tuned and held-out)", noise: `${(r.conditions || []).length} synthetic scenarios`, testSlices: (r.test_slices || []).length, generated: r.generated_at, integrity: r.integrity })),
    ...d3.runs.map(r => ({ kind: "d3", id: r.id, study: "Benchmark 3D (slice-wise versus volumetric)", noise: r.noise_model?.adjacent_slice_correlation ? `white in plane, adjacent-slice correlation ${r.noise_model.adjacent_slice_correlation}` : "white, independent between slices", testSlices: (r.test_slices || []).length, generated: r.generated_at, integrity: r.integrity })),
  ];

  return (
    <section>
      <PageHeading eyebrow="OVERVIEW" title="Biomedical image denoising and benchmarking"
        description="Classical (non-learned) denoising of medical images. A lab runs the real filters on an image you provide; recorded benchmarks compare them on one public CT series under synthetic noise. Research and teaching software, not a diagnostic tool." />

      <div className="workflow-grid">
        <WorkflowCard number="01" title="2D Denoising Lab" icon={ScanLine} tag="Image processing" onClick={() => setPage("lab")}
          detail={`Upload an image or DICOM slice, or use a bundled sample. Add controlled noise and compare up to ${methodsText}, with scores and measured runtimes.`} />
        <WorkflowCard number="02" title="3D CT Explorer" icon={Layers3} tag="Volume inspection" onClick={() => setPage("ct")}
          detail="Load a consistent DICOM series and inspect an interactive volume with a 2D slice preview and its voxel geometry." />
        <WorkflowCard number="03" title="Benchmark V2" icon={FlaskConical} tag="Recorded, 2D" onClick={() => setPage("v2")}
          detail="Nine filters tuned on separate slices and tested on held-out CT slices: errors in Hounsfield units and bootstrap intervals, read from a recorded run." />
        <WorkflowCard number="04" title="Benchmark 3D" icon={Box} tag="Recorded, volumetric" onClick={() => setPage("b3d")}
          detail="Does smoothing across neighbouring slices help? Slice-wise versus volumetric Gaussian smoothing, with the error split into structure change and residual noise." />
      </div>

      <div className="section-heading-row"><div><p className="eyebrow">Evidence</p><h2>Recorded results served by this API</h2></div><span className="muted tiny">Read from files; each file is checked against its recorded SHA-256</span></div>
      <div className="panel"><RecordedRuns runs={recorded} state={loading ? "loading" : "ready"} /></div>

      <div className="bottom-grid">
        <div className="panel pipeline-panel">
          <div className="panel-heading"><span>Processing pipeline</span><span className="mini-badge">5 STEPS</span></div>
          <div className="pipeline">
            {[["01", "Import", "Image / DICOM"], ["02", "Simulate", "Synthetic noise"], ["03", "Filter", "Spatial / FFT / edge-aware / wavelet"], ["04", "Evaluate", "RMSE, PSNR, SSIM"], ["05", "Compare", "Tables / intervals"]].map(([n, t, d], i) => (
              <div className="pipeline-step" key={n}>
                <div className="pipeline-number">{n}</div>
                <div><strong>{t}</strong><small>{d}</small></div>
                {i < 4 && <ChevronRight className="pipeline-arrow" size={15} aria-hidden="true" />}
              </div>
            ))}
          </div>
        </div>
        <div className="panel status-panel">
          <div className="panel-heading"><span>Server status</span><ShieldCheck size={17} aria-hidden="true" /></div>
          <div className="status-row"><span>API connection</span><strong className={apiState === "online" ? "status-good" : ""}>{apiState === "online" ? "Online" : apiState === "offline" ? "Offline" : "Checking…"}</strong></div>
          <div className="status-row"><span>Denoising methods</span><strong>{methodCount ?? "—"}</strong></div>
          <div className="status-row"><span>Benchmark V2 runs</span><strong className={v2.runs.length ? "status-good" : ""}>{v2.status === "loading" ? "Checking…" : v2.runs.length ? `${v2.runs.length} configured` : "None configured"}</strong></div>
          <div className="status-row"><span>Benchmark 3D runs</span><strong className={d3.runs.length ? "status-good" : ""}>{d3.status === "loading" ? "Checking…" : d3.runs.length ? `${d3.runs.length} configured` : "None configured"}</strong></div>
          <div className="status-row"><span>Older 2D snapshot</span><strong className={benchmark.available ? "status-good" : ""}>{benchmark.available ? `${count} rows` : "Not found"}</strong></div>
        </div>
      </div>

      <div className="panel scope-panel">
        <div className="panel-heading"><span>Scope and limits</span><BarChart3 size={17} aria-hidden="true" /></div>
        <ul className="scope-list">
          <li><strong>What it is.</strong> A teaching and benchmarking tool for classical (non-learned) denoising of medical images, with CT/DICOM handling. No neural network is used, on purpose.</li>
          <li><strong>Where the noise comes from.</strong> Noise is added synthetically. A real clinical slice is never noise-free, so every score compares an output with a reference that is itself noisy. Synthetic noise is not a model of a particular scanner.</li>
          <li><strong>What the scores mean.</strong> RMSE, PSNR and SSIM measure similarity to that reference. They do not show preserved anatomy, lesion detectability or any clinical benefit.</li>
          <li><strong>What the evidence covers.</strong> The recorded benchmarks use one public CT series from one patient; slices of one scan are not independent samples. They are exploratory, not an independent validation, and they do not show that any method is best in general.</li>
          <li><strong>What it is not.</strong> A diagnostic device. It has no clinical validation and must not be used to make clinical decisions.</li>
        </ul>
      </div>
    </section>
  );
}
