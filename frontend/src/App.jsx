import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, BarChart3, ChevronRight, CircleHelp, FlaskConical, Layers3, LayoutDashboard, Menu, Moon, RefreshCw, ScanLine, ShieldCheck, Sun, TriangleAlert, X } from "lucide-react";
import { api, apiHostLabel } from "./api";
import BenchmarkV2 from "./BenchmarkV2";
import CtExplorer from "./CtExplorer";
import Guide from "./Guide";
import Lab from "./Lab";
import Overview from "./Overview";
import Results from "./Results";

const NAV = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "lab", label: "2D Denoising Lab", icon: ScanLine },
  { id: "v2", label: "Benchmark V2", icon: FlaskConical },
  { id: "ct", label: "3D CT Explorer", icon: Layers3 },
  { id: "results", label: "Older 2D results", icon: BarChart3 },
  { id: "guide", label: "Methods & Guide", icon: CircleHelp },
];
const NO_RESULTS = { available: false, rows: [], noise_types: [] };
// How often the page checks the API: quickly while it is down (so it recovers by itself), slowly while it is up (to notice it stopping).
export const POLL_OFFLINE_MS = 2000;
export const POLL_ONLINE_MS = 5000;

function storedTheme() {
  try { return localStorage.getItem("biomed-theme") || "dark"; } catch { return "dark"; }
}

export default function App() {
  const [page, setPage] = useState("overview");
  const [theme, setTheme] = useState(storedTheme);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [health, setHealth] = useState("checking");
  const [healthError, setHealthError] = useState(null);
  const [problems, setProblems] = useState([]);
  const [apiEpoch, setApiEpoch] = useState(0);
  const [benchmark, setBenchmark] = useState(NO_RESULTS);
  const healthRef = useRef("checking");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("biomed-theme", theme); } catch { /* storage may be unavailable */ }
  }, [theme]);

  const ping = useCallback(async () => {
    try {
      const body = await api("/api/health");
      if (healthRef.current === "offline") setApiEpoch(epoch => epoch + 1);   // pages that failed while the API was down load again
      healthRef.current = "online";
      setHealth("online"); setHealthError(null); setProblems(body.problems || []);
    } catch (error) {
      healthRef.current = "offline";
      setHealth("offline"); setHealthError(error);
    }
  }, []);

  useEffect(() => { ping(); }, [ping]);
  useEffect(() => { api("/api/results").then(setBenchmark).catch(() => setBenchmark(NO_RESULTS)); }, [apiEpoch]);
  useEffect(() => {
    const delay = health === "offline" ? POLL_OFFLINE_MS : health === "online" ? POLL_ONLINE_MS : null;
    if (delay === null) return undefined;
    const timer = setInterval(ping, delay);
    return () => clearInterval(timer);
  }, [health, ping]);

  const currentNav = NAV.find(n => n.id === page);
  const go = id => { setPage(id); setSidebarOpen(false); };
  const offlineTitle = healthError?.kind === "dashboard-down" ? "The dashboard server is not responding" : "The API is not reachable";
  const statusText = health === "online" ? `Connected to ${apiHostLabel()}` : health === "offline" ? (healthError?.message || "Cannot reach the API.") : "Contacting the API…";

  return (
    <div className="app-shell">
      {sidebarOpen && <button type="button" className="sidebar-scrim" onClick={() => setSidebarOpen(false)} aria-label="Close navigation" />}
      <aside className={"sidebar" + (sidebarOpen ? " sidebar-open" : "")} aria-label="Primary">
        <div className="brand">
          <div className="brand-mark"><Activity size={23} aria-hidden="true" /></div>
          <div className="brand-copy"><strong>MED<span>LAB</span></strong><small>IMAGING WORKSPACE</small></div>
          <button type="button" className="icon-button mobile-close" onClick={() => setSidebarOpen(false)} aria-label="Close navigation"><X size={18} aria-hidden="true" /></button>
        </div>
        <div className="workspace-tag"><span className="status-dot" /> RESEARCH WORKSPACE</div>
        <p className="nav-label">WORKSPACE</p>
        <nav className="main-nav" aria-label="Pages">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button type="button" key={id} className={"nav-item" + (page === id ? " active" : "")} aria-current={page === id ? "page" : undefined} onClick={() => go(id)}>
              <Icon size={18} aria-hidden="true" /><span>{label}</span>{page === id && <ChevronRight className="nav-chevron" size={15} aria-hidden="true" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-status" data-testid="api-status">
          <div className="status-head">
            <span className={"status-dot " + (health === "online" ? "online" : health === "offline" ? "offline" : "")} /> API {health.toUpperCase()}
            {health === "offline" && <button type="button" className="icon-button" onClick={ping} aria-label="Check the API connection again"><RefreshCw size={13} aria-hidden="true" /></button>}
          </div>
          <p>{statusText}</p>
          <div className="privacy-note"><ShieldCheck size={16} aria-hidden="true" /><span>Research and education only. Not for diagnosis.</span></div>
        </div>
        <div className="sidebar-footer"><span>BIOMEDICAL IMAGE DENOISING AND BENCHMARKING</span></div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <button type="button" className="icon-button mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><Menu size={20} aria-hidden="true" /></button>
            <span className="breadcrumb">Workspace</span><ChevronRight size={14} aria-hidden="true" /><strong>{currentNav?.label}</strong>
          </div>
          <div className="topbar-right">
            <span className="live-pill"><span className={"status-dot " + (health === "online" ? "online" : health === "offline" ? "offline" : "")} /> {health === "online" ? "API CONNECTED" : health === "offline" ? "API OFFLINE" : "CHECKING API"}</span>
            <button type="button" className="theme-toggle" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
              {theme === "dark" ? <><Sun size={17} aria-hidden="true" />Light mode</> : <><Moon size={17} aria-hidden="true" />Dark mode</>}
            </button>
          </div>
        </header>
        <div className="page-content">
          {health === "offline" && (
            <div className="api-banner" role="alert" data-testid="api-banner">
              <TriangleAlert size={18} aria-hidden="true" />
              <div>
                <strong>{offlineTitle}</strong>
                <p>{healthError?.message}</p>
                <small>Checking again every {POLL_OFFLINE_MS / 1000} seconds; the pages reload their data by themselves when the connection returns.</small>
              </div>
              <button type="button" className="secondary-button" onClick={ping}><RefreshCw size={14} aria-hidden="true" /> Retry now</button>
            </div>
          )}
          {health === "online" && problems.length > 0 && (
            <div className="api-banner api-banner-warn" role="status" data-testid="api-problems">
              <TriangleAlert size={18} aria-hidden="true" />
              <div><strong>Part of the API is unavailable</strong>{problems.map(text => <p key={text}>{text}</p>)}</div>
            </div>
          )}
          {page === "overview" && <Overview setPage={go} benchmark={benchmark} apiState={health} apiEpoch={apiEpoch} />}
          {page === "lab" && <Lab apiOnline={health === "online"} apiEpoch={apiEpoch} />}
          {page === "v2" && <BenchmarkV2 apiEpoch={apiEpoch} />}
          {page === "ct" && <CtExplorer apiState={health} />}
          {page === "results" && <Results benchmark={benchmark} apiState={health} apiMessage={healthError?.message} />}
          {page === "guide" && <Guide apiEpoch={apiEpoch} />}
        </div>
        <footer className="main-footer"><span>MEDLAB · BIOMEDICAL IMAGE DENOISING AND BENCHMARKING</span><span>RESEARCH SOFTWARE <b>/</b> NOT FOR DIAGNOSIS</span></footer>
      </main>
    </div>
  );
}
