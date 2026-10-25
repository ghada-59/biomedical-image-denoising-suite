import { describe, expect, it } from "vitest";
import { api, apiHostLabel, apiIsLocal, fetchFile, queryString } from "../api";
import { json, mockApi } from "./mockApi";

describe("api()", () => {
  it("returns the parsed body of a successful request", async () => {
    mockApi({ "GET /api/health": { status: "ok" } });
    expect(await api("/api/health")).toEqual({ status: "ok" });
  });

  it("raises the server's own message for a refused request", async () => {
    mockApi({ "POST /api/denoise": () => json({ detail: "kernel_size: Input should be less than or equal to 51" }, 422) });
    await expect(api("/api/denoise", { method: "POST" })).rejects.toThrow("kernel_size: Input should be less than or equal to 51");
  });

  it.each([
    [503, /busy or starting up/],
    [413, /too large/],
    [500, /HTTP 500/],
    [502, /HTTP 502/],
    [404, /HTTP 404/],
  ])("explains an empty or non-JSON HTTP %i answer without exposing the raw body", async (status, message) => {
    mockApi({ "GET /api/x": () => new Response("<html>Bad gateway</html>", { status }) });
    const error = await api("/api/x").catch(e => e);
    expect(error.message).toMatch(message);
    expect(error.message).not.toMatch(/html|Bad gateway/i);
  });

  it("never lets a list-shaped detail reach the user as '[object Object]'", async () => {
    mockApi({ "GET /api/x": () => json({ detail: [{ msg: "bad" }] }, 422) });
    const error = await api("/api/x").catch(e => e);
    expect(error.message).not.toContain("[object Object]");
  });

  it("turns a lost connection into a message that names what to do", async () => {
    mockApi({ "GET /api/x": () => { throw new TypeError("Failed to fetch"); } });
    await expect(api("/api/x")).rejects.toThrow(/Cannot reach the API.*Start the backend/);
  });
});

describe("fetchFile()", () => {
  it("returns the bytes as a File that carries the given name and type", async () => {
    mockApi({ "GET /api/samples/a/file": () => new Response(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "image/png" } }) });
    const file = await fetchFile("/api/samples/a/file", "a.png", "image/png");
    expect(file).toBeInstanceOf(File);
    expect([file.name, file.type, file.size]).toEqual(["a.png", "image/png", 3]);
  });

  it("reports an unknown sample and a lost connection", async () => {
    mockApi({ "GET /api/samples/b/file": () => json({ detail: "Unknown sample image." }, 404), "GET /api/samples/c/file": () => { throw new TypeError("x"); } });
    await expect(fetchFile("/api/samples/b/file", "b.png")).rejects.toThrow(/HTTP 404/);
    await expect(fetchFile("/api/samples/c/file", "c.png")).rejects.toThrow(/Cannot reach the API/);
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
