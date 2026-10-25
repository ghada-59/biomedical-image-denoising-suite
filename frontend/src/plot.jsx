import { Suspense, lazy } from "react";

// Plotly is about 4.5 MB. It is loaded only when a page that draws a chart is opened, so the first screen stays light.
const LazyPlot = lazy(async () => {
  const [{ default: createPlotlyComponent }, { default: Plotly }] = await Promise.all([
    import("react-plotly.js/factory"),
    import("plotly.js-dist-min"),
  ]);
  return { default: createPlotlyComponent(Plotly) };
});

export function Plot(props) {
  const height = props.style?.height ?? 360;
  return (
    <Suspense fallback={<div className="chart-loading" role="status" style={{ minHeight: height }}>Loading chart…</div>}>
      <LazyPlot {...props} />
    </Suspense>
  );
}
