// Tests of the redesigned shell and shared components, and of the design tokens themselves (WCAG contrast of the real CSS values).
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fs from "node:fs";
import path from "node:path";
import App from "../App";
import { CompareStage, MetricCard, PageBoundary } from "../components";
import { Activity } from "lucide-react";
import { PIXEL, baseRoutes, mockApi } from "./mockApi";

const plotCalls = vi.hoisted(() => []);                                          // every render of a chart, with the props it was given
vi.mock("../plot", () => ({ Plot: props => { plotCalls.push(props); return <div data-testid="plot" />; } }));

describe("PageBoundary", () => {
  function Broken() { throw new Error("Failed to fetch dynamically imported module: /assets/plotly.js"); }

  it("shows what failed and how to recover instead of blanking the application", () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});        // React logs the caught error
    const muteWindowError = event => event.preventDefault();                       // and jsdom reports it as an uncaught error of the window
    window.addEventListener("error", muteWindowError);
    try {
      render(<PageBoundary><Broken /></PageBoundary>);
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("This page could not be displayed");
      expect(alert).toHaveTextContent("Failed to fetch dynamically imported module");
      expect(within(alert).getByRole("button", { name: /Reload the page/ })).toBeInTheDocument();
    } finally { window.removeEventListener("error", muteWindowError); quiet.mockRestore(); }
  });

  it("renders its children when nothing fails", () => {
    render(<PageBoundary><p>fine</p></PageBoundary>);
    expect(screen.getByText("fine")).toBeInTheDocument();
    expect(screen.queryByTestId("page-error")).toBeNull();
  });
});

describe("CompareStage", () => {
  function stageAt(divider = 50) {
    const onDivider = vi.fn();
    const view = render(<CompareStage leftSrc="l.png" rightSrc="r.png" leftLabel="Left" rightLabel="Right" leftAlt="left image" rightAlt="right image" divider={divider} onDivider={onDivider} aspectRatio="1 / 1" />);
    const stage = view.container.querySelector(".compare-stage");
    stage.getBoundingClientRect = () => ({ left: 100, width: 200, right: 300, top: 0, bottom: 200, height: 200 });
    return { stage, onDivider };
  }

  it("clips the left image at the divider and labels both sides", () => {
    stageAt(30);
    expect(screen.getByAltText("left image").style.clipPath).toBe("inset(0 70% 0 0)");
    expect(screen.getByText("Left")).toBeInTheDocument();
    expect(screen.getByText("Right")).toBeInTheDocument();
  });

  // jsdom has no PointerEvent with coordinates, so the pointer events are mouse events of the pointer types (React listens by type).
  const pointer = (stage, type, clientX) => fireEvent(stage, new MouseEvent(type, { clientX, bubbles: true, cancelable: true }));

  it("moves the divider to the pointer while it is pressed, and clamps it to the image", () => {
    const { stage, onDivider } = stageAt();
    pointer(stage, "pointerdown", 150);
    expect(onDivider).toHaveBeenLastCalledWith(25);                              // (150 - 100) / 200
    pointer(stage, "pointermove", 250);
    expect(onDivider).toHaveBeenLastCalledWith(75);
    pointer(stage, "pointermove", 900);
    expect(onDivider).toHaveBeenLastCalledWith(100);
    pointer(stage, "pointermove", -40);
    expect(onDivider).toHaveBeenLastCalledWith(0);
    pointer(stage, "pointerup", 0);
    onDivider.mockClear();
    pointer(stage, "pointermove", 120);
    expect(onDivider).not.toHaveBeenCalled();                                    // a hover without a press does nothing
  });
});

describe("MetricCard", () => {
  it("colours the figure only when a tone is given", () => {
    const { container, rerender } = render(<MetricCard label="Files" value="28" hint="verified" icon={Activity} />);
    expect(container.querySelector("article")).not.toHaveClass("is-ok");
    rerender(<MetricCard label="Files" value="28" hint="verified" icon={Activity} tone="ok" />);
    expect(container.querySelector("article")).toHaveClass("is-ok");
    rerender(<MetricCard label="Files" value="2" hint="differ" icon={Activity} tone="bad" />);
    expect(container.querySelector("article")).toHaveClass("is-bad");
  });
});

describe("navigation rail", () => {
  it("collapses to icons, keeps every page reachable by name, and remembers the choice", async () => {
    const user = userEvent.setup();
    localStorage.clear();
    mockApi(baseRoutes());
    const first = render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Pages" });
    const shell = first.container.querySelector(".app-shell");
    expect(shell).not.toHaveClass("sidebar-collapsed");
    await user.click(screen.getByRole("button", { name: /Collapse navigation/ }));
    expect(shell).toHaveClass("sidebar-collapsed");
    expect(localStorage.getItem("biomed-sidebar")).toBe("rail");
    expect(screen.getByRole("button", { name: /Expand navigation/ })).toHaveAttribute("aria-pressed", "true");
    for (const name of [/Overview/, /2D Denoising Lab/, /3D CT Explorer/, /Benchmark V2/, /Benchmark 3D/, /Older 2D results/, /Methods & Guide/]) {
      expect(within(nav).getByRole("button", { name })).toBeInTheDocument();      // the labels stay in the page (visually hidden), so the names are kept
    }
    expect(within(await screen.findByTestId("api-status")).getByText(/API ONLINE/)).toBeInTheDocument();
    first.unmount();
    mockApi(baseRoutes());
    const second = render(<App />);                                              // a new visit
    await screen.findByRole("navigation", { name: "Pages" });
    expect(second.container.querySelector(".app-shell")).toHaveClass("sidebar-collapsed");
  });

  it("still works when the browser refuses storage", async () => {
    const user = userEvent.setup();
    mockApi(baseRoutes());
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const view = render(<App />);
    await screen.findByRole("navigation", { name: "Pages" });
    await user.click(screen.getByRole("button", { name: /Collapse navigation/ }));
    expect(view.container.querySelector(".app-shell")).toHaveClass("sidebar-collapsed");
  });
});

describe("3D explorer chart", () => {
  const VOLUME = { filename_count: 2, slices: 2, dimensions_xyz: [4, 4, 2], spacing_xyz_mm: [1, 1, 1], intensity_range: [-1000, 400], middle_slice: PIXEL, note: "Research only.",
    figure: { data: [{ type: "volume" }], layout: { title: { text: "Interactive CT Volume" } } } };

  it("is not handed new layout, data or config objects when the page re-renders for another reason (the health check)", async () => {
    const user = userEvent.setup();
    plotCalls.length = 0;
    const { fetchMock } = mockApi(baseRoutes({ "POST /api/ct/volume": VOLUME }));
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Pages" });
    await user.click(within(nav).getByRole("button", { name: /3D CT Explorer/ }));
    await user.upload(await screen.findByLabelText("Select DICOM files"), [new File(["a"], "a.dcm"), new File(["b"], "b.dcm")]);
    await screen.findByTestId("plot");
    const healthChecks = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/health")).length;
    const before = { checks: healthChecks(), draws: plotCalls.length };
    await waitFor(() => expect(healthChecks()).toBeGreaterThan(before.checks), { timeout: 8000 });         // the page polls the API every 5 s
    await new Promise(resolve => setTimeout(resolve, 300));
    expect(plotCalls.length).toBe(before.draws);                                  // an unchanged answer re-renders nothing
  }, 15000);

  it("keeps the same layout, data and config objects across re-renders of the explorer", async () => {
    const user = userEvent.setup();
    plotCalls.length = 0;
    mockApi(baseRoutes({ "POST /api/ct/volume": VOLUME }));
    const { default: CtExplorer } = await import("../CtExplorer");
    const view = render(<CtExplorer apiState="online" />);
    await user.upload(screen.getByLabelText("Select DICOM files"), [new File(["a"], "a.dcm"), new File(["b"], "b.dcm")]);
    await screen.findByTestId("plot");
    view.rerender(<CtExplorer apiState="online" />);
    view.rerender(<CtExplorer apiState="online" />);
    const [first, ...rest] = plotCalls.slice(-3);
    expect(rest.length).toBe(2);
    for (const call of rest) {
      expect(call.layout).toBe(first.layout);
      expect(call.data).toBe(first.data);
      expect(call.config).toBe(first.config);
    }
    expect(first.layout.font.family).toContain("Inter");                          // drawn in the application's font and its own text colour, not an invalid CSS variable
    expect(first.layout.font.color).toMatch(/^#[0-9a-f]{6}$/i);
  });
});

describe("Overview figures", () => {
  const RUN = { id: "run_a", conditions: ["white_10HU", "white_25HU"], test_slices: [1, 2, 3], generated_at: "2026-10-25T19:31:21+00:00", integrity: { status: "verified", files_checked: 12 } };
  const RUN_3D = { id: "run_b", test_slices: [4, 5], generated_at: "2026-10-26T11:28:06+00:00", noise_model: {}, integrity: { status: "verified", files_checked: 8 } };

  it("computes every KPI from the API and invents nothing when no run is configured", async () => {
    mockApi(baseRoutes());
    render(<App />);
    const strip = await screen.findByLabelText("Key figures from the API");
    await waitFor(() => expect(within(strip).getByText("Recorded runs").closest("article")).toHaveTextContent("None configured on this server"));
    expect(within(strip).getByText("Result files verified").closest("article")).toHaveTextContent("Nothing to verify");
    expect(within(strip).getByText("Result files verified").closest("article")).not.toHaveClass("is-ok");
    expect(within(strip).getByText("API").closest("article")).toHaveTextContent("Online");
  });

  it("adds up the verified files of the recorded runs, and flags a run that differs from its record", async () => {
    mockApi(baseRoutes({ "GET /api/v2/runs": { configured: true, runs: [RUN], caveats: [], slice_comparison_available: false }, "GET /api/3d/runs": { configured: true, runs: [RUN_3D], caveats: [] } }));
    const first = render(<App />);
    const strip = await screen.findByLabelText("Key figures from the API");
    await waitFor(() => expect(within(strip).getByText("Result files verified").closest("article")).toHaveTextContent("20"));          // 12 + 8
    expect(within(strip).getByText("Recorded runs").closest("article")).toHaveTextContent("1 in 2D · 1 in 3D");
    expect(within(strip).getByText("Result files verified").closest("article")).toHaveClass("is-ok");
    first.unmount();
    mockApi(baseRoutes({ "GET /api/v2/runs": { configured: true, runs: [{ ...RUN, integrity: { status: "mismatch", files_checked: 12 } }], caveats: [], slice_comparison_available: false } }));
    render(<App />);
    const strip2 = await screen.findByLabelText("Key figures from the API");
    await waitFor(() => expect(within(strip2).getByText("Result files verified").closest("article")).toHaveClass("is-bad"));
    expect(within(strip2).getByText("Result files verified").closest("article")).toHaveTextContent("1 run(s) differ from their record");
  });

  it("presents the example image as an illustration with its attribution, not as a result", async () => {
    mockApi(baseRoutes());
    render(<App />);
    expect(await screen.findByText(/Example from the lab, not a result/)).toHaveTextContent(/CC BY 3\.0/);
    expect(screen.getByAltText(/Chest CT slice with synthetic Gaussian noise/)).toHaveAttribute("src", "/img/ct-chest-noisy.webp");
    expect(screen.getByAltText(/after a 5 by 5 median filter, shown on the right/)).toHaveAttribute("src", "/img/ct-chest-denoised.webp");
  });
});

// ---- design tokens: the real values in styles.css ------------------------------------------------------------------------------------
const CSS = fs.readFileSync(path.join(process.cwd(), "src", "styles.css"), "utf8");         // the tests are always run from frontend/

function tokens(selectorStart) {
  const start = CSS.indexOf(selectorStart);
  const body = CSS.slice(CSS.indexOf("{", start) + 1, CSS.indexOf("\n}", start));
  const raw = Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]));
  return raw;
}
const LIGHT_RAW = tokens(":root {");
const DARK_RAW = { ...LIGHT_RAW, ...tokens(':root[data-theme="dark"] {') };
const resolve = (raw, name) => { let value = raw[name]; while (value?.startsWith("var(")) value = raw[value.slice(4, -1)]; return value; };
const channel = hex => { const c = parseInt(hex, 16) / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const luminance = hex => 0.2126 * channel(hex.slice(1, 3)) + 0.7152 * channel(hex.slice(3, 5)) + 0.0722 * channel(hex.slice(5, 7));
const contrast = (a, b) => { const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };

describe.each([["light", LIGHT_RAW], ["dark", DARK_RAW]])("design tokens, %s theme", (_theme, raw) => {
  const colour = name => resolve(raw, name);
  const SURFACES = ["--bg", "--surface", "--surface-raised", "--surface-soft"];

  it("gives every text colour at least 4.5:1 on every surface it can sit on (WCAG AA)", () => {
    for (const text of ["--text", "--muted", "--subtle", "--accent", "--success", "--warning-text", "--danger"]) {
      for (const surface of SURFACES) {
        expect(contrast(colour(text), colour(surface)), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keeps the specified secondary text colour readable on white cards, and the button text on its fill", () => {
    expect(contrast(colour("--text-2"), colour("--surface"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(colour("--accent-contrast"), colour("--accent-strong"))).toBeGreaterThanOrEqual(4.5);
  });

  it("draws the border of a form control at 3:1 or more against its surface", () => {
    expect(contrast(colour("--border-strong"), colour("--surface"))).toBeGreaterThanOrEqual(3);
    expect(contrast(colour("--border-strong"), colour("--surface-raised"))).toBeGreaterThanOrEqual(3);
  });

  it("keeps the sidebar text readable on its resting, hover and active backgrounds", () => {
    for (const text of ["--sb-text", "--sb-muted", "--sb-accent"]) {
      for (const surface of ["--sb-bg", "--sb-hover", "--sb-active"]) {
        expect(contrast(colour(text), colour(surface)), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});

describe("design tokens, palette", () => {
  it("uses the specified identity colours", () => {
    expect(LIGHT_RAW["--navy"]).toBe("#10243a");
    expect(LIGHT_RAW["--blue"]).toBe("#176b87");
    expect(LIGHT_RAW["--teal"]).toBe("#16a6a0");
    expect(LIGHT_RAW["--bg"]).toBe("#f4f7fb");
    expect(LIGHT_RAW["--surface"]).toBe("#ffffff");
    expect(LIGHT_RAW["--text"]).toBe("#172b4d");
    expect(LIGHT_RAW["--text-2"]).toBe("#64748b");
    expect(LIGHT_RAW["--border"]).toBe("#e2e8f0");
  });
});
