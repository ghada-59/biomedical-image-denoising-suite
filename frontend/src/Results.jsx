import { useMemo, useState } from "react";
import { Activity, ArrowDownToLine, BarChart3, FileText, ScanLine, Waves } from "lucide-react";
import { DataTable, EmptyState, MetricCard, PageHeading } from "./components";

const COLORS = ["#7188ff", "#22a699", "#e3a64f", "#b18aff", "#5ca8e8", "#e27d9b", "#8d9aa8"];
const NOISE = ["Gaussian", "Salt & Pepper", "Speckle (synthetic)", "None"];

/** The older file holds a spatial and a frequency-domain table, each with its own unfiltered baseline, and a "Gauss" next to a "Gaussian": the domain tells them apart. */
export function filterLabel(row) {
  return row.Domain ? `${row.Filter} (${String(row.Domain).toLowerCase()})` : String(row.Filter);
}

function MetricBars({ title, rows, field }) {
  const values = rows.filter(row => Number.isFinite(Number(row[field]))).sort((a, b) => Number(b[field]) - Number(a[field]));
  const max = Math.max(...values.map(row => Number(row[field])), 0.001);
  return (
    <div className="bar-chart">
      <h3>{title}</h3>
      {values.map((row, i) => (
        <div className="bar-row" key={String(row.Filter) + String(row.Domain)}>
          <div className="bar-label">{filterLabel(row)}</div>
          <div className="bar-track"><div className="bar-fill" style={{ width: Math.max(2, Number(row[field]) / max * 100) + "%", background: COLORS[i % COLORS.length] }} /></div>
          <strong>{Number(row[field]).toFixed(field === "Mean_SSIM" ? 4 : 2)}</strong>
        </div>
      ))}
    </div>
  );
}

function downloadJson(rows) {
  const blob = new Blob([JSON.stringify(rows, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = "denoising-benchmark.json"; anchor.click();
  URL.revokeObjectURL(url);
}

export default function Results({ benchmark, apiState = "online", apiMessage = "" }) {
  const [noise, setNoise] = useState("Gaussian");
  const rows = useMemo(() => (benchmark.rows || []).filter(row => String(row.Noise) === noise), [benchmark.rows, noise]);
  const best = useMemo(() => rows.reduce((a, b) => (!a || Number(b.Mean_SSIM) > Number(a.Mean_SSIM) ? b : a), null), [rows]);
  const provenance = benchmark.provenance;
  return (
    <section>
      <PageHeading eyebrow="EXPERIMENT SUMMARY / 03" title="Results & Reports"
        description="Explore the older 2D benchmark file found by the API. Its provenance status is shown below. Newer, tuned and held-out comparisons are on the Benchmark V2 page."
        action={<span className="pill"><BarChart3 size={14} aria-hidden="true" />{benchmark.available ? (provenance?.status === "documented_run" ? "Documented run" : "Historical results") : "No benchmark"}</span>} />
      {apiState === "offline" ? (
        <EmptyState icon={BarChart3} title="Results cannot be loaded: the API is not reachable" detail={apiMessage || "Start the backend; this page loads the results by itself when it answers."} />
      ) : apiState === "checking" ? (
        <p className="muted" role="status">Contacting the API…</p>
      ) : benchmark.available ? (
        <>
          <div className="benchmark-toolbar">
            <div>
              <label className="field-label" htmlFor="bench-noise">Noise model</label>
              <select id="bench-noise" value={noise} onChange={e => setNoise(e.target.value)}>
                {(benchmark.noise_types?.length ? benchmark.noise_types : NOISE).map(n => <option key={n}>{n}</option>)}
              </select>
            </div>
            <div className="source-label"><FileText size={15} aria-hidden="true" /> Source: {benchmark.source}</div>
          </div>
          <p className="footnote" role="status" data-testid="provenance-banner">
            <strong>{provenance?.label || "Historical results — provenance and currency not verified"}</strong>
            {provenance?.reason ? ". " + provenance.reason : ""}
            {provenance?.file_modified ? (provenance?.reason ? " " : ". ") + "File modified: " + provenance.file_modified + "." : ""}
          </p>
          <div className="metrics-grid">
            <MetricCard label="Highest mean SSIM" value={best ? filterLabel(best) : "—"} hint="Within selected noise model" icon={Activity} />
            <MetricCard label="Mean SSIM" value={best ? Number(best.Mean_SSIM).toFixed(4) : "—"} hint="Structural similarity" icon={ScanLine} />
            <MetricCard label="Mean PSNR" value={best ? Number(best.Mean_PSNR_dB).toFixed(2) + " dB" : "—"} hint="Peak signal-to-noise ratio" icon={Waves} />
            <MetricCard label="Runs evaluated" value={best?.Runs_Evaluated ?? "—"} hint="Repeated synthetic-noise runs" icon={BarChart3} />
          </div>
          <div className="panel chart-panel">
            <div className="panel-heading"><span>Filter comparison</span><span className="mini-badge">MEAN METRICS</span></div>
            <div className="chart-grid">
              <MetricBars title="Mean SSIM" rows={rows} field="Mean_SSIM" />
              <MetricBars title="Mean PSNR (dB)" rows={rows} field="Mean_PSNR_dB" />
            </div>
          </div>
          <div className="panel results-table-panel">
            <div className="panel-heading"><span>Benchmark data</span><span className="mini-badge">{rows.length} rows</span></div>
            <DataTable label="Older 2D benchmark data" rows={rows} />
            <button type="button" className="secondary-button download-button" onClick={() => downloadJson(rows)}><ArrowDownToLine size={16} aria-hidden="true" /> Export filtered data (JSON)</button>
          </div>
          <p className="footnote">Benchmark values are from controlled experiments with synthetic noise on CT slices. Repeated noise realizations are not independent patients and do not establish clinical performance.</p>
        </>
      ) : (
        <EmptyState icon={BarChart3} title="Benchmark results are not available"
          detail="Run the benchmark locally to generate reports/denoising_summary.csv, then restart the API. Historical figures in docs/results are not loaded as current measurements." />
      )}
    </section>
  );
}
