import { Component, useCallback, useRef } from "react";
import { BarChart3, ChevronsLeftRight, FileImage, RefreshCw, TriangleAlert } from "lucide-react";

/**
 * Keeps a failure inside one page (for example a chart library chunk that could not be downloaded) from blanking the whole application:
 * the navigation stays usable and the message says what to do. The App gives it a new key for each page, so another page starts clean.
 */
export class PageBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="api-banner" role="alert" data-testid="page-error">
        <TriangleAlert size={18} aria-hidden="true" />
        <div>
          <strong>This page could not be displayed</strong>
          <p>{String(error?.message || error)}</p>
          <small>A part of the page, such as the chart library, may not have downloaded. Reloading the page usually fixes it; the other pages remain available.</small>
        </div>
        <button type="button" className="secondary-button" onClick={() => window.location.reload()}><RefreshCw size={14} aria-hidden="true" /> Reload the page</button>
      </div>
    );
  }
}

/** Original mark: a jagged (noisy) trace that becomes a smooth one. */
export function BrandMark({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
      <path d="M1.5 13.5l1.4-3.2 1.5 5.4 1.6-7.6 1.6 8.8 1.5-6.4 1.3 3" stroke="currentColor" strokeOpacity=".55" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M11.5 12.6c1.3-4.4 2.9-4.4 4.2 0s2.9 4.4 4.2 0 1.7-2.2 2.6-2.2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function PageHeading({ eyebrow, title, description, action }) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {action && <div>{action}</div>}
    </div>
  );
}

export function EmptyState({ icon: Icon = FileImage, title, detail }) {
  return (
    <div className="empty-state">
      <div className="empty-icon"><Icon size={25} /></div>
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

export function ImagePanel({ title, image, badge, large }) {
  return (
    <article className={"image-panel" + (large ? " image-panel-large" : "")}>
      <div className="panel-heading"><span>{title}</span>{badge && <span className="mini-badge">{badge}</span>}</div>
      {image
        ? <img className="result-image" src={image} alt={title} />
        : <div className="image-placeholder"><FileImage size={24} /><span>Run an experiment to display this image</span></div>}
    </article>
  );
}

/** One figure with its label and a hint. `tone` ("ok" or "bad") colours the figure only when the value itself is a verified state. */
export function MetricCard({ label, value, hint, icon: Icon, tone }) {
  return (
    <article className={"metric-card" + (tone === "ok" ? " is-ok" : tone === "bad" ? " is-bad" : "")}>
      <div className="metric-top"><span>{label}</span><span className="metric-icon"><Icon size={17} /></span></div>
      <strong>{value}</strong>
      <small>{hint}</small>
    </article>
  );
}

/**
 * Two images on top of each other with a draggable divider (the left image is shown to the left of it).
 * The divider moves with the pointer; a separate range input next to the stage is the keyboard-accessible control.
 */
export function CompareStage({ leftSrc, rightSrc, leftLabel, rightLabel, leftAlt, rightAlt, divider, onDivider, aspectRatio }) {
  const stage = useRef(null);
  const dragging = useRef(false);
  const moveTo = useCallback(clientX => {
    const box = stage.current?.getBoundingClientRect();
    if (!box || !box.width) return;
    onDivider(Math.round(Math.min(100, Math.max(0, ((clientX - box.left) / box.width) * 100))));
  }, [onDivider]);
  const onPointerDown = event => { dragging.current = true; event.currentTarget.setPointerCapture?.(event.pointerId); moveTo(event.clientX); };
  const onPointerMove = event => { if (dragging.current) moveTo(event.clientX); };
  const onPointerEnd = event => { dragging.current = false; event.currentTarget.releasePointerCapture?.(event.pointerId); };
  return (
    <div className="compare-stage" ref={stage} style={aspectRatio ? { aspectRatio } : undefined}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerEnd} onPointerCancel={onPointerEnd}>
      <img className="compare-img" src={rightSrc} alt={rightAlt} />
      <img className="compare-img compare-top" src={leftSrc} alt={leftAlt} style={{ clipPath: `inset(0 ${100 - divider}% 0 0)` }} />
      <span className="compare-tag compare-tag-left">{leftLabel}</span>
      <span className="compare-tag compare-tag-right">{rightLabel}</span>
      <span className="compare-line" style={{ left: `${divider}%` }} aria-hidden="true" />
      <span className="compare-handle" style={{ left: `${divider}%` }} aria-hidden="true"><ChevronsLeftRight size={18} /></span>
    </div>
  );
}

export function DataTable({ rows, label = "Data table" }) {
  if (!rows || !rows.length) {
    return <EmptyState icon={BarChart3} title="No measurements yet" detail="Run an experiment or load a benchmark to populate this table." />;
  }
  const keys = Object.keys(rows[0]);
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={label}>
      <table>
        <thead><tr>{keys.map(k => <th key={k} scope="col">{k.replaceAll("_", " ")}</th>)}</tr></thead>
        <tbody>{rows.map((row, i) => <tr key={i}>{keys.map(k => <td key={k}>{row[k] === null || row[k] === undefined ? "—" : String(row[k])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

export function RangeField({ id, label, value, min, max, step, display, onChange, help }) {
  const helpId = help ? `${id}-help` : undefined;
  return (
    <div className="field range-field">
      <div className="range-label">
        <label className="field-label" htmlFor={id}>{label}</label>
        <strong aria-hidden="true">{display}</strong>
      </div>
      <input id={id} type="range" value={value} min={min} max={max} step={step} aria-valuetext={String(display)}
        aria-describedby={helpId} onChange={e => onChange(Number(e.target.value))} />
      {help && <p className="field-help" id={helpId}>{help}</p>}
    </div>
  );
}

export function Notice({ tone = "info", icon: Icon, role, children }) {
  return (
    <div className={"notice-line notice-" + tone} role={role || (tone === "error" ? "alert" : "status")}>
      {Icon && <Icon size={16} aria-hidden="true" />}
      <span>{children}</span>
    </div>
  );
}

/** "kernel_size": 5 -> "kernel size 5"; nested or long values are shown as they are. */
export function formatParams(parameters) {
  const entries = Object.entries(parameters || {});
  if (!entries.length) return "—";
  return entries.map(([key, value]) => `${key.replaceAll("_", " ")} ${typeof value === "number" ? +value.toFixed(4) : value}`).join(", ");
}
