import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = name => path.join(here, "fixtures", name);

/** Collect everything the page prints as an error, so a passing flow cannot hide a broken console. */
function watchConsole(page) {
  const problems = [];
  page.on("pageerror", error => problems.push(`pageerror: ${error.message}`));
  page.on("console", message => {
    if (message.type() === "error") problems.push(`console.error: ${message.text()}`);
  });
  page.on("response", response => {
    if (response.status() >= 400) problems.push(`HTTP ${response.status()} ${response.url()}`);
  });
  return problems;
}

async function openLab(page) {
  await page.goto("/");
  await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
  await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: /2D Denoising Lab/ }).click();
  await expect(page.getByRole("checkbox", { name: "Mean", exact: true })).toBeVisible();
}

test.describe("2D lab against the real backend", () => {
  test("shows the method catalogue served by the API", async ({ page }) => {
    const problems = watchConsole(page);
    await openLab(page);
    await expect(page.getByRole("checkbox")).toHaveCount(9);
    for (const name of ["Mean", "Median", "Gaussian", "Frequency ideal", "Frequency Gaussian", "Frequency Butterworth"]) {
      await expect(page.getByRole("checkbox", { name, exact: true })).toBeChecked();
    }
    await expect(page.getByRole("checkbox", { name: /Non-local means/ })).not.toBeChecked();
    await expect(page.getByTestId("lab-run")).toBeDisabled();
    await expect(page.getByText("Start with an image")).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("denoises a bundled sample with all nine methods and reports real measurements", async ({ page }) => {
    const problems = watchConsole(page);
    await openLab(page);
    await page.getByLabel(/bundled sample/i).selectOption("cell_phase");
    await expect(page.getByAltText(/Preview of cell_phase.png/)).toBeVisible();
    await expect(page.getByText(/not tissue and not a radiological image/)).toBeVisible();
    for (const name of [/Bilateral/, /Non-local means/, /Wavelet/]) await page.getByRole("checkbox", { name }).check();
    await page.getByTestId("lab-run").click();
    const table = page.getByTestId("lab-results-table");
    await expect(table).toBeVisible();
    const rows = table.locator("tbody tr");
    await expect(rows).toHaveCount(10);
    const names = await rows.locator("th").allTextContents();
    expect(names).toEqual(["Noisy input", "Mean", "Median", "Gaussian", "Frequency ideal", "Frequency Gaussian", "Frequency Butterworth",
      "Bilateral", "Non-local means", "Wavelet (BayesShrink)"]);
    for (let i = 0; i < 10; i++) {
      const cells = await rows.nth(i).locator("td").allTextContents();
      const [psnr, ssim, ms] = cells;
      expect(Number(psnr)).toBeGreaterThan(5);
      expect(Number(ssim)).toBeGreaterThanOrEqual(-1);
      expect(Number(ssim)).toBeLessThanOrEqual(1);
      expect(Number(ms)).toBeGreaterThanOrEqual(0);
    }
    await expect(rows.nth(8)).toContainText("h 0.15, patch size 5, patch distance 6");
    await expect(rows.nth(9)).toContainText("assumed noise sd 0.15, wavelet sym4, levels 3");
    await expect(page.getByText(/LIVE RUN · \d+ ms TOTAL/)).toBeVisible();
    // every output image was decoded by the browser
    const decoded = await page.locator(".output-card img").evaluateAll(images => images.map(img => img.complete && img.naturalWidth > 0));
    expect(decoded).toHaveLength(11);                                  // original + noisy + nine methods
    expect(decoded.every(Boolean)).toBe(true);
    expect(problems).toEqual([]);
  });

  test("is reproducible: the same settings give the same scores", async ({ page }) => {
    await openLab(page);
    await page.getByLabel("Upload an image or DICOM slice").setInputFiles(fixture("phantom.png"));
    await expect(page.getByAltText(/Preview of phantom.png/)).toBeVisible();
    const read = async () => (await page.getByTestId("lab-results-table").locator("tbody tr").locator("td:nth-child(2), td:nth-child(3)").allTextContents());
    await page.getByTestId("lab-run").click();
    await expect(page.getByTestId("lab-results-table")).toBeVisible();
    const first = await read();
    await page.getByLabel("Random seed").fill("42");
    await page.getByTestId("lab-run").click();
    await expect(page.getByTestId("lab-results-table")).toBeVisible();
    expect(await read()).toEqual(first);
    await page.getByLabel("Random seed").fill("43");
    await page.getByTestId("lab-run").click();
    await expect(page.getByTestId("lab-results-table")).toBeVisible();
    expect(await read()).not.toEqual(first);
  });

  test("the comparison divider changes what is visible", async ({ page }) => {
    await openLab(page);
    await page.getByLabel("Upload an image or DICOM slice").setInputFiles(fixture("phantom.png"));
    await page.getByTestId("lab-run").click();
    const slider = page.getByTestId("compare-slider");
    await expect(slider).toBeVisible();
    const top = page.locator(".compare-top");
    await expect(top).toHaveCSS("clip-path", /inset\(0(px)? 50%/);
    await slider.fill("10");
    await expect(top).toHaveCSS("clip-path", /inset\(0(px)? 90%/);
    await page.getByLabel("Right").selectOption("Median");
    await expect(page.getByAltText(/Median, shown on the right/)).toBeVisible();
  });

  test("refuses a corrupt file with the server's message and keeps the run disabled", async ({ page }) => {
    await openLab(page);
    await page.getByLabel("Upload an image or DICOM slice").setInputFiles(fixture("corrupt.png"));
    await expect(page.getByRole("alert")).toContainText("Could not read corrupt.png");
    await expect(page.getByTestId("lab-run")).toBeDisabled();
  });

  test("blocks the slower methods on an image over their pixel limit but still processes the classical filters", async ({ page }) => {
    await openLab(page);
    await page.getByLabel("Upload an image or DICOM slice").setInputFiles(fixture("large_gradient.png"));
    await expect(page.getByText("1200 × 1000 px")).toBeVisible();
    await page.getByRole("checkbox", { name: /Non-local means/ }).check();
    await expect(page.getByRole("alert")).toContainText("limited to 1,048,576 pixels; this image has 1,200,000");
    await expect(page.getByTestId("lab-run")).toBeDisabled();
    await page.getByRole("checkbox", { name: /Non-local means/ }).uncheck();
    await page.getByRole("checkbox", { name: "Median", exact: true }).uncheck();      // keep the run quick
    await page.getByTestId("lab-run").click();
    await expect(page.getByTestId("lab-results-table")).toBeVisible();
  });

  test("shows a server refusal as readable text, not a crash", async ({ page }) => {
    await openLab(page);
    await page.getByLabel("Upload an image or DICOM slice").setInputFiles(fixture("phantom.png"));
    await expect(page.getByTestId("lab-run")).toBeEnabled();
    await page.route("**/api/denoise", route => route.fulfill({ status: 503, contentType: "application/json", headers: { "Retry-After": "5" },
      body: JSON.stringify({ detail: "The server is busy with other images. Try again in a few seconds." }) }));
    await page.getByTestId("lab-run").click();
    await expect(page.getByTestId("lab-error")).toContainText("busy with other images");
    await expect(page.getByTestId("lab-run")).toBeEnabled();
    await page.unroute("**/api/denoise");
    await page.getByTestId("lab-run").click();
    await expect(page.getByTestId("lab-results-table")).toBeVisible();
  });
});

test.describe("connection states", () => {
  // Here only the browser's /api requests fail while the page's own server still answers, so the page cannot name a cause beyond
  // "the request failed". The named causes (API down behind a running dashboard server, dashboard server down) are
  // covered with the real services in connection.spec.js.
  test("reports API requests that fail, and reloads the data by itself once they work again", async ({ page }) => {
    await page.route("**/api/**", route => route.abort("connectionrefused"));
    await page.goto("/");
    await expect(page.getByTestId("api-status")).toContainText("API OFFLINE");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: /2D Denoising Lab/ }).click();
    await expect(page.getByTestId("api-banner")).toContainText("failed before the server answered");
    await expect(page.getByTestId("lab-run")).toBeDisabled();
    await page.unroute("**/api/**");
    await page.getByRole("button", { name: /check the api connection again/i }).click();
    await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
    await expect(page.getByRole("checkbox", { name: "Mean", exact: true })).toBeVisible();   // no Retry press is needed
    await expect(page.getByTestId("api-banner")).toHaveCount(0);
  });

  test("Benchmark V2 says plainly that no run is configured", async ({ page }) => {
    test.skip(Boolean(process.env.E2E_BENCHMARK_RUN_DIR), "a run is configured for this session");
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: /Benchmark V2/ }).click();
    await expect(page.getByText("No benchmark V2 run is configured")).toBeVisible();
    await expect(page.locator(".js-plotly-plot")).toHaveCount(0);
  });

  test("Benchmark V2 shows a recorded run with verified files and charts", async ({ page }) => {
    test.skip(!process.env.E2E_BENCHMARK_RUN_DIR, "set E2E_BENCHMARK_RUN_DIR to a Benchmark V2 run directory");
    const problems = watchConsole(page);
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: /Benchmark V2/ }).click();
    await expect(page.getByText("FILES VERIFIED")).toBeVisible();
    await expect(page.locator(".js-plotly-plot").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/classical denoisers compared/)).toBeVisible();
    expect(problems).toEqual([]);
  });
});

test.describe("Benchmark 3D against the recorded run that ships with the repository", () => {
  test("shows the verified run, its statements computed from the tables, the recorded figures and the charts", async ({ page }) => {
    const problems = watchConsole(page);
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: /Benchmark 3D/ }).click();
    await expect(page.getByRole("heading", { name: "Benchmark 3D", level: 1 })).toBeVisible();
    await expect(page.getByText("FILES VERIFIED")).toBeVisible();
    await expect(page.getByText(/8 files match the recorded SHA-256/)).toBeVisible();
    await expect(page.getByText(/white, independent between voxels and between slices/)).toBeVisible();
    await expect(page.getByText(/lower in 6, higher in 2 of the slices/)).toBeVisible();              // the recorded mixed-sign gain at 50 HU, counted from test_per_slice.csv
    await expect(page.locator(".js-plotly-plot").first()).toBeVisible({ timeout: 30_000 });
    const figure = page.getByRole("img", { name: /structure change against residual noise/i });
    await figure.scrollIntoViewIfNeeded();                                                             // the image is loaded lazily, when it comes into view
    await expect(figure).toBeVisible();
    await expect.poll(() => figure.evaluate(img => img.complete && img.naturalWidth > 1000)).toBe(true);   // the recorded PNG really loads from the API
    await expect(page.getByText(/python benchmark_3d.py --dicom-series/)).toBeVisible();
    const table = page.getByRole("region", { name: "Selected parameters" });
    await expect(table.getByRole("row")).toHaveCount(10);                                              // header + 3 methods x 3 noise levels
    await expect(page.getByRole("link", { name: /Download test_summary.csv/ })).toHaveAttribute("href", /\/api\/3d\/runs\/benchmark_3d_2026-10-26\/tables\/test_summary\?format=csv/);
    const sideBySide = page.getByRole("region", { name: "Runs compared" });                              // the second recorded run (noise correlated between slices)
    await expect(sideBySide).toBeVisible();
    await expect(sideBySide.getByText("benchmark_3d_correlated_2026-10-27").first()).toBeVisible();
    await expect(sideBySide.getByText("correlation 0.3").first()).toBeVisible();
    expect(problems).toEqual([]);
  });
});

test.describe("responsive layout", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the lab fits a phone screen and navigation opens from the menu", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: /2D Denoising Lab/ }).click();
    await page.getByLabel("Upload an image or DICOM slice").setInputFiles(fixture("phantom.png"));
    await page.getByTestId("lab-run").click();
    await expect(page.getByTestId("lab-results-table")).toBeVisible();
    const overflow = await page.evaluate(() => {
      const width = document.documentElement.clientWidth;
      const outside = [...document.querySelectorAll(".settings-panel *, .compare *, .output-grid *")]
        .filter(el => !el.closest(".table-wrap") && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().right > width + 1)
        .map(el => `${el.tagName.toLowerCase()}.${el.className}`.slice(0, 60));
      return { scrolls: document.documentElement.scrollWidth > width, outside };
    });
    expect(overflow).toEqual({ scrolls: false, outside: [] });
  });

  test("no page scrolls sideways on a phone and nothing sticks out of its scrollable container", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
    const labels = [/Overview/, /3D CT Explorer/, /Benchmark 3D/, /Older 2D results/, /Methods & Guide/];
    for (const label of labels) {
      await page.getByRole("button", { name: "Open navigation" }).click();
      await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: label }).click();
      await expect(page.getByRole("main")).toBeVisible();
      if (String(label).includes("Benchmark 3D")) await expect(page.locator(".js-plotly-plot").first()).toBeVisible({ timeout: 30_000 });
      const result = await page.evaluate(() => {
        const width = document.documentElement.clientWidth;
        const scrollsInside = el => {                                   // an ancestor that scrolls sideways contains the overflow on purpose
          for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
            if (["auto", "scroll"].includes(getComputedStyle(node).overflowX)) return true;
          }
          return false;
        };
        const insidePlot = el => el.closest(".js-plotly-plot") && !el.matches(".js-plotly-plot, .plot-container, .svg-container, .main-svg, .gtitle, .legend");   // drawn points outside the axes are clipped by Plotly
        const outside = [...document.querySelectorAll("main *")]
          .filter(el => !insidePlot(el) && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().right > width + 1 && !scrollsInside(el))
          .map(el => `${el.tagName.toLowerCase()}.${String(el.className.baseVal ?? el.className)}`.slice(0, 60));
        return { scrolls: document.documentElement.scrollWidth > width, outside: outside.slice(0, 8) };
      });
      expect(result, String(label)).toEqual({ scrolls: false, outside: [] });
    }
  });

  test("the title of the 3D explorer chart fits a phone screen once a volume is loaded", async ({ page }) => {
    // The title is the one the backend writes (backend/src/plotly_ct_viewer.py); only the response is simulated, the layout and Plotly are real.
    const title = "Interactive CT Volume — 512 × 512 × 100 voxels";
    const pixel = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";
    await page.route("**/api/ct/volume", route => route.fulfill({ json: {
      filename_count: 100, slices: 100, dimensions_xyz: [512, 512, 100], spacing_xyz_mm: [0.54, 0.54, 3], intensity_range: [-1024, 1500],
      middle_slice: pixel, note: "Research and educational visualization only; not for diagnosis.",
      figure: { data: [{ type: "scatter", x: [0, 1, 2], y: [0, 1, 0], mode: "lines" }], layout: { title: { text: title }, margin: { t: 100 } } },
    } }));
    await page.goto("/");
    await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
    await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: /3D CT Explorer/ }).click();
    await page.locator('input[type="file"][aria-label="Select DICOM files"]').setInputFiles([path.join(here, "..", "..", "backend", "samples", "synthetic_ct_scan.dcm"),
                                                                                              path.join(here, "..", "..", "backend", "samples", "synthetic_ct_scan.dcm")]);
    const heading = page.locator(".js-plotly-plot .gtitle").first();
    await expect(heading).toBeVisible({ timeout: 30_000 });
    const box = await heading.evaluate(el => { const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, width: document.documentElement.clientWidth }; });
    expect(box.left).toBeGreaterThanOrEqual(0);
    expect(box.right).toBeLessThanOrEqual(box.width);                  // before the fix the title ran past the right edge of a 390 px screen
    expect(await heading.locator("tspan.line").count()).toBeGreaterThan(1);                           // and it is wrapped on several lines
  });

  test("Benchmark 3D has no serious accessibility violations on a phone", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
    await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: /Benchmark 3D/ }).click();
    await expect(page.getByText("FILES VERIFIED")).toBeVisible();
    await expect(page.locator(".js-plotly-plot").first()).toBeVisible({ timeout: 30_000 });
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const serious = result.violations.filter(v => ["serious", "critical"].includes(v.impact)).map(v => `${v.id}: ${v.nodes.length} node(s), e.g. ${String(v.nodes[0]?.target)}`);
    expect(serious, "scrollable regions, such as the command block, must be reachable with the keyboard").toEqual([]);
  });
});

test.describe("accessibility (axe-core, WCAG 2 A and AA rules)", () => {
  for (const theme of ["dark", "light"]) {
    test(`overview, lab and Benchmark 3D have no serious violations in the ${theme} theme`, async ({ page }) => {
      await page.addInitScript(value => localStorage.setItem("biomed-theme", value), theme);
      await page.goto("/");
      await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
      await page.addStyleTag({ content: "*{transition:none !important;animation:none !important}" });
      const scan = () => new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const serious = result => result.violations.filter(v => ["serious", "critical"].includes(v.impact))
        .map(v => `${v.id} (${v.impact}): ${v.nodes.slice(0, 4).map(n => `${n.target.join(" ")} [${(n.any[0]?.message || "").slice(0, 150)}]`).join(" | ")}`);
      expect(serious(await scan()), "overview").toEqual([]);
      await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: /2D Denoising Lab/ }).click();
      await page.getByLabel(/bundled sample/i).selectOption("chest_ct");
      await page.getByTestId("lab-run").click();
      await expect(page.getByTestId("lab-results-table")).toBeVisible();
      expect(serious(await scan()), "lab with results").toEqual([]);
      await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: /Benchmark 3D/ }).click();
      await expect(page.getByText("FILES VERIFIED")).toBeVisible();
      await expect(page.locator(".js-plotly-plot").first()).toBeVisible({ timeout: 30_000 });
      expect(serious(await scan()), "Benchmark 3D with charts").toEqual([]);
    });
  }
});
