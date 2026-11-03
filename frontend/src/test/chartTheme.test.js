import { describe, expect, it } from "vitest";
import { baseLayout, chartHeight, intervalBars, legendBelow, withWrappedTitle, wrapTitle } from "../chartTheme";

describe("wrapTitle", () => {
  it("keeps a short title on one line", () => {
    expect(wrapTitle("RMSE (HU)", 40)).toEqual(["RMSE (HU)"]);
  });

  it("breaks at spaces without losing or splitting words", () => {
    const text = "Structure change versus residual noise — 10 HU noise, tuning slices";
    const lines = wrapTitle(text, 30);
    expect(lines.join(" ")).toBe(text);
    expect(lines.length).toBeGreaterThan(1);
    expect(lines.every(line => line.length <= 30)).toBe(true);
  });

  it("leaves a single word longer than the limit whole", () => {
    expect(wrapTitle("abcdefghijklmnop qr", 5)).toEqual(["abcdefghijklmnop", "qr"]);
  });
});

describe("baseLayout", () => {
  it("wraps a long title on a phone and makes room for the extra lines", () => {
    window.innerWidth = 390;
    const long = "Change of RMSE_HU versus the unfiltered noisy image — white 25 HU";
    const layout = baseLayout(long, "x", "y");
    const lines = layout.title.text.split("<br>");
    expect(lines.length).toBeGreaterThan(1);
    expect(lines.join(" ")).toBe(long);
    expect(layout.margin.t).toBe(42 + 17 * (lines.length - 1));
  });

  it("applies the extra margin of a chart and still adds room for the title", () => {
    window.innerWidth = 390;
    const layout = baseLayout("A fairly long chart title that needs several lines on a phone", "x", "y", { margin: { l: 70, r: 14, t: 42, b: 70 } });
    expect(layout.margin.l).toBe(70);
    expect(layout.margin.b).toBe(70);
    expect(layout.margin.t).toBeGreaterThan(42);
  });

  it("does not wrap a title that fits on a wide screen", () => {
    window.innerWidth = 1360;
    const layout = baseLayout("Anisotropic 3D minus slice-wise 2D, RMSE_HU (principal mask)", "x", "y");
    expect(layout.title.text).not.toContain("<br>");
    expect(layout.margin.t).toBe(42);
  });
});

describe("legend placement", () => {
  it("pins the legend to the bottom of the figure so it cannot land on the x-axis title", () => {
    window.innerWidth = 1360;
    const { legend, margin } = baseLayout("RMSE (HU)", "Noise condition (synthetic)", "RMSE (HU)");
    expect(legend).toMatchObject({ orientation: "h", xref: "container", yref: "container", y: 0, yanchor: "bottom" });
    expect(margin.b).toBeGreaterThanOrEqual(190);                                   // rotated tick labels, the axis title and up to five legend rows
  });

  it("lets a chart widen the legend entries", () => {
    expect(legendBelow().entrywidth).toBe(110);
    expect(legendBelow(150)).toMatchObject({ entrywidth: 150, entrywidthmode: "pixels", yref: "container" });
  });
});

describe("chartHeight", () => {
  it("keeps the height on a wide screen", () => {
    window.innerWidth = 1360;
    expect(chartHeight(440, 10)).toBe(440);
  });

  it("adds a row of height per legend entry beyond five on a phone, where the legend is one column", () => {
    window.innerWidth = 390;
    expect(chartHeight(440, 10)).toBe(440 + 19 * 5);
    expect(chartHeight(380, 12)).toBe(380 + 19 * 7);
    expect(chartHeight(440, 4)).toBe(440);
  });
});

describe("withWrappedTitle", () => {
  const serverTitle = "Interactive CT Volume — 512 × 512 × 100 voxels";           // the title made by the backend for the 3D explorer

  it("wraps the long title of a server-made layout on a phone and keeps every other setting", () => {
    window.innerWidth = 390;
    const layout = { title: { text: serverTitle, x: 0.1 }, scene: { aspectmode: "data" }, margin: { t: 80 } };
    const wrapped = withWrappedTitle(layout);
    const lines = wrapped.title.text.split("<br>");
    expect(lines.length).toBeGreaterThan(1);
    expect(lines.join(" ")).toBe(serverTitle);
    expect(lines.every(line => line.length <= 31)).toBe(true);
    expect(wrapped.title.x).toBe(0.1);
    expect(wrapped.scene).toBe(layout.scene);
    expect(wrapped.margin).toBe(layout.margin);
    expect(layout.title.text).toBe(serverTitle);                                   // the layout received from the API is not modified
  });

  it("accepts a title given as a plain string", () => {
    window.innerWidth = 390;
    expect(withWrappedTitle({ title: serverTitle }).title.text).toContain("<br>");
  });

  it("leaves a title that fits, and a layout without a title, as they are", () => {
    window.innerWidth = 1360;
    expect(withWrappedTitle({ title: { text: serverTitle } }).title.text).toBe(serverTitle);
    const untitled = { scene: {} };
    expect(withWrappedTitle(untitled)).toBe(untitled);
    expect(withWrappedTitle(undefined)).toBeUndefined();
  });
});

describe("intervalBars", () => {
  it("draws no bar for missing values and distances from the mean otherwise", () => {
    const bars = intervalBars([1, null, 3], [0.5, 0, null], [2, 1, 4]);
    expect(bars.array).toEqual([1, 0, 1]);
    expect(bars.arrayminus).toEqual([0.5, 0, 0]);
  });
});
