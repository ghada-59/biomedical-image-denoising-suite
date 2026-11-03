// Unit tests of the API client with fetch MOCKED. They check how responses and failures are classified and worded;
// whether the real proxy and the real backend produce those responses is tested by the integration tests (proxy.integration.test.js and e2e/).
import { describe, expect, it } from "vitest";
import { ApiError, api, apiHostLabel, apiIsLocal, fetchFile, queryString } from "../api";
import { json, mockApi } from "./mockApi";

const html = (status, body = "<html><body>Not here</body></html>") => () => new Response(body, { status, headers: { "Content-Type": "text/html" } });

describe("api() with a mocked fetch", () => {
  it("returns the parsed body of a successful request", async () => {
    mockApi({ "GET /api/health": { status: "ok" } });
    expect(await api("/api/health")).toEqual({ status: "ok" });
  });

  it("raises the server's own explanation for a refused request, classified as an API answer", async () => {
    mockApi({ "POST /api/denoise": () => json({ detail: "kernel_size: Input should be less than or equal to 51" }, 422) });
    const error = await api("/api/denoise", { method: "POST" }).catch(e => e);
    expect(error).toBeInstanceOf(ApiError);
    expect([error.kind, error.status, error.message]).toEqual(["http", 422, "kernel_size: Input should be less than or equal to 51"]);
  });

  it("shows the dashboard server's own explanation when it cannot reach the backend (HTTP 502 from the proxy)", async () => {
    const detail = "The dashboard server is running but cannot reach the API at http://127.0.0.1:8000 (ECONNREFUSED). Start the backend (see the README).";
    mockApi({ "GET /api/health": () => json({ code: "api_unreachable", detail }, 502) });
    const error = await api("/api/health").catch(e => e);
    expect([error.kind, error.status, error.message]).toEqual(["api-unreachable", 502, detail]);
  });

  it("never mistakes a web page for the API: HTTP 200 with HTML (single-page fallback) is an error", async () => {
    mockApi({ "GET /api/health": html(200, "<!doctype html><title>dashboard</title>") });
    const error = await api("/api/health").catch(e => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe("no-api-route");
    expect(error.message).toMatch(/not as the API.*npm run dev.*VITE_API_BASE_URL/);
  });

  it("explains an HTML 404 (a server that has no /api, for example a static host) instead of saying 'not accepted'", async () => {
    mockApi({ "GET /api/methods": html(404) });
    const error = await api("/api/methods").catch(e => e);
    expect([error.kind, error.status]).toEqual(["no-api-route", 404]);
    expect(error.message).toMatch(/answered \/api\/methods with HTTP 404, but not as the API/);
  });

  it.each([
    [503, /busy or starting up/, "server"],
    [413, /too large/, "http"],
    [500, /HTTP 500/, "server"],
    [502, /HTTP 502/, "server"],
  ])("describes an empty HTTP %i answer without exposing its body", async (status, message, kind) => {
    mockApi({ "GET /api/x": () => new Response("Internal details: Traceback in C:\\secret", { status, headers: { "Content-Type": "text/plain" } }) });
    const error = await api("/api/x").catch(e => e);
    expect(error.message).toMatch(message);
    expect(error.kind).toBe(kind);
    expect(error.message).not.toMatch(/Traceback|secret/);
  });

  it("never lets a list-shaped detail reach the user as '[object Object]'", async () => {
    mockApi({ "GET /api/x": () => json({ detail: [{ msg: "bad" }] }, 422) });
    const error = await api("/api/x").catch(e => e);
    expect(error.message).not.toContain("[object Object]");
  });

  it("says the DASHBOARD server is down (not the API) when even the page's own origin does not answer", async () => {
    mockApi({ "GET /api/x": () => { throw new TypeError("Failed to fetch"); }, "HEAD /": () => { throw new TypeError("Failed to fetch"); } });
    const error = await api("/api/x").catch(e => e);
    expect(error.kind).toBe("dashboard-down");
    expect(error.message).toMatch(/dashboard server at http:\/\/.+ is not responding.*npm run dev.*reload/);
    expect(error.message).not.toMatch(/Cannot reach the API/);
  });

  it("blames the API only when the dashboard's own server still answers", async () => {
    mockApi({ "GET /api/x": () => { throw new TypeError("Failed to fetch"); }, "HEAD /": () => new Response(null) });
    const error = await api("/api/x").catch(e => e);
    expect(error.kind).toBe("api-unreachable");
    expect(error.message).toMatch(/\/api\/x failed before the server answered.*backend is running/);
  });
});

describe("fetchFile() with a mocked fetch", () => {
  it("returns the bytes as a File that carries the given name and type", async () => {
    mockApi({ "GET /api/samples/a/file": () => new Response(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "image/png" } }) });
    const file = await fetchFile("/api/samples/a/file", "a.png", "image/png");
    expect(file).toBeInstanceOf(File);
    expect([file.name, file.type, file.size]).toEqual(["a.png", "image/png", 3]);
    const actualBytes = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve([...new Uint8Array(reader.result)]);
      reader.onerror = () => reject(reader.error || new Error("Could not read the downloaded file."));
      reader.readAsArrayBuffer(file);
    });
    expect(actualBytes).toEqual([1, 2, 3]);
  });

  it("reports an unknown sample and a lost connection with the same classification as api()", async () => {
    mockApi({
      "GET /api/samples/b/file": () => json({ detail: "Unknown sample image." }, 404),
      "GET /api/samples/c/file": () => { throw new TypeError("x"); },
      "HEAD /": () => { throw new TypeError("x"); },
    });
    await expect(fetchFile("/api/samples/b/file", "b.png")).rejects.toMatchObject({ kind: "http", status: 404, message: "Unknown sample image." });
    await expect(fetchFile("/api/samples/c/file", "c.png")).rejects.toMatchObject({ kind: "dashboard-down" });
  });
});

describe("where the API runs", () => {
  it.each([
    ["", "localhost", true],
    ["", "127.0.0.1", true],
    ["", "example.onrender.com", false],
    ["http://127.0.0.1:8000", "example.com", true],
    ["https://api.example.onrender.com", "localhost", false],
    ["not a url", "localhost", false],
  ])("apiIsLocal(%j, page host %j) is %s", (base, host, expected) => {
    expect(apiIsLocal(base, host)).toBe(expected);
  });

  it("names the API host for the privacy notice", () => {
    expect(apiHostLabel("https://api.example.org/")).toBe("api.example.org");
    expect(apiHostLabel("garbage")).toBe("garbage");
  });
});

describe("queryString()", () => {
  it("drops empty values and encodes the rest", () => {
    expect(queryString({ a: 1, b: "", c: null, d: undefined, e: "x y", f: 0 })).toBe("a=1&e=x+y&f=0");
  });
});
