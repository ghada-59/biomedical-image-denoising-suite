// REAL tests of the PRODUCTION build: the application is built twice with `vite build` (with and without VITE_API_BASE_URL), served, and
// driven by a real Chrome while the URL of every API request is recorded. Nothing is mocked.
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { answers, buildDashboard, frontendDir, logText, startApi, startPreview, startStaticHost, stop, waitUntil } from "./stack.js";

test.describe.configure({ mode: "serial" });

const OUT = path.join(frontendDir, "dist-e2e");
const CROSS_DIR = path.join(OUT, "with-base-url");
const SAME_DIR = path.join(OUT, "without-base-url");
const API_PORT = 8871;
const API_ORIGIN = `http://127.0.0.1:${API_PORT}`;
const CROSS_PORT = 4281;
const SAME_PORT = 4282;
const STATIC_PORT = 4283;

test.beforeAll(() => {
  fs.rmSync(OUT, { recursive: true, force: true });
  buildDashboard(CROSS_DIR, API_ORIGIN);          // as built for a host where the API has another address
  buildDashboard(SAME_DIR, "");                   // as built for `npm run preview` or a host that forwards /api
});
test.afterAll(() => { fs.rmSync(OUT, { recursive: true, force: true }); });

const nav = (page, name) => page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name });

function recordApiOrigins(page) {
  const origins = new Map();
  const failures = [];
  page.on("request", request => { if (request.url().includes("/api/")) { const origin = new URL(request.url()).origin; origins.set(origin, (origins.get(origin) || 0) + 1); } });
  page.on("requestfailed", request => failures.push(`${request.url()} ${request.failure()?.errorText}`));
  return { origins, failures };
}

test("a build made WITH VITE_API_BASE_URL calls that address directly, and works when the API allows the page's origin", async ({ page }) => {
  const bundle = fs.readdirSync(path.join(CROSS_DIR, "assets")).filter(f => f.startsWith("index-") && f.endsWith(".js"));
  expect(fs.readFileSync(path.join(CROSS_DIR, "assets", bundle[0]), "utf8")).toContain(API_ORIGIN);       // the address is baked into the build
  const api = startApi(API_PORT, { CORS_ORIGINS: `http://127.0.0.1:${CROSS_PORT}` });
  const preview = startPreview(CROSS_PORT, 9, CROSS_DIR);                                                 // proxy target 9 is unused: calls must bypass it
  try {
    await waitUntil(answers(`http://127.0.0.1:${CROSS_PORT}/`), { label: "the preview server" });
    await waitUntil(answers(`${API_ORIGIN}/api/health`), { label: "the API" });
    const seen = recordApiOrigins(page);
    await page.goto(`http://127.0.0.1:${CROSS_PORT}/`);
    await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
    await expect(page.getByTestId("api-status")).toContainText(`127.0.0.1:${API_PORT}`);                  // the page says which API it talks to
    await nav(page, "Methods & Guide").click();
    await expect(page.getByRole("heading", { name: "Wavelet (BayesShrink)" })).toBeVisible();
    await nav(page, "2D Denoising Lab").click();
    await page.getByLabel("Upload an image or DICOM slice").setInputFiles("e2e/fixtures/phantom.png");
    await page.getByTestId("lab-run").click();
    await expect(page.getByTestId("lab-results-table")).toBeVisible();
    expect([...seen.origins.keys()]).toEqual([API_ORIGIN]);                                                // every API call went to the configured address
    expect(seen.failures).toEqual([]);
    expect(logText(api)).toMatch(/POST \/api\/denoise HTTP\/1\.1" 200/);
  } finally { await stop(preview); await stop(api); }
});

test("the same build says the API is unreachable (and which address) when it is not running, never a false success", async ({ page }) => {
  const preview = startPreview(CROSS_PORT, 9, CROSS_DIR);
  try {
    await waitUntil(answers(`http://127.0.0.1:${CROSS_PORT}/`), { label: "the preview server" });
    await page.goto(`http://127.0.0.1:${CROSS_PORT}/`);
    await expect(page.getByTestId("api-banner")).toContainText(`Cannot reach the API at 127.0.0.1:${API_PORT}`);
    await expect(page.getByTestId("api-banner")).toContainText("VITE_API_BASE_URL");
    await expect(page.getByTestId("api-status")).toContainText("API OFFLINE");
  } finally { await stop(preview); }
});

test("a build made WITHOUT it calls the page's own address, which `vite preview` forwards to the API", async ({ page }) => {
  const api = startApi(API_PORT);
  const preview = startPreview(SAME_PORT, API_PORT, SAME_DIR);
  try {
    await waitUntil(answers(`http://127.0.0.1:${SAME_PORT}/api/health`), { label: "the preview-to-API connection" });
    const seen = recordApiOrigins(page);
    await page.goto(`http://127.0.0.1:${SAME_PORT}/`);
    await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
    await nav(page, "Benchmark V2").click();
    await expect(page.getByText(/classical denoisers compared|No benchmark V2 run is configured/)).toBeVisible();
    expect([...seen.origins.keys()]).toEqual([`http://127.0.0.1:${SAME_PORT}`]);
    expect(seen.failures).toEqual([]);
    await stop(api);                                                                                       // and when the API stops, the preview proxy explains it
    await expect(page.getByTestId("api-banner")).toContainText(`cannot reach the API at http://127.0.0.1:${API_PORT}`, { timeout: 15_000 });
  } finally { await stop(preview); await stop(api); }
});

test("a build served by a static host with no backend never shows a false 'API ONLINE'", async ({ page }) => {
  const host = await startStaticHost(STATIC_PORT, SAME_DIR);        // answers HTTP 200 + index.html for /api/health, like a single-page fallback
  try {
    await page.goto(`http://127.0.0.1:${STATIC_PORT}/`);
    const banner = page.getByTestId("api-banner");
    await expect(banner).toContainText("The API is not reachable");
    await expect(banner).toContainText("not as the API");
    await expect(banner).toContainText("VITE_API_BASE_URL");
    await expect(page.getByTestId("api-status")).toContainText("API OFFLINE");
    await expect(page.getByTestId("api-status")).not.toContainText("API ONLINE");
    await nav(page, "2D Denoising Lab").click();
    await expect(page.getByTestId("lab-run")).toBeDisabled();
    await expect(page.getByText(/Choose methods|bundled sample/).first()).toBeVisible();
  } finally { await host.close(); }
});
