import { useEffect, useState } from "react";

// Colour-blind-safe series colours (Okabe-Ito based). They are used for the same method on every chart of every page.
export const FAMILY_COLORS = {
  "Noisy (no filter)": "#8c99a8", Mean: "#0072B2", Median: "#E69F00", Gaussian: "#009E73", "FFT ideal": "#CC79A7", "FFT Gaussian": "#56B4E9",
  "FFT Butterworth": "#D55E00", Bilateral: "#6a4c93", "Non-local means": "#8c564b", "Wavelet BayesShrink": "#b8a400",
};
export const METHOD_COLORS_3D = {
  "Noisy (no filter)": "#8c99a8", "2D slice-wise Gaussian": "#0072B2", "3D isotropic Gaussian": "#D55E00", "3D anisotropic Gaussian": "#009E73",
};
export const MASK_COLORS = ["#0072B2", "#E69F00", "#009E73"];

/** The application's own font stack, so chart text matches the page. */
export const CHART_FONT = 'Inter, "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif';

const WIDTH_STEP = 60;

/** Re-render when the theme attribute of the page changes (new colours) or the window width changes by a step (titles are wrapped to the width). */
export function useThemeTick() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const observer = new MutationObserver(() => setTick(value => value + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    let bucket = Math.round(window.innerWidth / WIDTH_STEP);
    const onResize = () => {
      const next = Math.round(window.innerWidth / WIDTH_STEP);
      if (next !== bucket) { bucket = next; setTick(value => value + 1); }
    };
    window.addEventListener("resize", onResize);
    return () => { observer.disconnect(); window.removeEventListener("resize", onResize); };
  }, []);
  return tick;
}

/** Width available to a chart, from the window width and the page layout (sidebar above 900 px, page padding, panel padding). */
function chartWidthEstimate() {
  const width = typeof window === "undefined" ? 1200 : window.innerWidth;
  return Math.min(width - (width > 900 ? 248 : 0) - (width > 640 ? 56 : 28) - 36, 1480);
}

/** Break a chart title into lines of at most maxChars characters, at spaces (Plotly does not wrap titles itself). */
export function wrapTitle(text, maxChars) {
  const lines = [];
  let line = "";
  for (const word of String(text).split(" ")) {
    if (line && `${line} ${word}`.length > maxChars) { lines.push(line); line = word; } else line = line ? `${line} ${word}` : word;
  }
  if (line) lines.push(line);
  return lines;
}

/** A layout made by the server, with its title wrapped to the width of the page. Plotly does not wrap titles, so a long one runs off a phone screen. */
export function withWrappedTitle(layout) {
  const title = layout?.title;
  const text = typeof title === "string" ? title : title?.text;
  if (!text) return layout;
  const lines = wrapTitle(text, Math.max(18, Math.floor((chartWidthEstimate() - 24) / 9.5)));     // about 9.5 px per character at Plotly's default title size
  return { ...layout, title: { ...(typeof title === "object" ? title : {}), text: lines.join("<br>") } };
}

/** Text, secondary text and grid colours read from the CSS tokens of the current theme. */
export function themeColors() {
  const style = getComputedStyle(document.documentElement);
  const read = (name, fallback) => (style.getPropertyValue(name) || fallback).trim() || fallback;
  return { text: read("--text", "#14212f"), muted: read("--muted", "#45566a"), grid: read("--border", "#d3dbe6") };
}

/** Height of a chart with a legend below it. On a phone the legend is one column, so it needs one more row of height for each entry beyond five (otherwise it turns into a scroll box). */
export function chartHeight(base, entries) {
  return chartWidthEstimate() < 400 ? base + 19 * Math.max(0, entries - 5) : base;
}

/** A legend pinned to the bottom-left corner of the figure, whatever the figure's height (otherwise it can land on the x-axis title). */
export function legendBelow(entryWidth = 110) {
  return { orientation: "h", xref: "container", x: 0, yref: "container", y: 0, yanchor: "bottom", entrywidth: entryWidth, entrywidthmode: "pixels", font: { size: 10 } };
}

export function baseLayout(title, xTitle, yTitle, extra) {
  const c = themeColors();
  const lines = wrapTitle(title, Math.max(18, Math.floor((chartWidthEstimate() - 24) / 7.2)));
  const margin = { l: 62, r: 14, t: 42, b: 190, ...extra?.margin };    // room for rotated tick labels, the axis title and a legend of up to five rows    // room for rotated tick labels, the axis title and a legend of up to five rows
  margin.t += 17 * (lines.length - 1);                                  // room for the extra title lines
  return {
    title: { text: lines.join("<br>"), font: { size: 13, color: c.text } }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: CHART_FONT, color: c.muted, size: 11 }, legend: legendBelow(),
    xaxis: { title: { text: xTitle, standoff: 14 }, gridcolor: c.grid, automargin: true, tickangle: -30 }, yaxis: { title: { text: yTitle }, gridcolor: c.grid, zeroline: true, zerolinecolor: c.grid },
    autosize: true, ...extra, margin,
  };
}

/** Error-bar arrays of a bar trace from mean and interval limits (missing values draw no bar). */
export function intervalBars(mean, low, high) {
  return {
    type: "data", symmetric: false, thickness: 1, width: 2,
    array: high.map((h, i) => (h == null || mean[i] == null ? 0 : h - mean[i])),
    arrayminus: low.map((l, i) => (l == null || mean[i] == null ? 0 : mean[i] - l)),
  };
}
