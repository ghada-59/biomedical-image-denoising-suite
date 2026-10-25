// @vitest-environment node
// REAL integration test (nothing mocked): an actual Vite dev server is started from frontend/vite.config.js and real HTTP requests are made to it.
// A tiny stand-in backend (plain Node http server) plays the API; the complete flow with the real FastAPI process is in e2e/connection.spec.js.
import http from "node:http";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { createServer, resolveConfig } from "vite";

const configFile = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../vite.config.js");
const cleanup = [];
afterEach(async () => { while (cleanup.length) await cleanup.pop()(); delete process.env.VITE_DEV_API_TARGET; });

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer().once("error", reject).listen(0, "127.0.0.1", () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
  });
}

async function startDashboard(apiTarget) {
  process.env.VITE_DEV_API_TARGET = apiTarget;
  const port = await freePort();
  const server = await createServer({ configFile, logLevel: "silent", server: { port, strictPort: true, host: "127.0.0.1" } });
  await server.listen();
  cleanup.push(() => server.close());
  return `http://127.0.0.1:${port}`;
}

async function startFakeApi(handler) {
  const server = http.createServer(handler);
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  cleanup.push(() => new Promise(resolve => server.close(resolve)));
  return `http://127.0.0.1:${server.address().port}`;
}

describe("dashboard dev server and its /api proxy (real Vite server)", () => {
  it("answers HTTP 502 with a message naming the unreachable address when the backend is not running", async () => {
    const closedPort = await freePort();                                     // nothing listens here
    const target = `http://127.0.0.1:${closedPort}`;
    const dashboard = await startDashboard(target);
    const response = await fetch(`${dashboard}/api/health`);
    const body = await response.json();
    expect(response.status).toBe(502);                                       // not Vite's empty HTTP 500
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(body.code).toBe("api_unreachable");
    expect(body.detail).toContain(`cannot reach the API at ${target}`);
    expect(body.detail).toMatch(/ECONNREFUSED/);
    expect(body.detail).toMatch(/Start the backend/);
    const page = await fetch(`${dashboard}/`);                               // the dashboard itself is fine
    expect(page.status).toBe(200);
    expect(await page.text()).toContain('<div id="root">');
  });

  it("forwards requests to the backend unchanged when it is running (method, path, query, body, status)", async () => {
    const seen = [];
    const api = await startFakeApi((request, response) => {
      let body = "";
      request.on("data", chunk => { body += chunk; });
      request.on("end", () => {
        seen.push({ method: request.method, url: request.url, body });
        response.writeHead(request.url.startsWith("/api/missing") ? 404 : 200, { "Content-Type": "application/json" });
        response.end(JSON.stringify(request.url.startsWith("/api/missing") ? { detail: "Unknown thing." } : { echoed: request.url, service: "stand-in" }));
      });
    });
    const dashboard = await startDashboard(api);
    const get = await fetch(`${dashboard}/api/v2/runs/some_run/tables/test_summary?mask=main&family=Mean`);
    expect(get.status).toBe(200);
    expect(await get.json()).toEqual({ echoed: "/api/v2/runs/some_run/tables/test_summary?mask=main&family=Mean", service: "stand-in" });
    const post = await fetch(`${dashboard}/api/denoise`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ a: 1 }) });
    expect(post.status).toBe(200);
    const refused = await fetch(`${dashboard}/api/missing`);
    expect([refused.status, await refused.json()]).toEqual([404, { detail: "Unknown thing." }]);        // a backend's own errors are not rewritten
    expect(seen.map(r => `${r.method} ${r.url}`)).toEqual(["GET /api/v2/runs/some_run/tables/test_summary?mask=main&family=Mean", "POST /api/denoise", "GET /api/missing"]);
    expect(seen[1].body).toBe('{"a":1}');
  });

  it("keeps working when the backend starts after the dashboard server (no restart needed)", async () => {
    const port = await freePort();
    const dashboard = await startDashboard(`http://127.0.0.1:${port}`);
    expect((await fetch(`${dashboard}/api/health`)).status).toBe(502);
    const api = http.createServer((request, response) => { response.writeHead(200, { "Content-Type": "application/json" }); response.end('{"status":"ok"}'); });
    await new Promise(resolve => api.listen(port, "127.0.0.1", resolve));
    cleanup.push(() => new Promise(resolve => api.close(resolve)));
    const answer = await fetch(`${dashboard}/api/health`);
    expect([answer.status, await answer.json()]).toEqual([200, { status: "ok" }]);
  });
});

describe("configured addresses", () => {
  it("proxies /api to the documented backend address by default, in development and in preview", async () => {
    delete process.env.VITE_DEV_API_TARGET;
    const config = await resolveConfig({ configFile, logLevel: "silent" }, "serve");
    expect(config.server.host).toBe("127.0.0.1");
    expect(config.server.port).toBe(5173);
    expect(config.server.proxy["/api"].target).toBe("http://127.0.0.1:8000");
    expect(config.preview.proxy["/api"].target).toBe("http://127.0.0.1:8000");
    expect(config.preview.port).toBe(4173);
    expect(typeof config.server.proxy["/api"].configure).toBe("function");
  });

  it("lets the proxy target be changed with VITE_DEV_API_TARGET", async () => {
    process.env.VITE_DEV_API_TARGET = "http://127.0.0.1:9001";
    const config = await resolveConfig({ configFile, logLevel: "silent" }, "serve");
    expect([config.server.proxy["/api"].target, config.preview.proxy["/api"].target]).toEqual(["http://127.0.0.1:9001", "http://127.0.0.1:9001"]);
  });
});
