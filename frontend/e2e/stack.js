// Helpers that start and stop the REAL backend (uvicorn) and the REAL dashboard server (Vite) as separate processes,
// so a test can reproduce start-up orders, crashes and restarts. Nothing here is mocked.
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const frontendDir = path.resolve(here, "..");
export const backendDir = path.resolve(frontendDir, "..", "backend");
const python = process.env.E2E_PYTHON || "python";

export function startApi(port, extraEnv = {}) {
  const output = [];
  const child = spawn(python, ["-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", String(port), "--log-level", "info"], {
    cwd: backendDir,
    env: { ...process.env, PYTHONUTF8: "1", ...extraEnv },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", chunk => output.push(String(chunk)));
  child.stderr.on("data", chunk => output.push(String(chunk)));
  return { child, port, output, kind: "api" };
}

export function startDashboard(port, apiPort) {
  const output = [];
  const child = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(port), "--strictPort"], {
    cwd: frontendDir,
    env: { ...process.env, VITE_DEV_API_TARGET: `http://127.0.0.1:${apiPort}` },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", chunk => output.push(String(chunk)));
  child.stderr.on("data", chunk => output.push(String(chunk)));
  return { child, port, output, kind: "dashboard" };
}

export async function waitUntil(check, { timeout = 60_000, interval = 250, label = "condition" } = {}) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    try {
      const value = await check();
      if (value) return value;
    } catch (error) { last = error; }
    await new Promise(resolve => setTimeout(resolve, interval));
  }
  throw new Error(`Timed out after ${timeout} ms waiting for ${label}${last ? ` (${last.message})` : ""}`);
}

export const answers = url => async () => (await fetch(url).catch(() => null))?.ok === true;

export function stop(service) {
  // A process ended by kill() keeps exitCode === null and sets signalCode, so both must be checked or a second stop() would wait forever.
  if (!service || service.child.exitCode !== null || service.child.signalCode !== null) return Promise.resolve();
  return new Promise(resolve => {
    service.child.once("exit", resolve);
    service.child.kill();
  });
}

export const logText = service => service.output.join("");

/** Build the dashboard into `outDir` with the given VITE_API_BASE_URL ("" = not set), exactly as `npm run build` would. */
export function buildDashboard(outDir, apiBaseUrl) {
  const env = { ...process.env };
  delete env.VITE_API_BASE_URL;
  if (apiBaseUrl) env.VITE_API_BASE_URL = apiBaseUrl;
  execFileSync(process.execPath, ["node_modules/vite/bin/vite.js", "build", "--outDir", outDir, "--emptyOutDir"], { cwd: frontendDir, env, stdio: "pipe" });
}

/** `vite preview`: serves a production build and forwards /api like the development server does. */
export function startPreview(port, apiPort, outDir) {
  const output = [];
  const child = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "preview", "--host", "127.0.0.1", "--port", String(port), "--strictPort", "--outDir", outDir], {
    cwd: frontendDir,
    env: { ...process.env, VITE_DEV_API_TARGET: `http://127.0.0.1:${apiPort}` },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", chunk => output.push(String(chunk)));
  child.stderr.on("data", chunk => output.push(String(chunk)));
  return { child, port, output, kind: "preview" };
}

/** A plain static file server with single-page fallback (what a static host does): it has NO /api and no backend behind it. */
export async function startStaticHost(port, directory) {
  const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".webp": "image/webp" };
  const server = http.createServer((request, response) => {
    const requested = path.join(directory, decodeURIComponent(new URL(request.url, "http://x").pathname));
    const file = requested.startsWith(directory) && fs.existsSync(requested) && fs.statSync(requested).isFile() ? requested : path.join(directory, "index.html");
    response.writeHead(200, { "Content-Type": types[path.extname(file)] || "application/octet-stream" });   // HTTP 200 for unknown paths, like a single-page fallback
    fs.createReadStream(file).pipe(response);
  });
  await new Promise(resolve => server.listen(port, "127.0.0.1", resolve));
  // server.close() only closes connections that are idle at that instant; a keep-alive connection that is busy then stays open, and the page, which polls
  // /api/health every 2 s, keeps reusing it, so close() could wait until the test timeout. The test is over when it closes the host: drop every connection.
  return { close: () => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }) };
}
