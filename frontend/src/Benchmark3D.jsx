import { useEffect, useMemo, useState } from "react";
import { ArrowDownToLine, Box, ShieldCheck } from "lucide-react";
import { Plot } from "./plot";
import { API_BASE_URL, api, queryString } from "./api";
import { METHOD_COLORS_3D, baseLayout, intervalBars, themeColors, useThemeTick } from "./chartTheme";
import { PageHeading } from "./components";

const METRICS = [
  { key: "RMSE_HU", label: "RMSE (HU)", unit: "HU", lowerIsBetter: true, note: "Error against the reference slice in Hounsfield units, unclipped, over the mask." },
  { key: "MAE_HU", label: "MAE (HU)", unit: "HU", lowerIsBetter: true, note: "Mean absolute error in Hounsfield units over the mask." },
  { key: "blur_rmse_hu", label: "Structure change (HU)", unit: "HU", lowerIsBetter: true, note: "RMS of f(reference) minus reference: what the filter does to the clean slice with no noise present. It also contains the removal of the reference's own noise, so it is not a pure loss of anatomy." },
  { key: "residual_noise_hu", label: "Residual noise (HU)", unit: "HU", lowerIsBetter: true, note: "RMS of f(noisy) minus f(reference): the noise that is left. RMSE squared equals structure change squared plus residual noise squared plus a cross term." },
  { key: "PSNR_dB", label: "PSNR (dB)", unit: "dB", lowerIsBetter: false, note: "Computed on images displayed with the -600/1500 HU window, not on HU. Not defined for the soft-tissue region." },
  { key: "SSIM_Wang2004", label: "SSIM (Wang 2004)", unit: "", lowerIsBetter: false, note: "Windowed display images; 11 x 11 Gaussian window, windows fully inside the mask. Not defined for the soft-tissue region." },
];
const MASKS = { main: "Principal mask (body, lung boundaries included)", inner: "Inner mask (10 px from the padding removed)", soft: "Homogeneous soft tissue (0 to 100 HU, away from edges)" };
const FIGURE_CAPTIONS = {
  "tradeoff_curves.png": "Recorded figure: structure change against residual noise on the tuning slices for every grid setting; dotted arcs are lines of equal RMSE; large circles mark the setting selected for each method.",
  "test_rmse.png": "Recorded figure: held-out RMSE_HU (principal mask) with the 95 % bootstrap interval over the 8 test slices of one patient.",
};
const RANGE_NOTE = "Intervals are 95 % percentile bootstrap intervals over 8 test slices of one patient; they describe spread over slices and under-cover (about 78 to 89 % for a nominal 95 % in a simulation).";

function Section({ title, badge, children, note }) {
  return <section className="panel v2-section"><div className="panel-heading"><span>{title}</span>{badge && <span className="mini-badge">{badge}</span>}</div><div className="v2-body">{children}{note && <p className="footnote">{note}</p>}</div></section>;
}

function Notice({ tone, children }) {
  return <div className={"v2-notice v2-" + (tone || "info")} role="status">{children}</div>;
}

function paramsOf(raw) {
  try { return typeof raw === "string" ? JSON.parse(raw) : (raw || {}); } catch { return {}; }
}

function useTable(runId, name, extra, enabled = true) {
  const [state, setState] = useState({ rows: null, error: "" });
  const key = JSON.stringify(extra || {});
  useEffect(() => {
    if (!runId || !enabled) { setState({ rows: null, error: "" }); return undefined; }
    let alive = true;
    setState({ rows: null, error: "" });
    const query = queryString(extra || {});
    api(`/api/3d/runs/${encodeURIComponent(runId)}/tables/${name}${query ? "?" + query : ""}`)
      .then(body => alive && setState({ rows: body.rows, error: "" }))
      .catch(e => alive && setState({ rows: null, error: e.message }));
    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, name, key, enabled]);
  return state;
}

function useInterpretation(runs) {
  const [state, setState] = useState({});
  const ids = runs.map(r => r.id).join("|");
  useEffect(() => {
    let alive = true;
    Promise.all(runs.map(r => api(`/api/3d/runs/${encodeURIComponent(r.id)}/interpretation`).then(body => [r.id, body]).catch(() => [r.id, null])))
      .then(entries => alive && setState(Object.fromEntries(entries)));
    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids]);
  return state;
}

function MetricChart({ summary, metric, mask, methods }) {
  useThemeTick();
  const def = METRICS.find(m => m.key === metric);
  const conditions = useMemo(() => [...new Set(summary.map(r => r.condition))], [summary]);
  const traces = ["Noisy (no filter)", ...methods].map(method => {
    const rows = conditions.map(c => summary.find(r => r.condition === c && r.mask === mask && r.method === method));
    const mean = rows.map(r => r?.[`${metric}_mean`] ?? null), low = rows.map(r => r?.[`${metric}_ci_low`] ?? null), high = rows.map(r => r?.[`${metric}_ci_high`] ?? null);
    return { type: "bar", name: method, x: conditions.map(c => c.replace("white_", "").replace("HU", " HU")), y: mean, marker: { color: METHOD_COLORS_3D[method] || "#999" }, error_y: intervalBars(mean, low, high),
      hovertemplate: `%{x}<br>${method}: %{y:.3f} ${def.unit}<extra></extra>` };
  });
  return <Plot data={traces} layout={baseLayout(`${def.label} on the held-out slices`, "Noise standard deviation (synthetic)", def.label, { barmode: "group", margin: { l: 62, r: 14, t: 42, b: 110 }, legend: { orientation: "h", x: 0, y: -0.3, yanchor: "top" }, xaxis: { title: { text: "Noise standard deviation (synthetic)" }, automargin: true } })}
    config={{ responsive: true, displaylogo: false }} useResizeHandler style={{ width: "100%", height: 400 }} />;
}

function TradeoffChart({ grid, selected, condition, mask, sigma, methods }) {
  useThemeTick();
  const colors = themeColors();
  const rows = grid.filter(r => r.condition === condition);
  const chosen = new Set(selected.filter(r => r.condition === condition).map(r => `${r.method}|${r.params}`));
  const x = r => r[`blur_rmse_hu_${mask}`], y = r => r[`residual_noise_hu_${mask}`];
  const traces = methods.map(method => {
    const own = rows.filter(r => r.method === method && x(r) != null);
    return { type: "scatter", mode: "markers", name: method, x: own.map(x), y: own.map(y), marker: { color: METHOD_COLORS_3D[method], size: own.map(r => (chosen.has(`${r.method}|${r.params}`) ? 15 : 6)), opacity: own.map(r => (chosen.has(`${r.method}|${r.params}`) ? 1 : 0.55)), line: { color: colors.text, width: own.map(r => (chosen.has(`${r.method}|${r.params}`) ? 2 : 0)) } },
      text: own.map(r => Object.entries(paramsOf(r.params)).map(([k, v]) => `${k.replaceAll("_", " ")} ${v}`).join(", ")),
      hovertemplate: `${method}<br>%{text}<br>structure %{x:.2f} HU, residual noise %{y:.2f} HU<extra></extra>` };
  });
  traces.push({ type: "scatter", mode: "markers", name: "Unfiltered", x: [0], y: [sigma], marker: { symbol: "x", size: 11, color: colors.text }, hovertemplate: `Unfiltered: residual noise ${sigma} HU<extra></extra>` });
  const arcs = [0.25, 0.5, 0.75, 1].map(f => ({ type: "circle", xref: "x", yref: "y", x0: -f * sigma, y0: -f * sigma, x1: f * sigma, y1: f * sigma, line: { color: colors.grid, width: 1, dash: "dot" } }));
  const layout = baseLayout(`Structure change versus residual noise — ${condition.replace("white_", "").replace("HU", " HU")} noise, tuning slices`, "Structure change (HU)", "Residual noise (HU)",
    { shapes: arcs, margin: { l: 62, r: 14, t: 42, b: 110 }, legend: { orientation: "h", x: 0, y: -0.28, yanchor: "top" },
      xaxis: { title: { text: "Structure change (HU)" }, range: [-sigma * 0.03, sigma * 0.8], gridcolor: colors.grid, automargin: true }, yaxis: { title: { text: "Residual noise (HU)" }, range: [-sigma * 0.03, sigma * 1.05], gridcolor: colors.grid, scaleanchor: "x" } });
  return <Plot data={traces} layout={layout} config={{ responsive: true, displaylogo: false }} useResizeHandler style={{ width: "100%", height: 460 }} />;
}

function PairedChart({ statements }) {
  useThemeTick();
  const rows = statements.filter(s => s.paired_difference_hu !== undefined);
  const labels = rows.map(s => s.condition.replace("white_", "").replace("HU", " HU"));
  const mean = rows.map(s => s.paired_difference_hu), low = rows.map(s => s.ci_low), high = rows.map(s => s.ci_high);
  const trace = { type: "scatter", mode: "markers", x: labels, y: mean, name: "Anisotropic 3D minus slice-wise 2D", marker: { color: METHOD_COLORS_3D["3D anisotropic Gaussian"], size: 11 }, error_y: intervalBars(mean, low, high),
    hovertemplate: "%{x}: %{y:+.3f} HU<extra></extra>" };
  return <Plot data={[trace]} layout={baseLayout("Anisotropic 3D minus slice-wise 2D, RMSE_HU (principal mask); below 0 = lower error with 3D", "Noise standard deviation (synthetic)", "Paired difference (HU)",
    { margin: { l: 70, r: 14, t: 42, b: 70 }, showlegend: false, xaxis: { title: { text: "Noise standard deviation (synthetic)" }, automargin: true } })}
    config={{ responsive: true, displaylogo: false }} useResizeHandler style={{ width: "100%", height: 320 }} />;
}

function DataTable({ rows, columns, label }) {
  if (!rows || !rows.length) return <p className="footnote">No rows for this selection.</p>;
  return <div className="table-wrap" tabIndex={0} role="region" aria-label={label}><table><thead><tr>{columns.map(c => <th key={c.key} scope="col">{c.label}</th>)}</tr></thead>
    <tbody>{rows.map((row, i) => <tr key={i}>{columns.map(c => <td key={c.key}>{c.render ? c.render(row) : (row[c.key] ?? "—")}</td>)}</tr>)}</tbody></table></div>;
}

const fixed = (value, digits = 2) => (value === null || value === undefined ? "—" : Number(value).toFixed(digits));
const signed = (value, digits = 2) => (value === null || value === undefined ? "—" : (Number(value) >= 0 ? "+" : "") + Number(value).toFixed(digits));
const csvLink = (runId, name) => `${API_BASE_URL}/api/3d/runs/${encodeURIComponent(runId)}/tables/${name}?${queryString({ format: "csv" })}`;

export default function Benchmark3D({ apiEpoch = 0 }) {
  const [state, setState] = useState({ status: "loading", runs: [], caveats: [], error: "" });
  const [runId, setRunId] = useState("");
  const [metric, setMetric] = useState("RMSE_HU");
  const [mask, setMask] = useState("main");
  const [condition, setCondition] = useState("white_50HU");

  useEffect(() => {
    api("/api/3d/runs").then(body => {
      setState({ status: body.runs.length ? "ready" : "empty", runs: body.runs, caveats: body.caveats, error: "" });
      if (body.runs.length) setRunId(body.runs[0].id);
    }).catch(e => setState({ status: "error", runs: [], caveats: [], error: e.message }));
  }, [apiEpoch]);

  const run = state.runs.find(r => r.id === runId);
  const summary = useTable(runId, "test_summary");
  const selected = useTable(runId, "selected_parameters");
  const grid = useTable(runId, "tuning_grid", { condition });
  const interpretations = useInterpretation(state.runs);
  const interpretation = interpretations[runId];

  if (state.status === "loading") return <p className="footnote" role="status">Loading Benchmark 3D runs…</p>;
  if (state.status === "error") return <Notice tone="warn">Benchmark 3D results cannot be loaded. {state.error}</Notice>;
  if (state.status === "empty") {
    return <div className="empty-state"><div className="empty-icon"><Box size={25} /></div><h3>No Benchmark 3D run is configured</h3>
      <p>Set the BENCHMARK_3D_RUN_DIRS environment variable on the API server to one or more run directories (each containing run_metadata.json). Nothing is displayed until real results are available.</p></div>;
  }

  const def = METRICS.find(m => m.key === metric);
  const spacing = run.voxel_spacing_xyz_mm || [null, null, null];
  const sigmaOf = c => Number(c.replace("white_", "").replace("HU", ""));
  const conditions = (run.noise_sigmas_hu || []).map(s => `white_${s}HU`);
  const integrityOk = run.integrity.status === "verified";
  const correlated = Boolean(run.noise_model?.adjacent_slice_correlation);
  const statements = interpretation?.statements || [];
  const reproduce = correlated
    ? "python benchmark_3d_correlated.py --dicom-series \"path/to/LIDC-IDRI-0709/<series folder>\" --out \"path/outside/repo/benchmark_3d_correlated_run\""
    : "python benchmark_3d.py --dicom-series \"path/to/LIDC-IDRI-0709/<series folder>\" --out \"path/outside/repo/benchmark_3d_run\"";

  return <section className="v2-page">
    <PageHeading eyebrow="EXPLORATORY STUDY" title="Benchmark 3D"
      description="Does smoothing across neighbouring slices help? Slice-wise (2D), isotropic 3D and anisotropic 3D Gaussian smoothing, with widths in millimetres, tuned on separate slices and compared on held-out slices of one CT series. Every number is read from the files of a recorded run." />

    <Notice tone="warn"><ShieldCheck size={15} aria-hidden="true" /> Exploratory study: one patient, 8 held-out slices, a noisy clinical reference and synthetic noise. Only Gaussian smoothing is compared. Not clinically validated and not evidence that volumetric smoothing is better or worse in general.</Notice>

    <Section title="Run and provenance" badge={integrityOk ? "FILES VERIFIED" : "CHECK FILES"}>
      <div className="v2-controls"><label>Run<select value={runId} onChange={e => setRunId(e.target.value)}>{state.runs.map(r => <option key={r.id} value={r.id}>{r.id}</option>)}</select></label></div>
      <ul className="v2-facts">
        <li><strong>Noise model</strong> {run.noise_model.kind}{correlated ? ` (correlation ${run.noise_model.adjacent_slice_correlation} with the adjacent slice)` : ""}</li>
        {run.noise_model.note && <li><strong>Reading</strong> {run.noise_model.note}</li>}
        <li><strong>Voxel spacing</strong> {spacing.map(v => fixed(v, 2)).join(" x ")} mm (x, y, z); volume {run.volume_shape_zyx?.join(" x ")} (z, y, x)</li>
        <li><strong>Tuning slices</strong> {run.tune_slices.join(", ")} x {run.tune_repeats} realisations; <strong>test slices</strong> {run.test_slices.join(", ")} x {run.test_repeats} realisations</li>
        <li><strong>Selection</strong> {run.selection_criterion} on the {run.primary_mask} mask, tuning slices only; bootstrap seed {run.bootstrap_seed}, {run.n_boot} resamples</li>
        <li><strong>Generated</strong> {run.generated_at}; <strong>source state</strong> {run.git_commit.slice(0, 12)} — {run.source_state}</li>
        <li><strong>Source files recorded</strong> {run.source_files.join(", ")} (SHA-256 in the run metadata)</li>
        <li><strong>Series</strong> {run.series_label} (public TCIA series; identity at file level with the public release not verified)</li>
        <li><strong>Result files</strong> {integrityOk ? `${run.integrity.files_checked} files match the recorded SHA-256` : run.integrity.status}{run.integrity.mismatched.length ? ` (changed: ${run.integrity.mismatched.join(", ")})` : ""}</li>
        <li><strong>Comparable with the historical results</strong> no</li>
      </ul>
      {!integrityOk && <Notice tone="warn">The files of this run do not match the hashes recorded in its metadata. Treat the numbers with caution.</Notice>}
      <ul className="v2-caveats">{state.caveats.map(c => <li key={c}>{c}</li>)}</ul>
    </Section>

    <Section title="Held-out results by method" badge="WITH 95% BOOTSTRAP INTERVALS" note={RANGE_NOTE}>
      <div className="v2-controls">
        <label>Metric<select value={metric} onChange={e => setMetric(e.target.value)}>{METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}</select></label>
        <label>Region<select value={mask} onChange={e => setMask(e.target.value)}>{Object.entries(MASKS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      </div>
      <p className="footnote">{def.note} {def.lowerIsBetter ? "Lower is better." : "Higher is better."} Parameters were selected on the principal mask with RMSE_HU only; the other regions and metrics are reported, not optimised.</p>
      {summary.error ? <Notice tone="warn">{summary.error}</Notice> : summary.rows ? <MetricChart summary={summary.rows} metric={metric} mask={mask} methods={run.methods} /> : <p className="footnote">Loading…</p>}
      <a className="secondary-button v2-download" href={csvLink(runId, "test_summary")}><ArrowDownToLine size={14} aria-hidden="true" /> Download test_summary.csv</a>
    </Section>

    <Section title="What the data say" badge="COMPUTED FROM THE TABLES" note="Counts compare the anisotropic 3D family with slice-wise 2D smoothing slice by slice. When the two families selected the same setting their outputs are identical. Statements concern RMSE_HU on the principal mask of this series only.">
      {interpretation ? <>
        <ul className="statement-list">{statements.map(s => <li key={s.condition}>{s.text}</li>)}</ul>
        <PairedChart statements={statements} />
      </> : <p className="footnote">Loading…</p>}
    </Section>

    <Section title="Structure change versus residual noise" badge="TUNING SLICES" note="Each point is one smoothing setting. Moving right changes the clean structure more; moving down leaves less noise. RMSE is the distance from the origin when the cross term is small, so points near the origin have the lowest error. Large circled points are the settings selected for each method. The structure change also contains the removal of the reference's own noise.">
      <div className="v2-controls">
        <label>Noise level<select value={condition} onChange={e => setCondition(e.target.value)}>{conditions.map(c => <option key={c} value={c}>{c.replace("white_", "").replace("HU", " HU")}</option>)}</select></label>
        <label>Region<select value={mask} onChange={e => setMask(e.target.value)}>{Object.entries(MASKS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      </div>
      {grid.error ? <Notice tone="warn">{grid.error}</Notice> : grid.rows && selected.rows ? <TradeoffChart grid={grid.rows} selected={selected.rows} condition={condition} mask={mask} sigma={sigmaOf(condition)} methods={run.methods} /> : <p className="footnote">Loading…</p>}
    </Section>

    <Section title="Selected parameters" badge="CHOSEN ON THE TUNING SLICES" note="Widths are physical (millimetres) and converted with the voxel spacing, so the same value means a very different number of voxels along z (3 mm slices) and in plane (0.54 mm pixels). A z width of 0 means no smoothing across slices; an isotropic setting uses the same width on every axis.">
      <DataTable label="Selected parameters" rows={(selected.rows || []).map(r => ({ ...r, p: paramsOf(r.params) }))} columns={[
        { key: "condition", label: "Noise", render: r => r.condition.replace("white_", "").replace("HU", " HU") },
        { key: "method", label: "Method" },
        { key: "xy", label: "In-plane width (mm)", render: r => fixed(r.p.sigma_xy_mm, 2) },
        { key: "xypx", label: "In plane (pixels)", render: r => (spacing[1] ? fixed(r.p.sigma_xy_mm / spacing[1], 2) : "—") },
        { key: "z", label: "Across slices (mm)", render: r => fixed(r.p.sigma_z_mm, 2) },
        { key: "zsl", label: "Across slices (slices)", render: r => (spacing[2] ? fixed(r.p.sigma_z_mm / spacing[2], 2) : "—") },
      ]} />
    </Section>

    {state.runs.length > 1 && <Section title="Runs side by side" badge="SAME PROTOCOL, DIFFERENT NOISE" note="Both runs use the same slices, grids, seed bases and selection rule; only the added noise differs. The noise of one run is independent between slices, the other is correlated with the adjacent slice, as the real noise of the series is.">
      <DataTable label="Runs compared" rows={state.runs.flatMap(r => (interpretations[r.id]?.statements || []).filter(s => s.paired_difference_hu !== undefined).map(s => ({ run: r, s })))} columns={[
        { key: "run", label: "Run", render: o => o.run.id },
        { key: "noise", label: "Noise between slices", render: o => (o.run.noise_model?.adjacent_slice_correlation ? `correlation ${o.run.noise_model.adjacent_slice_correlation}` : "independent") },
        { key: "level", label: "Noise level", render: o => o.s.condition.replace("white_", "").replace("HU", " HU") },
        { key: "two", label: "2D RMSE (HU)", render: o => fixed(o.s.rmse_hu["2D slice-wise Gaussian"], 2) },
        { key: "aniso", label: "3D anisotropic RMSE (HU)", render: o => fixed(o.s.rmse_hu["3D anisotropic Gaussian"], 2) },
        { key: "diff", label: "Paired difference [interval] (HU)", render: o => `${signed(o.s.paired_difference_hu)} [${signed(o.s.ci_low)}, ${signed(o.s.ci_high)}]` },
        { key: "slices", label: "Slices lower / higher", render: o => `${o.s.slices_lower} / ${o.s.slices_higher}` },
      ]} />
    </Section>}

    <Section title="Recorded figures" badge="AS RECORDED">
      <div className="figure-grid">
        {run.figures.map(name => <figure className="figure-card" key={name}>
          <img src={`${API_BASE_URL}/api/3d/runs/${encodeURIComponent(run.id)}/figures/${name}`} alt={FIGURE_CAPTIONS[name] || name} loading="lazy" />
          <figcaption>{FIGURE_CAPTIONS[name] || name}</figcaption>
        </figure>)}
      </div>
    </Section>

    <Section title="Limitations and reproduction">
      <p className="footnote">{run.limitations}</p>
      <p className="footnote">The CT series is not part of the repository. To repeat this run locally with the same series (about 8 minutes), see the README and run:</p>
      <pre className="command-box" tabIndex={0} role="region" aria-label="Command that repeats this run">{reproduce}</pre>
    </Section>
  </section>;
}
