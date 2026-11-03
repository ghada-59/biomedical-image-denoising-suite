import { useEffect, useState } from "react";
import { Activity, ArrowRight, BarChart3, Box, ChevronRight, FileCheck2, FlaskConical, Layers3, PlugZap, ScanLine, ShieldCheck, Waves } from "lucide-react";
import { api, apiHostLabel } from "./api";
import { CompareStage, MetricCard } from "./components";

// The example images are real outputs of the lab (the bundled chest CT sample, Gaussian noise of variance 0.02, seed 42, median 5 x 5), see docs/overview-images.md.
const IMAGES = { reference: "/img/ct-chest-reference.webp", noisy: "/img/ct-chest-noisy.webp", denoised: "/img/ct-chest-denoised.webp" };

function WorkflowCard({ number, title, detail, icon: Icon, tag, onClick }) {
  return (
    <button type="button" className="workflow-card" onClick={onClick}>
      <div className="workflow-card-top"><span className="workflow-number">{number}</span><span className="workflow-icon"><Icon size={19} aria-hidden="true" /></span></div>
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

const PIPELINE = [
  { n: "1", title: "Import", detail: "Image / DICOM", image: IMAGES.reference, alt: "Chest CT slice used as the example input" },
  { n: "2", title: "Simulate", detail: "Synthetic noise", image: IMAGES.noisy, alt: "The same slice with synthetic Gaussian noise added" },
  { n: "3", title: "Filter", detail: "Spatial / FFT / edge-aware / wavelet", image: IMAGES.denoised, alt: "The noisy slice after a 5 by 5 median filter" },
  { n: "4", title: "Evaluate", detail: "RMSE, PSNR, SSIM", icon: Activity },
  { n: "5", title: "Compare", detail: "Tables / intervals", icon: BarChart3 },
];

export default function Overview({ setPage, benchmark, apiState, apiEpoch = 0 }) {
  const [methodCount, setMethodCount] = useState(null);
  const [v2, setV2] = useState({ status: "loading", runs: [] });
  const [d3, setD3] = useState({ status: "loading", runs: [] });
  const [divider, setDivider] = useState(50);
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
  const verified = recorded.filter(r => r.integrity?.status === "verified");
  const differing = recorded.filter(r => r.integrity?.status === "mismatch");
  const filesVerified = verified.reduce((sum, r) => sum + (Number(r.integrity.files_checked) || 0), 0);
  const apiLabel = apiState === "online" ? "Online" : apiState === "offline" ? "Offline" : "Checking…";

  return (
    <section>
      <div className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Clinical imaging research workstation</p>
          <h1>Biomedical image denoising and benchmarking</h1>
          <p className="hero-lead">Classical (non-learned) denoising of medical images. A lab runs the real filters on an image you provide; recorded benchmarks compare them on one public CT series under synthetic noise. Research and teaching software, not a diagnostic tool.</p>
          <div className="hero-actions">
            <button type="button" className="primary-button" onClick={() => setPage("lab")}>Open the 2D lab <ArrowRight size={16} aria-hidden="true" /></button>
            <button type="button" className="secondary-button" onClick={() => setPage("v2")}><FlaskConical size={16} aria-hidden="true" /> Recorded benchmarks</button>
          </div>
          <ul className="hero-points">
            <li><Waves size={15} aria-hidden="true" /> No neural network, on purpose</li>
            <li><Layers3 size={15} aria-hidden="true" /> One public CT series</li>
            <li><ShieldCheck size={15} aria-hidden="true" /> Research use only</li>
          </ul>
        </div>
        <figure className="hero-figure">
          <CompareStage leftSrc={IMAGES.noisy} rightSrc={IMAGES.denoised} leftLabel="Noisy input" rightLabel="Median 5 × 5" divider={divider} onDivider={setDivider} aspectRatio="1 / 1"
            leftAlt="Chest CT slice with synthetic Gaussian noise, shown on the left of the divider" rightAlt="The same slice after a 5 by 5 median filter, shown on the right of the divider" />
          <input className="compare-range" type="range" min="0" max="100" value={divider} onChange={e => setDivider(Number(e.target.value))} aria-label="Divider position of the example image" />
          <figcaption>Example from the lab, not a result: slice 50 of LIDC-IDRI-0709 (The Cancer Imaging Archive, CC BY 3.0), Gaussian noise of variance 0.02 (seed 42), then a 5 × 5 median filter. One noise draw; it illustrates what the lab does and shows nothing about which filter is better.</figcaption>
        </figure>
      </div>

      <div className="kpi-strip" aria-label="Key figures from the API">
        <MetricCard label="Available methods" value={methodCount ?? "—"} hint="Classical and non-learned" icon={Waves} />
        <MetricCard label="Recorded runs" value={loading ? "…" : recorded.length} icon={FlaskConical}
          hint={loading ? "Looking for recorded runs" : recorded.length ? `${v2.runs.length} in 2D · ${d3.runs.length} in 3D` : "None configured on this server"} />
        <MetricCard label="Result files verified" value={loading ? "…" : verified.length ? filesVerified : "—"} icon={FileCheck2} tone={differing.length ? "bad" : verified.length ? "ok" : undefined}
          hint={differing.length ? `${differing.length} run(s) differ from their record` : verified.length ? "Match their recorded SHA-256" : "Nothing to verify"} />
        <MetricCard label="API" value={apiLabel} icon={PlugZap} tone={apiState === "online" ? "ok" : apiState === "offline" ? "bad" : undefined} hint={apiState === "online" ? `Connected to ${apiHostLabel()}` : "The pages load their data from it"} />
      </div>

      <div className="section-heading-row"><div><p className="eyebrow">Workflows</p><h2>Choose where to start</h2></div></div>
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
            {PIPELINE.map(({ n, title, detail, image, alt, icon: Icon }) => (
              <div className="pipeline-step" key={n}>
                <div className="pipeline-visual">
                  {image ? <img src={image} alt={alt} width="62" height="62" loading="lazy" decoding="async" /> : <Icon size={24} aria-hidden="true" />}
                  <span className="pipeline-number" aria-hidden="true">{n}</span>
                </div>
                <div><strong>{title}</strong><small>{detail}</small></div>
              </div>
            ))}
          </div>
          <p className="pipeline-caption">The first three pictures are the example of the top of this page (one noise draw, median 5 × 5); they illustrate the steps and are not results.</p>
        </div>
        <div className="panel status-panel">
          <div className="panel-heading"><span>Server status</span><ShieldCheck size={17} aria-hidden="true" /></div>
          <div className="status-row"><span>API connection</span><strong className={apiState === "online" ? "status-good" : ""}>{apiLabel}</strong></div>
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
