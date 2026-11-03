// Component tests of the Benchmark 3D page with fetch MOCKED. The numbers below are SYNTHETIC fixtures that only exercise the page;
// the same page against the real recorded run and the real API is in e2e/dashboard.spec.js.
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Benchmark3D from "../Benchmark3D";
import { baseRoutes, mockApi } from "./mockApi";

vi.mock("../plot", () => ({ Plot: props => <div data-testid="plot" data-traces={props.data.length} data-title={props.layout?.title?.text} data-ytitle={props.layout?.yaxis?.title?.text} /> }));

const METHODS = ["2D slice-wise Gaussian", "3D isotropic Gaussian", "3D anisotropic Gaussian"];

function run(overrides = {}) {
  return {
    id: "run_white", benchmark: "3D smoothing: slice-wise versus volumetric", generated_at: "2026-10-26T11:28:06+00:00", git_commit: "103d359ac1b1af89cdde5d552a800fd5d98ffaf2+dirty",
    source_state: "uncommitted working tree (dirty); the SHA-256 of the source files identifies the code", series_label: "series-x", volume_shape_zyx: [100, 512, 512], voxel_spacing_xyz_mm: [0.54, 0.54, 3.0],
    tune_slices: [35, 54, 74], test_slices: [16, 21, 25, 45, 64, 84, 88, 93], tune_repeats: 2, test_repeats: 5, noise_sigmas_hu: [25, 50], primary_mask: "main", selection_criterion: "RMSE_HU",
    bootstrap_seed: 12345, n_boot: 10000, noise_model: { kind: "white, independent between voxels and between slices", adjacent_slice_correlation: 0, note: "More favourable to smoothing across slices than the real noise." },
    methods: METHODS, integrity: { status: "verified", files_checked: 8, missing: [], mismatched: [], files_not_covered_by_metadata: [] }, tables: ["test_summary", "selected_parameters", "tuning_grid"],
    figures: ["test_rmse.png", "tradeoff_curves.png"], source_files: ["benchmark_3d.py", "benchmark_v2.py"], limitations: "Synthetic white noise (fixture text).", status: "recorded run; exploratory, one patient (not an independent validation)",
    comparable_with_historical_results: false, ...overrides,
  };
}

function summaryRows() {
  return ["white_25HU", "white_50HU"].flatMap(condition => ["main", "inner", "soft"].flatMap(mask => ["Noisy (no filter)", ...METHODS].map(method => ({
    condition, mask, method, n_slices: 8, RMSE_HU_mean: 20, RMSE_HU_ci_low: 19, RMSE_HU_ci_high: 21, blur_rmse_hu_mean: 5, blur_rmse_hu_ci_low: 4, blur_rmse_hu_ci_high: 6,
    PSNR_dB_mean: mask === "soft" ? null : 30, PSNR_dB_ci_low: null, PSNR_dB_ci_high: null,
  }))));
}

const STATEMENTS = [
  { condition: "white_25HU", kind: "identical", text: "At 25 HU: identical outputs (fixture).", rmse_hu: { [METHODS[0]]: 13.8, [METHODS[1]]: 13.8, [METHODS[2]]: 13.8 }, paired_difference_hu: 0, ci_low: 0, ci_high: 0, slices_lower: 0, slices_higher: 0 },
  { condition: "white_50HU", kind: "lower", text: "At 50 HU: anisotropic 3D minus slice-wise 2D is -0.11 HU, lower in 6, higher in 2 of the slices (fixture).", rmse_hu: { [METHODS[0]]: 21.65, [METHODS[1]]: 21.65, [METHODS[2]]: 21.55 }, paired_difference_hu: -0.11, ci_low: -0.18, ci_high: -0.04, slices_lower: 6, slices_higher: 2 },
];

function routes(runs, extra = {}) {
  const table = (name, rows) => ({ [`GET /api/3d/runs/${runs[0]?.id}/tables/${name}`]: { rows } });
  return baseRoutes({
    "GET /api/3d/runs": { configured: true, runs, caveats: ["One CT series (one patient); slices of one scan are not independent samples."] },
    ...table("test_summary", summaryRows()),
    ...table("selected_parameters", [
      { condition: "white_50HU", method: METHODS[0], params: JSON.stringify({ sigma_xy_mm: 0.4, sigma_z_mm: 0 }) },
      { condition: "white_50HU", method: METHODS[2], params: JSON.stringify({ sigma_xy_mm: 0.4, sigma_z_mm: 1 }) },
    ]),
    "GET /api/3d/runs/run_white/tables/tuning_grid?condition=white_50HU": { rows: [
      { condition: "white_50HU", method: METHODS[0], params: JSON.stringify({ sigma_xy_mm: 0.4, sigma_z_mm: 0 }), blur_rmse_hu_main: 9.9, residual_noise_hu_main: 19.2, blur_rmse_hu_soft: 4, residual_noise_hu_soft: 19 },
    ] },
    ...runs.reduce((all, r) => ({ ...all, [`GET /api/3d/runs/${r.id}/interpretation`]: { run: r.id, statements: STATEMENTS, caveats: [] } }), {}),
    ...extra,
  });
}

describe("Benchmark 3D page", () => {
  it("explains that nothing is shown when no run is configured", async () => {
    mockApi(baseRoutes());
    render(<Benchmark3D />);
    expect(await screen.findByText("No Benchmark 3D run is configured")).toBeInTheDocument();
    expect(screen.getByText(/Nothing is displayed until real results are available/)).toBeInTheDocument();
    expect(screen.queryByTestId("plot")).not.toBeInTheDocument();
  });

  it("reports an unreachable API instead of an empty page", async () => {
    mockApi(baseRoutes({ "GET /api/3d/runs": () => { throw new TypeError("Failed to fetch"); } }));
    render(<Benchmark3D />);
    expect(await screen.findByText(/Benchmark 3D results cannot be loaded/)).toBeInTheDocument();
  });

  it("shows the provenance of a recorded run: noise model, source state, verified files and the scope warning", async () => {
    mockApi(routes([run()]));
    render(<Benchmark3D />);
    expect(await screen.findByText("FILES VERIFIED")).toBeInTheDocument();
    expect(screen.getByText(/white, independent between voxels and between slices/)).toBeInTheDocument();
    expect(screen.getByText(/103d359ac1b1 — uncommitted working tree \(dirty\)/)).toBeInTheDocument();
    expect(screen.getByText(/8 files match the recorded SHA-256/)).toBeInTheDocument();
    expect(screen.getByText(/Exploratory study: one patient, 8 held-out slices/)).toBeInTheDocument();
    expect(screen.getByText(/slices of one scan are not independent samples/)).toBeInTheDocument();
    expect(screen.getByText(/Comparable with the historical results/).closest("li")).toHaveTextContent("no");
    expect(screen.getByText(/0.54 x 0.54 x 3.00 mm/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTestId("plot").length).toBeGreaterThan(1));
  });

  it("warns when the files of a run no longer match their recorded hashes", async () => {
    mockApi(routes([run({ integrity: { status: "mismatch", files_checked: 8, missing: [], mismatched: ["test_summary.csv"], files_not_covered_by_metadata: [] } })]));
    render(<Benchmark3D />);
    expect(await screen.findByText("CHECK FILES")).toBeInTheDocument();
    expect(screen.getByText(/do not match the hashes recorded in its metadata/)).toBeInTheDocument();
    expect(screen.getByText(/changed: test_summary.csv/)).toBeInTheDocument();
  });

  it("states what the data say, including the mixed sign of the small gain, from the API's computed statements", async () => {
    mockApi(routes([run()]));
    render(<Benchmark3D />);
    expect(await screen.findByText(/lower in 6, higher in 2 of the slices/)).toBeInTheDocument();
    expect(screen.getByText(/identical outputs/)).toBeInTheDocument();
    expect(screen.getByText(/Statements concern RMSE_HU on the principal mask of this series only/)).toBeInTheDocument();
  });

  it("converts the selected widths from millimetres to pixels and to slices with the recorded voxel spacing", async () => {
    mockApi(routes([run()]));
    render(<Benchmark3D />);
    const table = await screen.findByRole("region", { name: "Selected parameters" });
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBe(3));
    const aniso = within(table).getByText("3D anisotropic Gaussian").closest("tr");
    const cells = within(aniso).getAllByRole("cell").map(c => c.textContent);
    expect(cells).toEqual(["50 HU", "3D anisotropic Gaussian", "0.40", "0.74", "1.00", "0.33"]);      // 0.4 mm / 0.54 mm = 0.74 px; 1 mm / 3 mm = 0.33 slice
  });

  it("changes the metric of the chart and offers the CSV of the table", async () => {
    const user = userEvent.setup();
    mockApi(routes([run()]));
    render(<Benchmark3D />);
    await screen.findByText("FILES VERIFIED");
    await waitFor(() => expect(screen.getAllByTestId("plot").some(p => p.dataset.title === "RMSE (HU) on the held-out slices")).toBe(true));
    await user.selectOptions(screen.getByLabelText("Metric"), "residual_noise_hu");
    await waitFor(() => expect(screen.getAllByTestId("plot").some(p => p.dataset.title === "Residual noise (HU) on the held-out slices")).toBe(true));
    expect(screen.getByRole("link", { name: /Download test_summary.csv/ })).toHaveAttribute("href", expect.stringContaining("/api/3d/runs/run_white/tables/test_summary?format=csv"));
  });

  it("compares runs side by side when several are recorded", async () => {
    const correlated = run({ id: "run_corr", noise_model: { kind: "white inside a slice, correlated with the adjacent slice", adjacent_slice_correlation: 0.3 } });
    mockApi(routes([run(), correlated]));
    render(<Benchmark3D />);
    const table = await screen.findByRole("region", { name: "Runs compared" });
    expect(within(table).getAllByText("run_corr").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("correlation 0.3").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("independent").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("-0.11 [-0.18, -0.04]").length).toBe(2);
  });

  it("shows the recorded figures from the API and the command that reproduces the run", async () => {
    mockApi(routes([run()]));
    render(<Benchmark3D />);
    await screen.findByText("FILES VERIFIED");
    const images = screen.getAllByRole("img");
    expect(images.map(i => i.getAttribute("src"))).toEqual(expect.arrayContaining(["/api/3d/runs/run_white/figures/test_rmse.png", "/api/3d/runs/run_white/figures/tradeoff_curves.png"]));
    expect(screen.getByText(/python benchmark_3d.py --dicom-series/)).toBeInTheDocument();
    expect(screen.queryByText(/benchmark_3d_correlated/)).not.toBeInTheDocument();
  });
});
