import { useEffect, useState } from "react";
import { Activity, Layers3, ScanLine, ShieldCheck, Waves } from "lucide-react";
import { api } from "./api";
import { PageHeading } from "./components";

const METRIC_NOTES = [
  [Activity, "METRICS", "PSNR, SSIM and RMSE",
    "PSNR summarizes pixel error relative to a reference on a [0, 1] display scale. SSIM compares local luminance, contrast and structure (Wang et al., 2004, 11×11 Gaussian window in the benchmark). RMSE in Hounsfield units is reported by Benchmark V2. All three measure similarity to a reference that is itself a noisy image; none shows that anatomy or small lesions are preserved."],
  [Layers3, "DICOM / 3D", "One series, multiple slices",
    "A single DICOM file can be previewed in 2D. A meaningful 3D voxel grid requires multiple slices from one series with consistent orientation, pixel spacing and geometry."],
];

export default function Guide({ apiEpoch = 0 }) {
  const [state, setState] = useState({ status: "loading", methods: [], error: "" });
  useEffect(() => {
    let alive = true;
    api("/api/methods")
      .then(body => alive && setState({ status: "ready", methods: body.methods, error: "" }))
      .catch(e => alive && setState({ status: "error", methods: [], error: e.message }));
    return () => { alive = false; };
  }, [apiEpoch]);

  return (
    <section>
      <PageHeading eyebrow="DOCUMENTATION / 04" title="Methods & Guide"
        description="What this workspace implements, how to read the measurements and the limitations to keep in mind." />
      <h2 className="lab-subheading">Denoising methods</h2>
      {state.status === "loading" && <p className="muted" role="status">Loading the method list from the API…</p>}
      {state.status === "error" && <p className="error-box" role="alert">The method descriptions come from the API and could not be loaded. {state.error}</p>}
      <div className="guide-grid">
        {state.methods.map(m => (
          <article className="panel guide-card" key={m.id}>
            <div className="guide-icon">{m.family === "Frequency" ? <Waves size={20} aria-hidden="true" /> : <ScanLine size={20} aria-hidden="true" />}</div>
            <p className="eyebrow">{m.family.toUpperCase()}</p>
            <h3>{m.label}</h3>
            <p>{m.summary}</p>
            <p><strong>Assumes:</strong> {m.assumption}</p>
            <p className="muted tiny">Reference: {m.reference}</p>
          </article>
        ))}
      </div>
      <h2 className="lab-subheading">Reading the measurements</h2>
      <div className="guide-grid">
        {METRIC_NOTES.map(([Icon, tag, title, detail]) => (
          <article className="panel guide-card" key={title}>
            <div className="guide-icon"><Icon size={20} aria-hidden="true" /></div>
            <p className="eyebrow">{tag}</p>
            <h3>{title}</h3>
            <p>{detail}</p>
          </article>
        ))}
      </div>
      <div className="notice-box"><ShieldCheck size={18} aria-hidden="true" /><span>This project is for research and education, not diagnosis. Synthetic-noise results do not demonstrate clinical benefit or generalization across patients and scanners.</span></div>
    </section>
  );
}
