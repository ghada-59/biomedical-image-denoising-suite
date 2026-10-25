import { useEffect, useMemo, useState } from "react";
import { ArrowDownToLine, FlaskConical, ShieldCheck } from "lucide-react";
import { Plot } from "./plot";
import { API_BASE_URL, api, queryString } from "./api";

const METRICS = [
  { key: "RMSE_HU", label: "RMSE (HU)", unit: "HU", lowerIsBetter: true, note: "Error in Hounsfield units over the mask, unclipped." },
  { key: "MAE_HU", label: "MAE (HU)", unit: "HU", lowerIsBetter: true, note: "Mean absolute error in Hounsfield units over the mask." },
  { key: "PSNR_dB", label: "PSNR (dB)", unit: "dB", lowerIsBetter: false, note: "Computed on images displayed with the -600/1500 HU window, not on HU." },
  { key: "SSIM_Wang2004", label: "SSIM (Wang 2004)", unit: "", lowerIsBetter: false, note: "Windowed display images; 11x11 Gaussian window, windows fully inside the mask." },
];
const MASKS = { main: "Principal mask", inner: "Inner mask (10 px from padding removed)" };
const FAMILY_COLORS = { "Noisy (no filter)": "#8d9aa8", Mean: "#7188ff", Median: "#22a699", Gaussian: "#e3a64f", "FFT ideal": "#b18aff", "FFT Gaussian": "#5ca8e8", "FFT Butterworth": "#e27d9b", Bilateral: "#8bd17c", "Non-local means": "#ff8a65", "Wavelet BayesShrink": "#4dd0e1" };
const ADDED_NOTES = {
  Bilateral: "Bilateral: the tuned value is the intensity scale (HU); the spatial scale is fixed.",
  "Non-local means": "Non-local means: the tuned value is the filtering strength h (HU); patch and search window are fixed, and the true noise level is not supplied.",
  "Wavelet BayesShrink": "Wavelet BayesShrink: the tuned value is the noise level the thresholds ASSUME (HU), used as a strength control, not a measurement.",
};
const RANGE_NOTE = "Intervals are 95% percentile bootstrap intervals over test slices of one patient; they under-cover and are descriptive.";

function useThemeTick() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const observer = new MutationObserver(() => setTick(value => value + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return tick;
}

function themeColors() {
  const style = getComputedStyle(document.documentElement);
  const read = (name, fallback) => (style.getPropertyValue(name) || fallback).trim() || fallback;
  return { text: read("--text", "#edf1e8"), muted: read("--muted", "#b2bdaf"), grid: read("--border", "#37463b") };
}

function baseLayout(title, xTitle, yTitle, extra) {
  const c = themeColors();
  return {
    title: { text: title, font: { size: 13, color: c.text } }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: c.muted, size: 11 }, margin: { l: 62, r: 14, t: 42, b: 150 }, legend: { orientation: "h", x: 0, y: -0.42, yanchor: "top", entrywidth: 110, entrywidthmode: "pixels", font: { size: 10 } },
    xaxis: { title: { text: xTitle, standoff: 14 }, gridcolor: c.grid, automargin: true, tickangle: -30 }, yaxis: { title: { text: yTitle }, gridcolor: c.grid, zeroline: true, zerolinecolor: c.grid },
    autosize: true, ...extra,
  };
}

function Section({ title, badge, children, note }) {
  return <section className="panel v2-section"><div className="panel-heading"><span>{title}</span>{badge && <span className="mini-badge">{badge}</span>}</div><div className="v2-body">{children}{note && <p className="footnote">{note}</p>}</div></section>;
}

function Notice({ tone, children }) {
  return <div className={"v2-notice v2-" + (tone || "info")} role="status">{children}</div>;
}

function paramText(raw) {
  try {
    const params = typeof raw === "string" ? JSON.parse(raw) : raw;
    const entries = Object.entries(params || {});
    return entries.length ? entries.map(([k, v]) => `${k.replaceAll("_", " ")} ${v === null ? "none (identity)" : v}`).join(", ") : "—";
  } catch { return String(raw); }
}

export function classifyGridChange(row) {
  // new minus old; for error metrics lower is better, for PSNR and SSIM higher is better.
  const lower = row.metric === "RMSE_HU" || row.metric === "MAE_HU";
  if (row.identical_to_old) return "identical";
  const improved = lower ? row.ci_high < 0 : row.ci_low > 0;
  const worse = lower ? row.ci_low > 0 : row.ci_high < 0;
  return improved ? "improved" : worse ? "worse" : "unresolved";
}

export function summariseGridChanges(rows) {
  const table = {};
  rows.forEach(row => {
    const key = `${row.metric}|${row.mask}`;
    table[key] = table[key] || { metric: row.metric, mask: row.mask, improved: 0, worse: 0, identical: 0, unresolved: 0 };
    table[key][classifyGridChange(row)] += 1;
  });
  return Object.values(table);
}

function csvLink(runId, name, extra) {
  return `${API_BASE_URL}/api/v2/runs/${encodeURIComponent(runId)}/tables/${name}?${queryString({ format: "csv", ...extra })}`;
}

function useTable(runId, name, enabled = true) {
  const [state, setState] = useState({ rows: null, error: "" });
  useEffect(() => {
    if (!runId || !enabled) { setState({ rows: null, error: "" }); return undefined; }
    let alive = true;
    setState({ rows: null, error: "" });
    api(`/api/v2/runs/${encodeURIComponent(runId)}/tables/${name}`)
      .then(body => alive && setState({ rows: body.rows, error: "" }))
      .catch(e => alive && setState({ rows: null, error: e.message }));
    return () => { alive = false; };
  }, [runId, name, enabled]);
  return state;
}

function MetricCharts({ summary, metric, scenario }) {
  useThemeTick();
  const def = METRICS.find(m => m.key === metric);
  const conditions = useMemo(() => [...new Set(summary.map(r => r.condition))].filter(c => scenario === "all" || (scenario === "ct" ? !c.startsWith("robustness") : c.startsWith("robustness"))), [summary, scenario]);
  const families = useMemo(() => [...new Set(summary.map(r => r.family))], [summary]);
  return <div className="v2-chart-grid">
    {Object.entries(MASKS).map(([mask, label]) => {
      const traces = families.map(family => {
        const rows = conditions.map(c => summary.find(r => r.condition === c && r.mask === mask && r.family === family));
        const mean = rows.map(r => r?.[`${metric}_mean`] ?? null), low = rows.map(r => r?.[`${metric}_ci_low`]), high = rows.map(r => r?.[`${metric}_ci_high`]);
        return { type: "bar", name: family, x: conditions, y: mean, marker: { color: FAMILY_COLORS[family] || "#999" },
          error_y: { type: "data", symmetric: false, array: high.map((h, i) => (h == null || mean[i] == null ? 0 : h - mean[i])), arrayminus: low.map((l, i) => (l == null || mean[i] == null ? 0 : mean[i] - l)), thickness: 1, width: 2 },
          hovertemplate: `%{x}<br>${family}: %{y:.3f} ${def.unit}<extra></extra>` };
      });
      return <div key={mask} className="v2-chart"><Plot data={traces} layout={baseLayout(`${def.label} — ${label}`, "Noise condition (synthetic)", `${def.label}${def.unit ? "" : ""}`, { barmode: "group" })} config={{ responsive: true, displaylogo: false }} useResizeHandler style={{ width: "100%", height: 380 }}/></div>;
    })}
  </div>;
}

function GainChart({ summary, metric, condition }) {
  useThemeTick();
  const def = METRICS.find(m => m.key === metric);
  const families = [...new Set(summary.map(r => r.family))].filter(f => f !== "Noisy (no filter)");
  const traces = Object.entries(MASKS).map(([mask, label], i) => {
    const rows = families.map(f => summary.find(r => r.condition === condition && r.mask === mask && r.family === f));
    const mean = rows.map(r => r?.[`${metric}_gain_mean`] ?? null), low = rows.map(r => r?.[`${metric}_gain_ci_low`]), high = rows.map(r => r?.[`${metric}_gain_ci_high`]);
    return { type: "bar", name: label, x: families, y: mean, marker: { color: i ? "#e3a64f" : "#7188ff" },
      error_y: { type: "data", symmetric: false, array: high.map((h, k) => (h == null || mean[k] == null ? 0 : h - mean[k])), arrayminus: low.map((l, k) => (l == null || mean[k] == null ? 0 : mean[k] - l)), thickness: 1, width: 2 },
      hovertemplate: `%{x}: %{y:+.3f} ${def.unit}<extra>${label}</extra>` };
  });
  return <Plot data={traces} layout={baseLayout(`Change of ${def.label} versus the unfiltered noisy image — ${condition}`, "Tuned filter", `Filtered minus unfiltered${def.unit ? " (" + def.unit + ")" : ""}`, { barmode: "group" })} config={{ responsive: true, displaylogo: false }} useResizeHandler style={{ width: "100%", height: 380 }}/>;
}

function DataTable({ rows, columns }) {
  if (!rows || !rows.length) return <p className="footnote">No rows for this selection.</p>;
  return <div className="table-wrap"><table><thead><tr>{columns.map(c => <th key={c.key}>{c.label}</th>)}</tr></thead>
    <tbody>{rows.map((row, i) => <tr key={i}>{columns.map(c => <td key={c.key}>{c.render ? c.render(row) : (row[c.key] ?? "—")}</td>)}</tr>)}</tbody></table></div>;
}

function SliceViewer({ run, conditions }) {
  useThemeTick();
  const slices = [...run.test_slices.map(s => ({ s, role: "test" })), ...run.tune_slices.map(s => ({ s, role: "tuning" }))];
  const [slice, setSlice] = useState(run.test_slices[0]);
  const [condition, setCondition] = useState(conditions[1] || conditions[0]);
  const [repeat, setRepeat] = useState(1);
  const [center, setCenter] = useState(-600);
  const [width, setWidth] = useState(1500);
  const [diffRange, setDiffRange] = useState(100);
  const [overlay, setOverlay] = useState("");
  const [mode, setMode] = useState("filtered");
  const [row, setRow] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const maxRepeat = slices.find(x => x.s === slice)?.role === "tuning" ? run.tune_repeats : run.test_repeats;

  useEffect(() => {
    let alive = true;
    setBusy(true); setError("");
    api(`/api/v2/runs/${encodeURIComponent(run.id)}/slice-comparison?${queryString({ slice, condition, repeat: Math.min(repeat, maxRepeat), row })}`)
      .then(body => { if (alive) setData(body); })
      .catch(e => { if (alive) { setError(e.message); setData(null); } })
      .finally(() => alive && setBusy(false));
    return () => { alive = false; };
  }, [run.id, slice, condition, repeat, row, maxRepeat]);

  const imageUrl = view => `${API_BASE_URL}/api/v2/runs/${encodeURIComponent(run.id)}/slice-image?${queryString({ slice, condition, repeat: Math.min(repeat, maxRepeat), view, window_center: center, window_width: width, diff_range_hu: diffRange, overlay })}`;
  const profileTraces = data ? [{ x: data.profile.reference.map((_, i) => i), y: data.profile.reference, name: "Reference (clinical slice)", line: { color: "#ffffff", width: 1.2, dash: "dot" } },
    ...Object.entries(data.profile.series).map(([name, y]) => ({ x: y.map((_, i) => i), y, name, line: { width: 1, color: FAMILY_COLORS[name] } }))] : [];

  return <div>
    <div className="v2-controls">
      <label>Slice<select value={slice} onChange={e => { setSlice(Number(e.target.value)); setRow(null); }}>{slices.map(x => <option key={x.s} value={x.s}>{x.s} ({x.role})</option>)}</select></label>
      <label>Noise condition<select value={condition} onChange={e => setCondition(e.target.value)}>{conditions.map(c => <option key={c}>{c}</option>)}</select></label>
      <label>Noise realisation<input type="number" min="1" max={maxRepeat} value={Math.min(repeat, maxRepeat)} onChange={e => setRepeat(Math.max(1, Math.min(maxRepeat, Number(e.target.value) || 1)))}/></label>
      <label>Window centre (HU) {center}<input type="range" min="-1000" max="500" step="10" value={center} onChange={e => setCenter(Number(e.target.value))}/></label>
      <label>Window width (HU) {width}<input type="range" min="100" max="4000" step="50" value={width} onChange={e => setWidth(Number(e.target.value))}/></label>
      <label>Show<select value={mode} onChange={e => setMode(e.target.value)}><option value="filtered">Filtered images</option><option value="diff">Difference maps (filtered − reference)</option></select></label>
      <label>Difference scale ±{diffRange} HU<input type="range" min="10" max="500" step="10" value={diffRange} onChange={e => setDiffRange(Number(e.target.value))}/></label>
      <label>Mask outline<select value={overlay} onChange={e => setOverlay(e.target.value)}><option value="">None</option><option value="main">Principal mask</option><option value="inner">Inner mask</option></select></label>
    </div>
    {busy && <p className="footnote" role="status">Recomputing from the recorded seed…</p>}
    {error && <Notice tone="warn">{error}</Notice>}
    {data && <>
      <Notice tone={data.reproduces_recorded_run?.all_match ? "ok" : "info"}>
        {data.reproduces_recorded_run
          ? (data.reproduces_recorded_run.all_match ? `Recomputed values match the ${data.reproduces_recorded_run.compared} recorded test rows (RMSE_HU, principal mask) for this slice, condition and realisation.` : "Some recomputed values differ from the recorded run; do not treat these images as the recorded result.")
          : "This is a tuning slice; the run stored no per-realisation test rows for it, so the recomputation cannot be compared with a record."}
        {" "}Seed {data.seed}. Images are windowed for display only; the metrics use HU.
      </Notice>
      <div className="v2-image-grid">
        <figure><figcaption>Reference (noisy clinical slice) — window {center}/{width} HU</figcaption><img src={imageUrl("reference")} alt="Reference slice" loading="lazy"/></figure>
        <figure><figcaption>With synthetic noise ({condition})</figcaption><img src={imageUrl(mode === "diff" ? "diff:" + "Noisy (no filter)" : "noisy")} alt="Noisy slice" loading="lazy"/></figure>
        {data.outputs.filter(o => o.family !== "Noisy (no filter)").map(o => <figure key={o.family}><figcaption>{o.family}{o.identity ? " — identity (no filtering)" : ""}<br/><small>{paramText(o.params)}</small></figcaption><img src={imageUrl((mode === "diff" ? "diff:" : "filtered:") + o.family)} alt={`${o.family} ${mode}`} loading="lazy"/></figure>)}
      </div>
      <p className="footnote">Difference maps show the filtered (or noisy) image minus the reference in HU on a grey scale where mid-grey is zero; they are not maps of clinical change. A smoother image is not by itself a more faithful one.</p>
      <h3 className="v2-h3">Metrics of this realisation</h3>
      <DataTable rows={data.outputs} columns={[
        { key: "family", label: "Method" },
        { key: "p", label: "Parameters", render: o => paramText(o.params) },
        { key: "m", label: "RMSE principal (HU)", render: o => o.metrics.main.RMSE_HU.toFixed(2) },
        { key: "i", label: "RMSE inner (HU)", render: o => o.metrics.inner.RMSE_HU.toFixed(2) },
        { key: "b", label: `RMSE ≤${data.boundary_band_px} px from mask edge (HU)`, render: o => o.rmse_hu_boundary_band?.toFixed(2) ?? "—" },
        { key: "c", label: `RMSE deeper than ${data.boundary_band_px} px (HU)`, render: o => o.rmse_hu_core?.toFixed(2) ?? "—" },
        { key: "s", label: "SSIM (Wang)", render: o => o.metrics.main.SSIM_Wang2004?.toFixed(4) ?? "—" },
        { key: "p2", label: "PSNR (dB)", render: o => o.metrics.main.PSNR_dB?.toFixed(2) ?? "—" },
      ]}/>
      <p className="footnote">The boundary band is {(data.band_fraction_of_mask * 100).toFixed(1)}% of the principal mask. Compare its error with the deeper region: RMSE_HU on the principal mask can be dominated by this thin band. The band/core split is descriptive, not a benchmark metric.</p>
      <div className="v2-controls"><label>Profile row {row ?? data.row}<input type="range" min="0" max={data.shape[0] - 1} value={row ?? data.row} onChange={e => setRow(Number(e.target.value))}/></label></div>
      <Plot data={profileTraces} layout={baseLayout(`Intensity profile along image row ${data.profile.row}`, "Column (pixel)", "HU", { margin: { l: 62, r: 14, t: 42, b: 90 } })} config={{ responsive: true, displaylogo: false }} useResizeHandler style={{ width: "100%", height: 360 }}/>
    </>}
  </div>;
}

export default function BenchmarkV2() {
  const [state, setState] = useState({ status: "loading", runs: [], caveats: [], sliceOk: false, error: "" });
  const [runId, setRunId] = useState("");
  const [metric, setMetric] = useState("RMSE_HU");
  const [scenario, setScenario] = useState("ct");
  const [condition, setCondition] = useState("white_25HU");
  const [statements, setStatements] = useState([]);

  useEffect(() => {
    api("/api/v2/runs").then(body => {
      setState({ status: body.runs.length ? "ready" : "empty", runs: body.runs, caveats: body.caveats, sliceOk: body.slice_comparison_available, error: "" });
      if (body.runs.length) setRunId(body.runs[body.runs.length - 1].id);
    }).catch(e => setState({ status: "error", runs: [], caveats: [], sliceOk: false, error: e.message }));
  }, []);

  const run = state.runs.find(r => r.id === runId);
  const summary = useTable(runId, "test_summary");
  const selected = useTable(runId, "selected_parameters");
  const bracketing = useTable(runId, "grid_bracketing", !!run?.tables.includes("grid_bracketing"));
  const criteria = useTable(runId, "tuning_criteria_comparison", !!run?.tables.includes("tuning_criteria_comparison"));
  const gridCmp = useTable(runId, "comparison_vs_initial_grid", !!run?.tables.includes("comparison_vs_initial_grid"));

  useEffect(() => {
    if (!runId) return undefined;
    let alive = true;
    api(`/api/v2/runs/${encodeURIComponent(runId)}/interpretation`).then(b => alive && setStatements(b.statements)).catch(() => alive && setStatements([]));
    return () => { alive = false; };
  }, [runId]);

  if (state.status === "loading") return <p className="footnote" role="status">Loading benchmark runs…</p>;
  if (state.status === "error") return <Notice tone="warn">The API is not reachable ({state.error}). Start the backend to view benchmark results.</Notice>;
  if (state.status === "empty") return <div className="empty-state"><div className="empty-icon"><FlaskConical size={25}/></div><h3>No benchmark V2 run is configured</h3><p>Set the BENCHMARK_RUN_DIRS environment variable on the API server to one or more run directories (each containing run_metadata.json). Nothing is displayed until real results are available.</p></div>;

  const conditions = run.conditions;
  const bracketByKey = Object.fromEntries((bracketing.rows || []).map(r => [`${r.condition}|${r.family}`, r]));
  const integrityOk = run.integrity.status === "verified";
  const addedFamilies = (run.families || []).filter(f => ADDED_NOTES[f]);
  const agreement = criteria.rows ? { n: criteria.rows.length, psnr: criteria.rows.filter(r => r.PSNR_agrees).length, ssim: criteria.rows.filter(r => r.SSIM_agrees).length } : null;

  return <section className="v2-page">
    <div className="page-heading"><div><p className="eyebrow">EXPLORATORY STUDY / 04</p><h1>Benchmark V2</h1>
      <p className="page-description">{(run.families || []).length || "Several"} classical denoisers compared under synthetic noise on one CT series. Every number below is read from the files of a recorded run or recomputed from its recorded seeds.</p></div></div>

    <Notice tone="warn"><ShieldCheck size={15}/> Exploratory study: one patient, few slices, a noisy clinical reference and synthetic noise. Not clinically validated and not evidence that any filter is best in general.</Notice>

    <Section title="Run and provenance" badge={integrityOk ? "FILES VERIFIED" : "CHECK FILES"}>
      <div className="v2-controls"><label>Run<select value={runId} onChange={e => setRunId(e.target.value)}>{state.runs.map(r => <option key={r.id} value={r.id}>{r.id}</option>)}</select></label></div>
      <ul className="v2-facts">
        <li><strong>Grid</strong> {run.grid_version}</li><li><strong>Generated</strong> {run.generated_at}</li>
        <li><strong>Source state</strong> {run.git_commit.slice(0, 12)} — {run.source_state}</li>
        <li><strong>Series</strong> {run.series_label} (identity with a public release not verified)</li>
        <li><strong>Tuning slices</strong> {run.tune_slices.join(", ")} × {run.tune_repeats} realisations</li>
        <li><strong>Test slices</strong> {run.test_slices.join(", ")} × {run.test_repeats} realisations</li>
        <li><strong>CSV integrity</strong> {run.integrity.status === "verified" ? `${run.integrity.files_checked} files match the recorded SHA-256` : run.integrity.status}{run.integrity.mismatched.length ? ` (changed: ${run.integrity.mismatched.join(", ")})` : ""}</li>
        <li><strong>Comparable with the historical results</strong> no</li>
      </ul>
      {!integrityOk && <Notice tone="warn">The files of this run do not match the hashes recorded in its metadata. Treat the numbers with caution.</Notice>}
      <ul className="v2-caveats">{state.caveats.map(c => <li key={c}>{c}</li>)}</ul>
    </Section>

    <Section title="Test-slice metrics by method" badge="WITH 95% BOOTSTRAP INTERVALS" note={RANGE_NOTE}>
      <div className="v2-controls">
        <label>Metric<select value={metric} onChange={e => setMetric(e.target.value)}>{METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}</select></label>
        <label>Scenarios<select value={scenario} onChange={e => setScenario(e.target.value)}><option value="ct">White and correlated noise (6)</option><option value="robustness">Robustness tests (salt-and-pepper, speckle)</option><option value="all">All 8</option></select></label>
      </div>
      <p className="footnote">{METRICS.find(m => m.key === metric).note} {METRICS.find(m => m.key === metric).lowerIsBetter ? "Lower is better." : "Higher is better."} Tuned on the principal mask with RMSE_HU only; both masks are scored. The two metrics families can disagree, so no single ranking is shown.</p>
      {summary.error ? <Notice tone="warn">{summary.error}</Notice> : summary.rows ? <MetricCharts summary={summary.rows} metric={metric} scenario={scenario}/> : <p className="footnote">Loading…</p>}
      <a className="secondary-button v2-download" href={csvLink(runId, "test_summary")}><ArrowDownToLine size={14}/> Download test_summary.csv</a>
    </Section>

    <Section title="Change relative to the unfiltered noisy image" badge="PAIRED OVER TEST SLICES" note="Negative values lower the error for RMSE and MAE; for PSNR and SSIM, positive values are an improvement. A zero bar with no interval is a tuned choice that did not filter (identity).">
      <div className="v2-controls"><label>Noise condition<select value={condition} onChange={e => setCondition(e.target.value)}>{conditions.map(c => <option key={c}>{c}</option>)}</select></label></div>
      {summary.rows && <GainChart summary={summary.rows} metric={metric} condition={condition}/>}
      <h3 className="v2-h3">What the data say for {condition}</h3>
      <ul className="v2-statements">{statements.filter(s => s.condition === condition).map((s, i) => <li key={i}>{s.text}</li>)}{!statements.some(s => s.condition === condition) && <li>No statement can be made from the available values.</li>}</ul>
    </Section>

    <Section title={`Tuned parameters — ${condition}`} badge="CHOSEN ON 3 TUNING SLICES" note="'identity' means no smoothing scored best under RMSE_HU on the principal mask; it does not show that smoothing is useless elsewhere in the image. 'interior' means both neighbours in the grid scored worse.">
      <DataTable rows={(selected.rows || []).filter(r => r.condition === condition)} columns={[
        { key: "family", label: "Family" }, { key: "params", label: "Selected parameters", render: r => paramText(r.params) },
        { key: "tuning_score", label: "Tuning RMSE (HU)", render: r => Number(r.tuning_score).toFixed(2) },
        { key: "status", label: "Grid position", render: r => bracketByKey[`${r.condition}|${r.family}`]?.status ?? "—" },
      ]}/>
      {addedFamilies.map(f => <p className="footnote" key={f}>{ADDED_NOTES[f]}</p>)}
      {agreement && <p className="footnote">Across all {agreement.n} tuned settings of this run, PSNR would have chosen the same parameters as RMSE_HU in {agreement.psnr} and SSIM in {agreement.ssim} (tuning slices only).</p>}
    </Section>

    {gridCmp.rows && <Section title="Expanded grid versus the first grid" badge="FILTERED VS FILTERED" note="Each cell compares the tuned result of this run with the tuned result of the first run. 'identical' means the same setting was selected. This is not a comparison with the unfiltered image, and it is not an independent validation: test slices were inspected before the grid was expanded.">
      <DataTable rows={summariseGridChanges(gridCmp.rows)} columns={[
        { key: "metric", label: "Metric" }, { key: "mask", label: "Mask", render: r => (r.mask === "main" ? "principal" : "inner") },
        { key: "improved", label: "Improved" }, { key: "worse", label: "Worse" }, { key: "identical", label: "Identical setting" }, { key: "unresolved", label: "Unresolved" }]}/>
      <p className="footnote">An improvement in RMSE_HU on the principal mask (the tuning criterion) does not carry over to the inner mask or to SSIM; read the rows together.</p>
    </Section>}

    {state.sliceOk && run.tables.includes("selected_parameters") ? <Section title="Look at the images" badge="RECOMPUTED FROM THE RECORDED SEED">
      <SliceViewer key={run.id} run={run} conditions={conditions}/>
    </Section> : <Section title="Look at the images"><p className="footnote">Image comparison needs the CT series on the server (CT_SERIES_DIR). It is not configured, so no images are shown.</p></Section>}
  </section>;
}
