import { vi } from "vitest";
import contract from "./fixtures/api_contract.json";

export const CATALOGUE = contract.methods;
export const SAMPLES = contract.samples;

/** A 1x1 transparent PNG, as a data URL, to stand in for the images the API returns. */
export const PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

export function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/**
 * Replace global fetch with a router. ``routes`` maps "METHOD /path" to a body, a Response, or a function of the request
 * (``{ url, method, body }``) returning either. An unrouted request fails the test, so no call goes unnoticed.
 */
export function mockApi(routes) {
  const calls = [];
  const fetchMock = vi.fn(async (input, options = {}) => {
    const url = String(input).replace(/^https?:\/\/[^/]+/, "");
    const method = (options.method || "GET").toUpperCase();
    const request = { url, method, body: options.body };
    calls.push(request);
    const route = routes[`${method} ${url}`];
    if (route === undefined) throw new Error(`Unexpected request: ${method} ${url}`);
    const answer = typeof route === "function" ? await route(request) : route;
    return answer instanceof Response ? answer : json(answer);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function formEntries(body) {
  return Object.fromEntries([...body.entries()].map(([key, value]) => [key, value instanceof File ? `file:${value.name}` : value]));
}

export function baseRoutes(extra = {}) {
  return {
    "HEAD /": () => new Response(null),                       // the dashboard server itself answers
    "GET /api/health": { status: "ok", service: "Biomedical Imaging API", version: "1.0.0", unavailable_methods: [], problems: [] },
    "GET /api/results": { available: false, rows: [], noise_types: [], source: null, provenance: null },
    "GET /api/methods": CATALOGUE,
    "GET /api/samples": SAMPLES,
    "GET /api/v2/runs": { configured: false, runs: [], caveats: [], slice_comparison_available: false },
    "GET /api/3d/runs": { configured: false, runs: [], caveats: [] },
    ...extra,
  };
}

/** The "parameters used" the API reports for each method (same keys as backend/methods.py). */
const USED = {
  mean: { kernel_size: 5 }, median: { kernel_size: 5 }, gaussian: { kernel_size: 5, sigma: "auto (set by OpenCV from the kernel size)" },
  fft_ideal: { cutoff_ratio: 0.15 }, fft_gauss: { cutoff_ratio: 0.15 }, fft_butterworth: { cutoff_ratio: 0.15, order: 2 },
  bilateral: { sigma_color: 0.4, sigma_space: 1.5 }, nlm: { h: 0.15, patch_size: 5, patch_distance: 6 },
  wavelet: { assumed_noise_sd: 0.15, wavelet: "sym4", levels: 3, shifts_averaged: 16 },
};

/** The shape of a /api/denoise answer for the given method ids (images are tiny stand-ins). */
export function denoiseAnswer(ids, { width = 64, height = 48, noise = "Gaussian" } = {}) {
  const methods = ids.map(id => CATALOGUE.methods.find(m => m.id === id));
  const labels = ["Noisy input", ...methods.map(m => m.label)];
  return {
    filename: "x.png", width, height, noise_type: noise,
    images: Object.fromEntries(labels.map(label => [label, PIXEL])),
    results: labels.map((label, i) => ({ Filter: label, "PSNR (dB)": i === 0 ? 17.3 : 20 + i, SSIM: i === 0 ? 0.06 : 0.5 + i / 20 })),
    methods: methods.map(m => ({ id: m.id, label: m.label, family: m.family, parameters: USED[m.id] })),
    settings: { noise_type: noise, noise_amount: null, noise_variance: 0.02, seed: 42 },
    timings_ms: Object.fromEntries([...labels.map((label, i) => [label, 1.5 + i]), ["total", 25.25]]),
    note: "Metrics compare outputs with the original image before synthetic noise was added.",
  };
}

export const PREVIEW = { filename: "slice.png", width: 64, height: 48, preview: PIXEL, format: "grayscale image" };
