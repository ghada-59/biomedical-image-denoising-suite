import { defineConfig } from "@playwright/test";

// End-to-end tests drive a real browser against the real FastAPI backend and the Vite dev server.
//   E2E_PYTHON            Python with the backend requirements installed (default: "python")
//   E2E_BROWSER_CHANNEL   "chrome" (default, uses the installed Chrome), "msedge", or "chromium" after `npx playwright install chromium`
//   E2E_BENCHMARK_RUN_DIR optional: a Benchmark V2 run directory to expose to the API (enables the benchmark test)
const python = process.env.E2E_PYTHON || "python";
const apiPort = 8765;
const webPort = 5199;
const channel = process.env.E2E_BROWSER_CHANNEL || "chrome";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    ...(channel === "chromium" ? {} : { channel }),
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `${python} -m uvicorn api:app --host 127.0.0.1 --port ${apiPort} --log-level warning`,
      cwd: "../backend",
      url: `http://127.0.0.1:${apiPort}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { BENCHMARK_RUN_DIRS: process.env.E2E_BENCHMARK_RUN_DIR || "", CT_SERIES_DIR: "", PYTHONUTF8: "1" },
    },
    {
      command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${webPort} --strictPort`,
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_DEV_API_TARGET: `http://127.0.0.1:${apiPort}` },
    },
  ],
});
