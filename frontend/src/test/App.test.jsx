// Component tests of the application shell with fetch MOCKED. They check what the page does with each kind of answer, including how it
// recovers by itself; the same flows against a real backend and a real dashboard server are in e2e/connection.spec.js.
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { CATALOGUE, baseRoutes, json, mockApi } from "./mockApi";

vi.mock("../plot", () => ({ Plot: () => <div data-testid="plot" /> }));

const PROXY_502 = () => json({ code: "api_unreachable", detail: "The dashboard server is running but cannot reach the API at http://127.0.0.1:8000 (ECONNREFUSED). Start the backend (see the README); this page reconnects by itself once it answers." }, 502);
const RECOVERY = { timeout: 7000 };       // the page polls every 2 s while the API is down

describe("application shell", () => {
  it("shows the API as connected and lists the methods the API reports", async () => {
    mockApi(baseRoutes());
    render(<App />);
    expect(within(await screen.findByTestId("api-status")).getByText(/API ONLINE/)).toBeInTheDocument();
    expect(await screen.findByText("Denoising methods")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Denoising methods").nextSibling).toHaveTextContent(String(CATALOGUE.methods.length)));
    expect(screen.getByText("None configured")).toBeInTheDocument();
    expect(screen.getByText(/Scope and limits/)).toBeInTheDocument();
    expect(screen.queryByTestId("api-banner")).not.toBeInTheDocument();
  });

  it("navigates between pages and marks the current one", async () => {
    const user = userEvent.setup();
    mockApi(baseRoutes());
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Pages" });
    expect(within(nav).getByRole("button", { name: /Overview/ })).toHaveAttribute("aria-current", "page");
    await user.click(within(nav).getByRole("button", { name: /2D Denoising Lab/ }));
    expect(await screen.findByRole("heading", { name: "2D Denoising Lab", level: 1 })).toBeInTheDocument();
    await user.click(within(nav).getByRole("button", { name: /Benchmark V2/ }));
    expect(await screen.findByText("No benchmark V2 run is configured")).toBeInTheDocument();
    await user.click(within(nav).getByRole("button", { name: /3D CT Explorer/ }));
    expect(await screen.findByText("No CT volume loaded")).toBeInTheDocument();
    await user.click(within(nav).getByRole("button", { name: /Older 2D results/ }));
    expect(await screen.findByText("Benchmark results are not available")).toBeInTheDocument();
    await user.click(within(nav).getByRole("button", { name: /Methods & Guide/ }));
    expect(await screen.findByRole("heading", { name: "Wavelet (BayesShrink)" })).toBeInTheDocument();
  });

  it("switches and remembers the colour theme", async () => {
    const user = userEvent.setup();
    localStorage.clear();
    mockApi(baseRoutes());
    render(<App />);
    expect(document.documentElement.dataset.theme).toBe("dark");
    await user.click(await screen.findByRole("button", { name: /light mode/i }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("biomed-theme")).toBe("light");
  });

  it("states the benchmark status without inventing results", async () => {
    mockApi(baseRoutes({ "GET /api/results": { available: true, source: "reports/denoising_summary.csv", rows: [{ Noise: "Gaussian", Filter: "Mean", Mean_SSIM: 0.5, Mean_PSNR_dB: 25, Runs_Evaluated: 15 }], noise_types: ["Gaussian"], provenance: { label: "Historical results — provenance not verified", status: "unverified" } } }));
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText("1 rows")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Older 2D results/ }));
    expect(await screen.findByTestId("provenance-banner")).toHaveTextContent("Historical results — provenance not verified");
  });
});

describe("connection problems and recovery", () => {
  it("names the real cause when the dashboard server cannot reach the backend, on every page", async () => {
    const user = userEvent.setup();
    mockApi(baseRoutes({ "GET /api/health": PROXY_502, "GET /api/methods": PROXY_502, "GET /api/v2/runs": PROXY_502, "GET /api/results": PROXY_502, "GET /api/samples": PROXY_502 }));
    render(<App />);
    const banner = await screen.findByTestId("api-banner");
    expect(banner).toHaveTextContent("The API is not reachable");
    expect(banner).toHaveTextContent("cannot reach the API at http://127.0.0.1:8000 (ECONNREFUSED)");
    expect(screen.getByTestId("api-status")).toHaveTextContent(/API OFFLINE.*127\.0\.0\.1:8000/);
    expect(screen.queryByText(/HTTP 500/)).not.toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Pages" });
    await user.click(within(nav).getByRole("button", { name: /Older 2D results/ }));
    expect(await screen.findByText("Results cannot be loaded: the API is not reachable")).toBeInTheDocument();
    expect(screen.queryByText(/Run the benchmark locally/)).not.toBeInTheDocument();         // no misleading "run the benchmark" advice
    await user.click(within(nav).getByRole("button", { name: /Benchmark V2/ }));
    expect(await screen.findByText(/Benchmark results cannot be loaded.*cannot reach the API at http:\/\/127\.0\.0\.1:8000/)).toBeInTheDocument();
    await user.click(within(nav).getByRole("button", { name: /Methods & Guide/ }));
    expect(await screen.findByText(/method descriptions come from the API and could not be loaded/)).toBeInTheDocument();
    expect(screen.getAllByText(/cannot reach the API at http:\/\/127\.0\.0\.1:8000/).length).toBeGreaterThan(1);
    await user.click(within(nav).getByRole("button", { name: /3D CT Explorer/ }));
    expect(screen.getByLabelText("Select DICOM files")).toBeDisabled();
  });

  it("says the DASHBOARD server is down (not the API) when the page's own server stops answering", async () => {
    const gone = () => { throw new TypeError("Failed to fetch"); };
    mockApi(baseRoutes({ "GET /api/health": gone, "HEAD /": gone }));
    render(<App />);
    const banner = await screen.findByTestId("api-banner");
    expect(banner).toHaveTextContent("The dashboard server is not responding");
    expect(banner).toHaveTextContent(/npm run dev.*start it again, then reload/);
    expect(banner).not.toHaveTextContent("Cannot reach the API");
  });

  it("recovers by itself when the API comes back, and the pages that failed load their data without a reload", async () => {
    const user = userEvent.setup();
    const down = { "GET /api/health": PROXY_502, "GET /api/methods": PROXY_502, "GET /api/results": PROXY_502 };
    const up = baseRoutes();
    const routes = { ...up, ...down };
    mockApi(routes);
    render(<App />);
    expect(await screen.findByTestId("api-banner")).toBeInTheDocument();
    await user.click(within(screen.getByRole("navigation", { name: "Pages" })).getByRole("button", { name: /Methods & Guide/ }));
    expect(await screen.findByText(/method descriptions come from the API and could not be loaded/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Wavelet (BayesShrink)" })).not.toBeInTheDocument();
    Object.keys(down).forEach(key => { routes[key] = up[key]; });                       // the backend starts
    await waitFor(() => expect(screen.queryByTestId("api-banner")).not.toBeInTheDocument(), RECOVERY);
    expect(await screen.findByRole("heading", { name: "Wavelet (BayesShrink)" }, RECOVERY)).toBeInTheDocument();
    expect(screen.getByTestId("api-status")).toHaveTextContent("API ONLINE");
  }, 30000);

  it("notices when the API stops while the page is open and then recovers, keeping the user's page", async () => {
    const user = userEvent.setup();
    const up = baseRoutes();
    const routes = { ...up };
    mockApi(routes);
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("api-status")).toHaveTextContent("API ONLINE"));
    await user.click(within(screen.getByRole("navigation", { name: "Pages" })).getByRole("button", { name: /2D Denoising Lab/ }));
    await screen.findByRole("checkbox", { name: "Mean", exact: true });
    routes["GET /api/health"] = PROXY_502;
    await waitFor(() => expect(screen.getByTestId("api-banner")).toBeInTheDocument(), { timeout: 8000 });
    expect(screen.getByRole("checkbox", { name: "Mean", exact: true })).toBeInTheDocument();     // the lab is still there, only a banner was added
    routes["GET /api/health"] = up["GET /api/health"];
    await waitFor(() => expect(screen.queryByTestId("api-banner")).not.toBeInTheDocument(), RECOVERY);
    expect(screen.getByRole("heading", { name: "2D Denoising Lab", level: 1 })).toBeInTheDocument();
  }, 30000);

  it("offers an immediate retry", async () => {
    const user = userEvent.setup();
    const routes = baseRoutes({ "GET /api/health": PROXY_502 });
    mockApi(routes);
    render(<App />);
    const banner = await screen.findByTestId("api-banner");
    routes["GET /api/health"] = baseRoutes()["GET /api/health"];
    await user.click(within(banner).getByRole("button", { name: /retry now/i }));
    await waitFor(() => expect(screen.queryByTestId("api-banner")).not.toBeInTheDocument());
  });

  it("warns, without blocking, when part of the API is unavailable in this environment", async () => {
    mockApi(baseRoutes({ "GET /api/health": { status: "ok", service: "Biomedical Imaging API", version: "1.0.0", unavailable_methods: [{ id: "wavelet" }],
      problems: ["Wavelet (BayesShrink): Wavelet (BayesShrink) needs the Python package PyWavelets, which is not installed in this environment."] } }));
    render(<App />);
    const notice = await screen.findByTestId("api-problems");
    expect(notice).toHaveTextContent("Part of the API is unavailable");
    expect(notice).toHaveTextContent("needs the Python package PyWavelets");
    expect(screen.queryByTestId("api-banner")).not.toBeInTheDocument();
    expect(screen.getByTestId("api-status")).toHaveTextContent("API ONLINE");
  });
});
