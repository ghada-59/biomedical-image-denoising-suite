// REAL integration tests of start-up order, crashes and recovery: separate uvicorn and Vite processes are started and stopped while a real
// Chrome keeps the same page open. Nothing is mocked or intercepted. Ports are private to this file (8861 / 5261).
import { expect, test } from "@playwright/test";
import { answers, logText, startApi, startDashboard, stop, waitUntil } from "./stack.js";

const API_PORT = 8861;
const WEB_PORT = 5261;
const WEB = `http://127.0.0.1:${WEB_PORT}`;
const API_HEALTH = `http://127.0.0.1:${API_PORT}/api/health`;
const PAGES = ["Overview", "2D Denoising Lab", "Benchmark V2", "Benchmark 3D", "3D CT Explorer", "Older 2D results", "Methods & Guide"];

test.describe.configure({ mode: "serial" });

let api;
let dashboard;
test.afterEach(async () => { await stop(api); await stop(dashboard); api = undefined; dashboard = undefined; });

async function openApp(page, origin = WEB) {
  await page.goto(origin);
  await page.evaluate(() => { window.__sameDocument = "yes"; });         // survives only while the page is not reloaded
}
const sameDocument = page => page.evaluate(() => window.__sameDocument === "yes");
const nav = (page, name) => page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name });

test("dashboard started first, API later: the page names the cause, then recovers by itself without a reload", async ({ page }) => {
  dashboard = startDashboard(WEB_PORT, API_PORT);
  await waitUntil(async () => (await fetch(WEB).catch(() => null))?.ok === true, { label: "the dashboard server" });
  await openApp(page);

  // the API has never been started: the real Vite proxy answers 502 with an explicit message
  const banner = page.getByTestId("api-banner");
  await expect(banner).toContainText("The API is not reachable");
  await expect(banner).toContainText(`cannot reach the API at http://127.0.0.1:${API_PORT}`);
  await expect(page.getByTestId("api-status")).toContainText("API OFFLINE");
  await expect(page.locator("body")).not.toContainText("HTTP 500");
  await nav(page, "Methods & Guide").click();
  await expect(page.getByText(/method descriptions come from the API and could not be loaded/)).toBeVisible();
  await nav(page, "Older 2D results").click();
  await expect(page.getByText("Results cannot be loaded: the API is not reachable")).toBeVisible();
  await nav(page, "3D CT Explorer").click();
  await expect(page.getByLabel("Select DICOM files")).toBeDisabled();

  // start the real backend
  api = startApi(API_PORT);
  await waitUntil(answers(API_HEALTH), { label: "the API health check" });
  await expect(banner).toBeHidden({ timeout: 15_000 });
  await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
  expect(await sameDocument(page)).toBe(true);                           // recovered without a reload
  await expect(page.getByLabel("Select DICOM files")).toBeEnabled();
  await nav(page, "Methods & Guide").click();
  await expect(page.getByRole("heading", { name: "Wavelet (BayesShrink)" })).toBeVisible();
  await nav(page, "2D Denoising Lab").click();
  await expect(page.getByRole("checkbox", { name: "Mean", exact: true })).toBeVisible();
  expect(logText(api)).not.toMatch(/Traceback|Error/);
});

test("API stopped while the page is open, then restarted: accurate error, page kept, recovery without a reload", async ({ page }) => {
  api = startApi(API_PORT);
  dashboard = startDashboard(WEB_PORT, API_PORT);
  await waitUntil(answers(`${WEB}/api/health`), { label: "the dashboard-to-API connection" });
  await openApp(page);
  await nav(page, "2D Denoising Lab").click();
  await expect(page.getByRole("checkbox", { name: "Mean", exact: true })).toBeVisible();
  await page.getByLabel("Random seed").fill("123");

  await stop(api);                                                        // the backend dies
  const banner = page.getByTestId("api-banner");
  await expect(banner).toContainText("cannot reach the API at", { timeout: 15_000 });
  await expect(banner).toContainText("ECONNREFUSED");
  await expect(page.getByRole("checkbox", { name: "Mean", exact: true })).toBeVisible();   // the lab is still on screen
  await expect(page.getByLabel("Random seed")).toHaveValue("123");                          // and keeps what the user typed

  api = startApi(API_PORT);                                              // the backend returns on the same port
  await waitUntil(answers(API_HEALTH), { label: "the restarted API" });
  await expect(banner).toBeHidden({ timeout: 15_000 });
  expect(await sameDocument(page)).toBe(true);
  await expect(page.getByLabel("Random seed")).toHaveValue("123");
  await page.getByLabel("Upload an image or DICOM slice").setInputFiles("e2e/fixtures/phantom.png");
  await page.getByTestId("lab-run").click();
  await expect(page.getByTestId("lab-results-table")).toBeVisible();      // real processing works after the restart
});

test("dashboard server stopped while the page is open: the message names the dashboard, not the API, and the page returns when it restarts", async ({ page }) => {
  api = startApi(API_PORT);
  dashboard = startDashboard(WEB_PORT, API_PORT);
  await waitUntil(answers(`${WEB}/api/health`), { label: "the dashboard-to-API connection" });
  await openApp(page);
  await expect(page.getByTestId("api-status")).toContainText("API ONLINE");

  await stop(dashboard);                                                  // the situation behind "Cannot reach the API at localhost:5173"
  const banner = page.getByTestId("api-banner");
  await expect(banner).toContainText("The dashboard server is not responding", { timeout: 15_000 });
  await expect(banner).toContainText(`http://127.0.0.1:${WEB_PORT}`);
  await expect(banner).toContainText("npm run dev");
  await expect(banner).not.toContainText("Cannot reach the API");

  dashboard = startDashboard(WEB_PORT, API_PORT);
  await waitUntil(answers(`${WEB}/api/health`), { label: "the restarted dashboard server" });
  await expect(page.getByTestId("api-banner")).toBeHidden({ timeout: 20_000 });
  await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
});

for (const hostname of ["127.0.0.1", "localhost"]) {
  test(`all seven pages work through ${hostname}, with no failed request and no console error`, async ({ page }) => {
    api = startApi(API_PORT);
    await waitUntil(answers(API_HEALTH), { label: "the API" });         // the API is ready BEFORE the dashboard starts sending requests
    dashboard = startDashboard(WEB_PORT, API_PORT);
    await waitUntil(answers(`${WEB}/api/health`), { label: "the dashboard-to-API connection" });
    const problems = [];
    const requested = new Set();
    page.on("requestfailed", request => problems.push(`FAILED ${request.method()} ${request.url()} ${request.failure()?.errorText}`));
    page.on("response", response => { if (response.url().includes("/api/")) { requested.add(new URL(response.url()).origin); if (response.status() >= 400) problems.push(`HTTP ${response.status()} ${response.url()}`); } });
    page.on("console", message => { if (message.type() === "error") problems.push(`console.error ${message.text()}`); });
    page.on("pageerror", error => problems.push(`pageerror ${error.message}`));
    await openApp(page, `http://${hostname}:${WEB_PORT}`);
    await expect(page.getByTestId("api-status")).toContainText("API ONLINE");
    for (const name of PAGES) {
      await nav(page, name).click();
      await page.waitForTimeout(1200);
    }
    await expect(page.getByRole("heading", { name: "Wavelet (BayesShrink)" })).toBeVisible();   // Methods & Guide shows the real descriptions
    await nav(page, "2D Denoising Lab").click();
    await page.getByLabel(/bundled sample/i).selectOption("synthetic_ct");
    await expect(page.getByAltText(/Preview of/)).toBeVisible();
    await page.getByTestId("lab-run").click();
    await expect(page.getByTestId("lab-results-table")).toBeVisible();
    expect(problems).toEqual([]);
    expect([...requested]).toEqual([`http://${hostname}:${WEB_PORT}`]);    // every API call went to the page's own address (through the proxy)
    expect(logText(api)).not.toMatch(/Traceback| 500 /);
    expect(logText(api)).toMatch(/GET \/api\/methods HTTP\/1\.1" 200/);    // the backend really received them
  });
}
