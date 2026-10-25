import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { CATALOGUE, baseRoutes, mockApi } from "./mockApi";

vi.mock("../plot", () => ({ Plot: () => <div data-testid="plot" /> }));

describe("application shell", () => {
  it("shows the API as connected and lists the methods the API reports", async () => {
    mockApi(baseRoutes());
    render(<App />);
    expect(within(await screen.findByTestId("api-status")).getByText(/API ONLINE/)).toBeInTheDocument();
    expect(await screen.findByText("Denoising methods")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Denoising methods").nextSibling).toHaveTextContent(String(CATALOGUE.methods.length)));
    expect(screen.getByText("None configured")).toBeInTheDocument();
    expect(screen.getByText(/Scope and limits/)).toBeInTheDocument();
    expect(screen.getAllByText(/Not for diagnosis|not for diagnosis|not a diagnostic|Not a diagnostic/i).length).toBeGreaterThan(0);
  });

  it("reports an offline API and offers a retry that reconnects", async () => {
    const user = userEvent.setup();
    const routes = baseRoutes({ "GET /api/health": () => { throw new TypeError("Failed to fetch"); } });
    mockApi(routes);
    render(<App />);
    const status = await screen.findByTestId("api-status");
    await waitFor(() => expect(status).toHaveTextContent("API OFFLINE"));
    expect(status).toHaveTextContent(/Cannot reach the API/);
    routes["GET /api/health"] = { status: "ok" };
    await user.click(within(status).getByRole("button", { name: /check the api connection again/i }));
    await waitFor(() => expect(status).toHaveTextContent("API ONLINE"));
  });

  it("navigates between pages and marks the current one", async () => {
    const user = userEvent.setup();
    mockApi(baseRoutes());
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Pages" });
    expect(within(nav).getByRole("button", { name: /Overview/ })).toHaveAttribute("aria-current", "page");
    await user.click(within(nav).getByRole("button", { name: /2D Denoising Lab/ }));
    expect(await screen.findByRole("heading", { name: "2D Denoising Lab", level: 1 })).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: /2D Denoising Lab/ })).toHaveAttribute("aria-current", "page");
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
    await user.click(screen.getByRole("button", { name: /dark mode/i }));
    expect(document.documentElement.dataset.theme).toBe("dark");
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
