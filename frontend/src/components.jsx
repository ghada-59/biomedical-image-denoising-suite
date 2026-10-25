import { BarChart3, FileImage } from "lucide-react";

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

export function MetricCard({ label, value, hint, icon: Icon }) {
  return (
    <article className="metric-card">
      <div className="metric-top"><span>{label}</span><span className="metric-icon"><Icon size={17} /></span></div>
      <strong>{value}</strong>
      <small>{hint}</small>
    </article>
  );
}

export function DataTable({ rows }) {
  if (!rows || !rows.length) {
    return <EmptyState icon={BarChart3} title="No measurements yet" detail="Run an experiment or load a benchmark to populate this table." />;
  }
  const keys = Object.keys(rows[0]);
  return (
    <div className="table-wrap">
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
