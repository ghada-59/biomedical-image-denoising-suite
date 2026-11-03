import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import Results, { filterLabel } from "../Results";

// Rows shaped like backend/reports/denoising_summary.csv: a spatial and a frequency-domain table, each with its own unfiltered baseline.
const row = (Domain, Filter, Mean_SSIM, Mean_PSNR_dB) => ({ Noise: "Gaussian", "Noise Parameter": "variance=0.02", Domain, Filter, Runs_Evaluated: 15, Mean_SSIM, Mean_PSNR_dB });
const ROWS = [
  row("Frequency", "Noisy (Unfiltered)", 0.1702, 18.39), row("Frequency", "Gauss", 0.6499, 23.09), row("Frequency", "Ideal", 0.5473, 22.05),
  row("Spatial", "Noisy (Unfiltered)", 0.1702, 18.39), row("Spatial", "Gaussian", 0.5365, 25.32), row("Spatial", "Median", 0.6074, 27.88),
];
const benchmark = rows => ({ available: true, source: "reports/denoising_summary.csv", provenance: { label: "Historical results" }, noise_types: ["Gaussian"], rows });
const barLabels = container => [...container.querySelectorAll(".bar-label")].map(element => element.textContent);

describe("older 2D results", () => {
  it("says which domain each bar belongs to, so two baselines and 'Gauss' versus 'Gaussian' cannot be confused", () => {
    const { container } = render(<Results benchmark={benchmark(ROWS)} />);
    const labels = barLabels(container);
    expect(labels).toHaveLength(12);                                                       // 6 filters in the SSIM chart and 6 in the PSNR chart
    for (const label of ["Noisy (Unfiltered) (frequency)", "Noisy (Unfiltered) (spatial)", "Gauss (frequency)", "Gaussian (spatial)", "Median (spatial)", "Ideal (frequency)"]) {
      expect(labels.filter(text => text === label), label).toHaveLength(2);                // one bar per chart
    }
    expect(labels).not.toContain("Noisy (Unfiltered)");                                    // no ambiguous bare label is left
  });

  it("names the domain of the filter with the highest mean SSIM", () => {
    render(<Results benchmark={benchmark(ROWS)} />);
    expect(screen.getByText("Highest mean SSIM").closest("article")).toHaveTextContent("Gauss (frequency)");
  });

  it("says that an undocumented file may come from the earlier 0.10 cutoff, and drops that note for a documented run", () => {
    const { unmount } = render(<Results benchmark={benchmark(ROWS)} />);
    expect(screen.getByTestId("cutoff-note")).toHaveTextContent(/cutoff of 0\.10.*default to 0\.15/);
    unmount();
    const documented = { ...benchmark(ROWS), provenance: { status: "documented_run", label: "Documented run" } };
    render(<Results benchmark={documented} />);
    expect(screen.queryByTestId("cutoff-note")).toBeNull();
  });

  it("uses unique React keys when rows have no domain", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const withoutDomain = ROWS.map(({ Domain: _domain, ...rest }) => rest);
      render(<Results benchmark={benchmark(withoutDomain)} />);
      expect(consoleError).not.toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
  });

  it("keeps the plain filter name when a row has no domain", () => {
    const withoutDomain = ROWS.map(({ Domain: _domain, ...rest }) => rest);
    const { container } = render(<Results benchmark={benchmark(withoutDomain)} />);
    expect(barLabels(container)).toContain("Median");
    expect(filterLabel({ Filter: "Median" })).toBe("Median");
    expect(filterLabel({ Filter: "Median", Domain: "Spatial" })).toBe("Median (spatial)");
  });
});
