import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, BarChart3, Check, FlaskConical, Info, RefreshCw, ScanLine, Settings2, ShieldCheck, UploadCloud } from "lucide-react";
import { api, apiHostLabel, apiIsLocal, fetchFile } from "./api";
import { EmptyState, Notice, PageHeading, RangeField, formatParams } from "./components";

const FAMILY_ORDER = ["Spatial", "Frequency", "Edge-preserving", "Wavelet"];
const MAX_KERNEL_SLIDER = 31;
const ORIGINAL = "Original input";
const MAX_SEED = 4294967295;      // 2**32 - 1, the server's limit

export function sliderBounds(spec) {
  const min = spec.exclusive_minimum ? Math.max(spec.step, spec.minimum + spec.step) : spec.minimum;
  const limit = spec.integer ? Math.min(spec.maximum, MAX_KERNEL_SLIDER) : spec.maximum;
  const max = spec.exclusive_maximum ? Number((limit - spec.step).toFixed(6)) : limit;   // the server rejects the excluded end point
  return { min, max };
}

export function displayValue(spec, value) {
  if (spec.name === "sigma" && Number(value) === 0) return "Auto";
  const text = spec.integer ? String(value) : Number(value).toFixed(spec.step < 0.1 ? 2 : 1);
  return spec.unit ? `${text} ${spec.unit}` : text;
}

/** Distinct parameters of the selected methods, in catalogue order (a parameter shared by several methods appears once). */
export function activeParameters(methods, selectedIds) {
  const seen = new Map();
  methods.filter(m => selectedIds.has(m.id)).forEach(m => m.parameters.forEach(p => {
    if (!seen.has(p.name)) seen.set(p.name, { spec: p, usedBy: [] });
    seen.get(p.name).usedBy.push(m.label);
  }));
  return [...seen.values()];
}

function groupByFamily(methods) {
  const groups = FAMILY_ORDER.map(family => [family, methods.filter(m => m.family === family)]).filter(([, list]) => list.length);
  const known = new Set(FAMILY_ORDER);
  const rest = methods.filter(m => !known.has(m.family));
  return rest.length ? [...groups, ["Other", rest]] : groups;
}

export default function Lab({ apiOnline = true }) {
  const [catalogue, setCatalogue] = useState({ status: "loading", methods: [], defaults: [], noiseTypes: [], limits: {}, error: "" });
  const [samples, setSamples] = useState([]);
  const [sampleId, setSampleId] = useState("");
  const [input, setInput] = useState(null);
  const [preview, setPreview] = useState(null);
  const [inputError, setInputError] = useState("");
  const [previewBusy, setPreviewBusy] = useState(false);
  const [noiseType, setNoiseType] = useState("Gaussian");
  const [variance, setVariance] = useState(0.02);
  const [amount, setAmount] = useState(0.02);
  const [seed, setSeed] = useState(42);
  const [selected, setSelected] = useState(new Set());
  const [values, setValues] = useState({});
  const [busy, setBusy] = useState(false);
  const [runError, setRunError] = useState("");
  const [result, setResult] = useState(null);
  const [left, setLeft] = useState("Noisy input");
  const [right, setRight] = useState("");
  const [divider, setDivider] = useState(50);
  const localUrl = useRef(null);
  const inputToken = useRef(0);
  const runToken = useRef(0);

  const loadCatalogue = useCallback(() => {
    setCatalogue(c => ({ ...c, status: "loading", error: "" }));
    api("/api/methods").then(body => {
      const defaults = {};
      body.methods.forEach(m => m.parameters.forEach(p => { defaults[p.name] = p.default; }));
      setValues(defaults);
      setSelected(new Set(body.default_methods));
      setCatalogue({ status: "ready", methods: body.methods, defaults: body.default_methods, noiseTypes: body.noise_types, limits: body.limits, error: "" });
    }).catch(e => setCatalogue({ status: "error", methods: [], defaults: [], noiseTypes: [], limits: {}, error: e.message }));
    api("/api/samples").then(body => setSamples(body.samples)).catch(() => setSamples([]));
  }, []);

  useEffect(() => { loadCatalogue(); }, [loadCatalogue]);
  useEffect(() => () => { if (localUrl.current) URL.revokeObjectURL(localUrl.current); }, []);

  const methods = catalogue.methods;
  const orderedSelected = useMemo(() => methods.filter(m => selected.has(m.id)), [methods, selected]);
  const parameters = useMemo(() => activeParameters(methods, selected), [methods, selected]);
  const sample = samples.find(s => s.id === sampleId);
  const pixels = preview?.width && preview?.height ? preview.width * preview.height : null;
  const heavySelected = orderedSelected.filter(m => m.heavy);
  const tooLargeForHeavy = Boolean(pixels && catalogue.limits.max_advanced_pixels && heavySelected.length && pixels > catalogue.limits.max_advanced_pixels);
  const canRun = Boolean(input && preview && orderedSelected.length && !busy && !previewBusy && !tooLargeForHeavy && catalogue.status === "ready");

  function resetResult() {
    runToken.current += 1;
    setResult(null); setRunError(""); setBusy(false);
  }

  async function chooseFile(file, fromSample = "") {
    const token = ++inputToken.current;
    if (localUrl.current) { URL.revokeObjectURL(localUrl.current); localUrl.current = null; }
    resetResult();
    setPreview(null); setInputError(""); setInput(null); setSampleId(fromSample);
    if (!file) return;
    const name = file.name.toLowerCase();
    if (file.type.startsWith("image/") && !name.endsWith(".dcm")) {
      localUrl.current = URL.createObjectURL(file);
      setPreview({ filename: file.name, preview: localUrl.current, format: "Selected image", width: null, height: null, local: true });
    }
    setPreviewBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await api("/api/image/preview", { method: "POST", body });
      if (token !== inputToken.current) return;
      setPreview(response);
      setInput({ file, name: file.name });
    } catch (e) {
      if (token !== inputToken.current) return;
      setPreview(null);
      setInputError(e.message);
    } finally {
      if (token === inputToken.current) setPreviewBusy(false);
    }
  }

  async function chooseSample(id) {
    if (!id) { await chooseFile(null); return; }
    const entry = samples.find(s => s.id === id);
    if (!entry) return;
    setSampleId(id);
    try {
      const file = await fetchFile(entry.file_url, entry.filename, entry.media_type);
      await chooseFile(file, id);
    } catch (e) {
      await chooseFile(null);          // drop the previous image so the sample shown always matches the image that would run
      setInputError(e.message);
    }
  }

  function toggleMethod(id) {
    setSelected(current => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
    resetResult();
  }

  async function run() {
    if (!canRun) return;
    const token = ++runToken.current;
    setBusy(true); setRunError("");
    try {
      const body = new FormData();
      body.append("file", input.file);
      body.append("noise_type", noiseType);
      body.append("noise_amount", String(amount));
      body.append("noise_variance", String(variance));
      body.append("seed", String(seed));
      body.append("methods", orderedSelected.map(m => m.id).join(","));
      parameters.forEach(({ spec }) => body.append(spec.name, String(values[spec.name])));
      const response = await api("/api/denoise", { method: "POST", body });
      if (token !== runToken.current) return;
      setResult({ ...response, original: preview?.preview || null, inputName: input.name });
      setLeft("Noisy input");
      setRight(response.results[1]?.Filter || "Noisy input");
      setDivider(50);
    } catch (e) {
      if (token === runToken.current) { setResult(null); setRunError(e.message); }
    } finally {
      if (token === runToken.current) setBusy(false);
    }
  }

  const sources = useMemo(() => {
    if (!result) return [];
    const list = result.original ? [{ label: ORIGINAL, src: result.original }] : [];
    return [...list, ...Object.entries(result.images).map(([label, src]) => ({ label, src }))];
  }, [result]);
  const sourceOf = label => sources.find(s => s.label === label)?.src;
  const rowOf = label => result?.results.find(r => r.Filter === label);
  const methodOf = label => result?.methods.find(m => m.label === label);
  const filteredRows = result ? result.results.filter(r => r.Filter !== "Noisy input") : [];
  const bestPsnr = Math.max(...filteredRows.map(r => Number(r["PSNR (dB)"])).filter(Number.isFinite), -Infinity);
  const bestSsim = Math.max(...filteredRows.map(r => Number(r.SSIM)).filter(Number.isFinite), -Infinity);
  const local = apiIsLocal();

  return (
    <section>
      <PageHeading eyebrow="IMAGE PROCESSING / 01" title="2D Denoising Lab"
        description="Choose an image, add controlled synthetic noise, run the methods you select and compare the outputs. Every number below is computed by the API for this run."
        action={<span className="pill"><FlaskConical size={14} aria-hidden="true" /> Interactive experiment</span>} />
      <div className="lab-layout">
        <aside className="settings-panel" aria-label="Experiment settings">
          <div className="section-title"><Settings2 size={17} aria-hidden="true" /><h2>Experiment settings</h2></div>

          {catalogue.status === "error" && (
            <div className="error-box" role="alert">
              <span>{catalogue.error}</span>
              <button type="button" className="secondary-button" onClick={loadCatalogue}><RefreshCw size={14} aria-hidden="true" /> Retry</button>
            </div>
          )}
          {catalogue.status === "loading" && <p className="muted tiny" role="status">Loading the method catalogue from the API…</p>}

          <fieldset className="lab-fieldset">
            <legend className="field-label">1. Input image</legend>
            <label className="upload-box compact-upload">
              <UploadCloud size={22} aria-hidden="true" />
              <strong>{input && !sampleId ? input.name : "Upload an image or DICOM slice"}</strong>
              <small>PNG, JPG or DICOM (.dcm)</small>
              <input type="file" accept=".png,.jpg,.jpeg,.dcm" aria-label="Upload an image or DICOM slice"
                onChange={e => { const file = e.target.files?.[0]; setSampleId(""); chooseFile(file); e.target.value = ""; }} />
            </label>
            <div className="field">
              <label className="field-label" htmlFor="lab-sample">…or use a bundled sample</label>
              <select id="lab-sample" value={sampleId} disabled={!samples.length} onChange={e => chooseSample(e.target.value)}
                aria-describedby="lab-sample-info">
                <option value="">{samples.length ? "Choose a sample" : "No samples available on this server"}</option>
                {samples.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
              {sample && (
                <div className="sample-info" id="lab-sample-info">
                  <p><strong>{sample.modality}.</strong> {sample.description}</p>
                  <p><strong>Source:</strong> {sample.provenance} <strong>Licence:</strong> {sample.licence}</p>
                  <p className="sample-caution"><strong>Caution:</strong> {sample.caution}</p>
                </div>
              )}
            </div>
            <p className="field-help">
              {local
                ? "The API runs on this computer; files you choose are not sent to another server."
                : `Files you upload are sent to the server at ${apiHostLabel()}. Do not upload identifiable patient data.`}
            </p>
            {inputError && <div className="error-box" role="alert"><span>{inputError}</span></div>}
          </fieldset>

          <fieldset className="lab-fieldset">
            <legend className="field-label">2. Synthetic noise</legend>
            <div className="field">
              <label className="field-label" htmlFor="lab-noise">Noise model</label>
              <select id="lab-noise" value={noiseType} onChange={e => { setNoiseType(e.target.value); resetResult(); }}>
                {(catalogue.noiseTypes.length ? catalogue.noiseTypes : ["Gaussian", "Salt & Pepper", "Speckle (synthetic)", "None"]).map(n => <option key={n}>{n}</option>)}
              </select>
            </div>
            {noiseType === "Salt & Pepper" && <RangeField id="lab-amount" label="Affected pixels" value={amount} min={0.001} max={0.2} step={0.005} display={amount.toFixed(3)} onChange={v => { setAmount(v); resetResult(); }} help="Fraction of pixels set to black or white." />}
            {(noiseType === "Gaussian" || noiseType === "Speckle (synthetic)") && <RangeField id="lab-variance" label="Noise variance" value={variance} min={0.001} max={0.2} step={0.005} display={variance.toFixed(3)} onChange={v => { setVariance(v); resetResult(); }} help="Variance on the [0, 1] intensity scale (0.02 is a standard deviation of about 0.14)." />}
            {noiseType === "None" && <p className="field-help">No noise is added. Scores then measure similarity to the input, not denoising accuracy.</p>}
            <div className="field">
              <label className="field-label" htmlFor="lab-seed">Random seed</label>
              <input id="lab-seed" type="number" min="0" max="4294967295" value={seed} disabled={noiseType === "None"}
                onChange={e => { setSeed(Math.min(MAX_SEED, Math.max(0, Math.floor(Number(e.target.value) || 0)))); resetResult(); }} />
            </div>
          </fieldset>

          <fieldset className="lab-fieldset">
            <legend className="field-label">3. Methods</legend>
            {groupByFamily(methods).map(([family, list]) => (
              <div className="method-group" key={family}>
                <p className="method-family">{family}</p>
                {list.map(m => (
                  <label className="method-option" key={m.id}>
                    <input type="checkbox" checked={selected.has(m.id)} onChange={() => toggleMethod(m.id)} />
                    <span>{m.label}{m.heavy && <small className="method-cost"> slower</small>}</span>
                  </label>
                ))}
              </div>
            ))}
            {catalogue.status === "ready" && !orderedSelected.length && <p className="field-help field-warning" role="status">Select at least one method.</p>}
            {orderedSelected.length > 0 && (
              <details className="method-details">
                <summary>What the selected methods assume</summary>
                <ul>
                  {orderedSelected.map(m => (
                    <li key={m.id}><strong>{m.label}.</strong> {m.summary} {m.assumption} <span className="muted">Reference: {m.reference}</span></li>
                  ))}
                </ul>
              </details>
            )}
          </fieldset>

          {parameters.length > 0 && (
            <fieldset className="lab-fieldset">
              <legend className="field-label">4. Parameters</legend>
              {parameters.map(({ spec, usedBy }) => {
                const { min, max } = sliderBounds(spec);
                return (
                  <RangeField key={spec.name} id={`lab-${spec.name}`} label={spec.label} value={values[spec.name] ?? spec.default}
                    min={min} max={max} step={spec.step} display={displayValue(spec, values[spec.name] ?? spec.default)}
                    onChange={v => { setValues(current => ({ ...current, [spec.name]: v })); resetResult(); }}
                    help={`${spec.help} Used by: ${usedBy.join(", ")}.`} />
                );
              })}
            </fieldset>
          )}

          {tooLargeForHeavy && (
            <div className="error-box" role="alert">
              <span>{heavySelected.map(m => m.label).join(", ")} {heavySelected.length === 1 ? "is" : "are"} limited to {catalogue.limits.max_advanced_pixels.toLocaleString("en-US")} pixels; this image has {pixels.toLocaleString("en-US")}. Deselect {heavySelected.length === 1 ? "it" : "them"} or use a smaller image.</span>
            </div>
          )}
          <button type="button" className="primary-button full-width" disabled={!canRun} onClick={run} aria-busy={busy} data-testid="lab-run">
            {busy ? <span className="spinner" aria-hidden="true" /> : <Activity size={17} aria-hidden="true" />} {busy ? "Processing image…" : "Run denoising"}
          </button>
          {!input && !previewBusy && catalogue.status === "ready" && <p className="field-help">Choose an image or a sample to enable the run.</p>}
          {runError && <div className="error-box" role="alert" data-testid="lab-error"><span>{runError}</span></div>}
        </aside>

        <div className="lab-results" aria-live="polite">
          <div className="section-heading-row">
            <div><p className="eyebrow">VISUAL COMPARISON</p><h2>Image outputs</h2></div>
            {preview?.width && <span className="file-tag"><Check size={13} aria-hidden="true" />{preview.width} × {preview.height} px</span>}
          </div>

          {!apiOnline && catalogue.status === "error" && <Notice tone="warn" icon={Info}>The API is not reachable, so images cannot be processed. Start the backend (see the README) and press Retry.</Notice>}

          {!preview && !previewBusy && !busy && (
            <EmptyState icon={ScanLine} title="Start with an image" detail="Upload a PNG, JPEG or DICOM slice, or pick a bundled sample. A preview appears here before anything is processed." />
          )}
          {previewBusy && !preview && <p className="muted" role="status"><span className="spinner" aria-hidden="true" /> Reading the image…</p>}

          {preview && !result && (
            <div className="lab-preview">
              <figure className="image-panel">
                <figcaption className="panel-heading"><span>Input image</span><span className="mini-badge">{preview.format}</span></figcaption>
                <img className="result-image" src={preview.preview} alt={`Preview of ${preview.filename}`} />
              </figure>
              <div className="panel preview-info">
                <p className="eyebrow">READY</p>
                <h3>{busy ? "Processing…" : "Choose methods, then run"}</h3>
                <p className="muted">{busy ? "The API is filtering the image. Larger images and the slower methods take longer." : "Nothing has been computed yet. Scores and images appear here after you run the experiment."}</p>
                {preview.format === "DICOM" && <p className="field-help">DICOM intensities are mapped to [0, 1] with the file's window (or min–max). Scores are on that display scale, not in Hounsfield units.</p>}
              </div>
            </div>
          )}

          {result && (
            <>
              <p className="sr-only" role="status">Processing finished: {result.results.length - 1} outputs in {Math.round(result.timings_ms.total)} milliseconds.</p>
              <div className="compare" data-testid="compare">
                <div className="compare-controls">
                  <label className="field-label" htmlFor="cmp-left">Left</label>
                  <select id="cmp-left" value={left} onChange={e => setLeft(e.target.value)}>{sources.map(s => <option key={s.label}>{s.label}</option>)}</select>
                  <label className="field-label" htmlFor="cmp-right">Right</label>
                  <select id="cmp-right" value={right} onChange={e => setRight(e.target.value)}>{sources.map(s => <option key={s.label}>{s.label}</option>)}</select>
                </div>
                <div className="compare-stage" style={{ aspectRatio: `${result.width} / ${result.height}` }}>
                  <img className="compare-img" src={sourceOf(right)} alt={`${right}, shown on the right of the divider`} />
                  <img className="compare-img compare-top" src={sourceOf(left)} alt={`${left}, shown on the left of the divider`} style={{ clipPath: `inset(0 ${100 - divider}% 0 0)` }} />
                  <span className="compare-tag compare-tag-left">{left}</span>
                  <span className="compare-tag compare-tag-right">{right}</span>
                  <span className="compare-line" style={{ left: `${divider}%` }} aria-hidden="true" />
                </div>
                <label className="field-label" htmlFor="cmp-divider">Divider position</label>
                <input id="cmp-divider" className="compare-range" type="range" min="0" max="100" value={divider} onChange={e => setDivider(Number(e.target.value))} data-testid="compare-slider" />
              </div>

              <h3 className="lab-subheading">All outputs</h3>
              <div className="output-grid">
                {sources.map(s => {
                  const row = rowOf(s.label);
                  return (
                    <figure className="output-card" key={s.label}>
                      <button type="button" className="output-thumb" aria-pressed={right === s.label} onClick={() => setRight(s.label)} title={`Show ${s.label} on the right of the divider`}>
                        <img src={s.src} alt={s.label} loading="lazy" />
                      </button>
                      <figcaption><strong>{s.label}</strong>{row && <span>PSNR {row["PSNR (dB)"]} dB · SSIM {row.SSIM}</span>}</figcaption>
                    </figure>
                  );
                })}
              </div>

              <div className="panel results-table-panel">
                <div className="panel-heading"><span>Quantitative measurements</span><span className="mini-badge">LIVE RUN · {Math.round(result.timings_ms.total)} ms TOTAL</span></div>
                <p className="muted tiny table-note">
                  {result.noise_type === "None" ? "No noise added" : `${result.noise_type} noise`}
                  {result.settings.noise_variance != null ? `, variance ${result.settings.noise_variance}` : ""}
                  {result.settings.noise_amount != null ? `, ${result.settings.noise_amount} of pixels` : ""}
                  {result.settings.seed != null ? `, seed ${result.settings.seed}` : ""}. Input: {result.inputName}.
                </p>
                <div className="table-wrap" tabIndex={0} role="region" aria-label="Measurements for this run">
                  <table data-testid="lab-results-table">
                    <thead><tr><th scope="col">Method</th><th scope="col">PSNR (dB)</th><th scope="col">SSIM</th><th scope="col">Time (ms)</th><th scope="col">Parameters used</th></tr></thead>
                    <tbody>
                      {result.results.map(row => {
                        const method = methodOf(row.Filter);
                        const isFiltered = row.Filter !== "Noisy input";
                        return (
                          <tr key={row.Filter}>
                            <th scope="row">{row.Filter}</th>
                            <td className={isFiltered && Number(row["PSNR (dB)"]) === bestPsnr ? "cell-top" : ""}>{row["PSNR (dB)"]}</td>
                            <td className={isFiltered && Number(row.SSIM) === bestSsim ? "cell-top" : ""}>{row.SSIM}</td>
                            <td>{result.timings_ms[row.Filter] ?? "—"}</td>
                            <td>{method ? formatParams(method.parameters) : "—"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="muted tiny table-note">Bold values mark the highest PSNR and SSIM among the filtered outputs of this run. They can point to different methods, and neither shows that anatomy or small structures are preserved. Timings are wall-clock milliseconds measured by the server.</p>
              </div>
              <Notice tone="info" icon={ShieldCheck}>{result.note}</Notice>
              {preview?.format === "DICOM" && <Notice tone="info" icon={Info}>DICOM input: intensities are mapped to [0, 1] with the file's window (or min–max), so these scores are on a display scale, not in Hounsfield units. The Benchmark V2 page reports HU-domain metrics for CT.</Notice>}
              <Notice tone="warn" icon={BarChart3}>Research and education only. Not a diagnostic tool; nothing here shows clinical benefit.</Notice>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
