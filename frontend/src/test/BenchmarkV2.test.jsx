import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import BenchmarkV2, { classifyGridChange, summariseGridChanges } from "../BenchmarkV2";
import { baseRoutes, json, mockApi } from "./mockApi";

vi.mock("../plot", () => ({ Plot: props => <div data-testid="plot" data-traces={props.data.length} /> }));

const FAMILIES = ["Mean", "Median", "Gaussian", "FFT ideal", "FFT Gaussian", "FFT Butterworth", "Bilateral", "Non-local means", "Wavelet BayesShrink"];

function run(overrides = {}) {
  return {
    id: "run_a", generated_at: "2026-10-25T18:00:00+00:00", git_commit: "2fe94f6e2396af6ecba4ead9161319b8106328d1",
    source_state: "clean commit", grid_version: "methods", series_label: "series-x", tune_slices: [35, 54, 74], test_slices: [16, 25, 39],
    tune_repeats: 2, test_repeats: 5, conditions: ["white_25HU", "correlated_25HU"], families: FAMILIES,
    integrity: { status: "verified", files_checked: 12, missing: [], mismatched: [], csv_files_not_covered_by_metadata: [] },
    tables: ["test_summary", "selected_parameters", "grid_bracketing"], limitations: "x", comparable_with_historical_results: false,
    ...overrides,
  };
}

function summaryRows() {
  return ["Noisy (no filter)", ...FAMILIES].flatMap(family => ["white_25HU", "correlated_25HU"].flatMap(condition => ["main", "inner"].map(mask => ({
    condition, mask, family, n_slices: 3, RMSE_HU_mean: 20, RMSE_HU_ci_low: 19, RMSE_HU_ci_high: 21,
    RMSE_HU_gain_mean: family === "Noisy (no filter)" ? null : -5, RMSE_HU_gain_ci_low: -6, RMSE_HU_gain_ci_high: -4,
  }))));
}

function routes(runs, extra = {}) {
  return baseRoutes({
    "GET /api/v2/runs": { configured: true, runs, caveats: ["One CT series (one patient)."], slice_comparison_available: false },
    "GET /api/v2/runs/run_a/tables/test_summary": { rows: summaryRows() },
    "GET /api/v2/runs/run_a/tables/selected_parameters": { rows: [
      { condition: "white_25HU", family: "Wavelet BayesShrink", params: JSON.stringify({ sigma_hu: 50, wavelet: "sym4", levels: 3, max_shifts: 3 }), tuning_score: 12.08 },
      { condition: "white_25HU", family: "Mean", params: JSON.stringify({ kernel_size: 3 }), tuning_score: 15.5 },
    ] },
    "GET /api/v2/runs/run_a/tables/grid_bracketing": { rows: [{ condition: "white_25HU", family: "Mean", status: "interior" }] },
    "GET /api/v2/runs/run_a/interpretation": { statements: [{ condition: "white_25HU", text: "On the main mask the lowest mean RMSE_HU is Wavelet BayesShrink." }] },
    ...extra,
  });
}

describe("Benchmark V2 page", () => {
  it("explains that nothing is shown when no run is configured", async () => {
    mockApi(baseRoutes());
    render(<BenchmarkV2 />);
    expect(await screen.findByText("No benchmark V2 run is configured")).toBeInTheDocument();
    expect(screen.getByText(/Nothing is displayed until real results are available/)).toBeInTheDocument();
    expect(screen.queryByTestId("plot")).not.toBeInTheDocument();
  });

  it("reports an unreachable API instead of an empty page", async () => {
    mockApi(baseRoutes({ "GET /api/v2/runs": () => { throw new TypeError("Failed to fetch"); } }));
    render(<BenchmarkV2 />);
    expect(await screen.findByText(/Benchmark results cannot be loaded/)).toBeInTheDocument();
  });

  it("shows the provenance of a recorded run, its verified files and the number of denoisers it covers", async () => {
    mockApi(routes([run()]));
    render(<BenchmarkV2 />);
    expect(await screen.findByText("FILES VERIFIED")).toBeInTheDocument();
    expect(screen.getByText(/9 classical denoisers compared/)).toBeInTheDocument();
    expect(screen.getByText("2fe94f6e2396 — clean commit")).toBeInTheDocument();
    expect(screen.getByText(/12 files match the recorded SHA-256/)).toBeInTheDocument();
    expect(screen.getByText(/Exploratory study: one patient/)).toBeInTheDocument();
    expect(screen.getByText("One CT series (one patient).")).toBeInTheDocument();
    expect(screen.getByText(/Comparable with the historical results/).closest("li")).toHaveTextContent("no");
    await waitFor(() => expect(screen.getAllByTestId("plot").length).toBeGreaterThan(0));
    expect(screen.getByText(/lowest mean RMSE_HU is Wavelet BayesShrink/)).toBeInTheDocument();
  });

  it("describes what the tuned value means for each added denoiser", async () => {
    mockApi(routes([run()]));
    render(<BenchmarkV2 />);
    expect(await screen.findByText(/Wavelet BayesShrink: the tuned value is the noise level the thresholds ASSUME/)).toBeInTheDocument();
    expect(screen.getByText(/Bilateral: the tuned value is the intensity scale/)).toBeInTheDocument();
    expect(screen.getByText(/true noise level is not supplied/)).toBeInTheDocument();
    expect(await screen.findByText("sigma hu 50, wavelet sym4, levels 3, max shifts 3")).toBeInTheDocument();
  });

  it("does not claim the notes of families a run does not contain", async () => {
    mockApi(routes([run({ families: FAMILIES.slice(0, 6), grid_version: "expanded" })]));
    render(<BenchmarkV2 />);
    await screen.findByText("FILES VERIFIED");
    expect(screen.getByText(/6 classical denoisers compared/)).toBeInTheDocument();
    expect(screen.queryByText(/the tuned value is the noise level the thresholds ASSUME/)).not.toBeInTheDocument();
  });

  it("warns when the files of a run no longer match their recorded hashes", async () => {
    const changed = run({ integrity: { status: "mismatch", files_checked: 12, missing: [], mismatched: ["test_summary.csv"], csv_files_not_covered_by_metadata: [] } });
    mockApi(routes([changed]));
    render(<BenchmarkV2 />);
    expect(await screen.findByText("CHECK FILES")).toBeInTheDocument();
    expect(screen.getByText(/do not match the hashes recorded in its metadata/)).toBeInTheDocument();
    expect(screen.getByText(/changed: test_summary.csv/)).toBeInTheDocument();
  });

  it("says why images are missing when no CT series is configured on the server", async () => {
    mockApi(routes([run()]));
    render(<BenchmarkV2 />);
    expect(await screen.findByText(/Image comparison needs the CT series on the server/)).toBeInTheDocument();
  });

  it("shows a table error without hiding the rest of the page", async () => {
    mockApi(routes([run()], { "GET /api/v2/runs/run_a/tables/test_summary": () => json({ detail: "This run does not contain that table." }, 404) }));
    render(<BenchmarkV2 />);
    expect(await screen.findByText("This run does not contain that table.")).toBeInTheDocument();
    expect(screen.getByText("FILES VERIFIED")).toBeInTheDocument();
  });
});

describe("grid comparison helpers", () => {
  const row = (metric, ci_low, ci_high, extra = {}) => ({ metric, mask: "main", ci_low, ci_high, identical_to_old: false, ...extra });

  it("classifies a change using the direction in which each metric improves", () => {
    expect(classifyGridChange(row("RMSE_HU", -2, -1))).toBe("improved");
    expect(classifyGridChange(row("RMSE_HU", 1, 2))).toBe("worse");
    expect(classifyGridChange(row("RMSE_HU", -1, 1))).toBe("unresolved");
    expect(classifyGridChange(row("SSIM_Wang2004", 0.01, 0.02))).toBe("improved");
    expect(classifyGridChange(row("SSIM_Wang2004", -0.02, -0.01))).toBe("worse");
    expect(classifyGridChange(row("PSNR_dB", -1, 1))).toBe("unresolved");
    expect(classifyGridChange(row("RMSE_HU", -2, -1, { identical_to_old: true }))).toBe("identical");
  });

  it("counts the classes per metric and mask", () => {
    const table = summariseGridChanges([row("RMSE_HU", -2, -1), row("RMSE_HU", 1, 2), row("RMSE_HU", -1, 1), row("MAE_HU", -2, -1)]);
    expect(table).toEqual([
      { metric: "RMSE_HU", mask: "main", improved: 1, worse: 1, identical: 0, unresolved: 1 },
      { metric: "MAE_HU", mask: "main", improved: 1, worse: 0, identical: 0, unresolved: 0 },
    ]);
  });
});
