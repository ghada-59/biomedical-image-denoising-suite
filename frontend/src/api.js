const configuredApiBase = (import.meta.env.VITE_API_BASE_URL || "").trim();

export const API_BASE_URL = configuredApiBase
  ? (configuredApiBase.startsWith("http") ? configuredApiBase : "https://" + configuredApiBase).replace(/\/+$/, "")
  : "";

/**
 * An error with a machine-readable ``kind``, so the interface can say what is actually wrong:
 *  - "dashboard-down":  the server that delivered this page no longer answers (for example `npm run dev` was stopped)
 *  - "api-unreachable": the dashboard server (or the browser) cannot reach the backend
 *  - "no-api-route":    something answered, but it is not the API (a static host without a backend, a wrong address)
 *  - "server":          the API itself failed (HTTP 5xx)
 *  - "http":            the API refused the request with an explanation (HTTP 4xx)
 */
export class ApiError extends Error {
  constructor(message, kind, status = null) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

/** True when the API runs on this computer, so uploaded files never leave it. */
export function apiIsLocal(base = API_BASE_URL, pageHost = typeof window !== "undefined" ? window.location.hostname : "") {
  let host = pageHost;
  if (base) {
    try { host = new URL(base).hostname; } catch { return false; }
  }
  return ["localhost", "127.0.0.1", "[::1]", "::1"].includes(host);
}

export function apiHostLabel(base = API_BASE_URL) {
  if (!base) return typeof window !== "undefined" ? window.location.host : "this site";
  try { return new URL(base).host; } catch { return base; }
}

function pageOrigin() {
  return typeof window !== "undefined" ? window.location.origin : "";
}

/** Does the server that delivered this page still answer? (Same origin, so no CORS involved.) */
async function ownServerAnswers() {
  try {
    await fetch(`${pageOrigin()}/`, { method: "HEAD", cache: "no-store" });
    return true;
  } catch {
    return false;
  }
}

async function networkError(path) {
  if (API_BASE_URL) {
    return new ApiError(
      `Cannot reach the API at ${apiHostLabel()}. Start the backend, or check VITE_API_BASE_URL and the API's CORS_ORIGINS setting.`,
      "api-unreachable",
    );
  }
  if (!(await ownServerAnswers())) {
    return new ApiError(
      `The dashboard server at ${pageOrigin()} is not responding. If you started it with "npm run dev" it has stopped: start it again, then reload this page.`,
      "dashboard-down",
    );
  }
  return new ApiError(`The request to ${path} failed before the server answered. Check that the backend is running.`, "api-unreachable");
}

function notTheApi(path, status) {
  return new ApiError(
    `${pageOrigin() || "This server"} answered ${path} with HTTP ${status}, but not as the API. ` +
    "With `npm run dev` or `npm run preview` the dashboard forwards /api to the backend; a production build needs VITE_API_BASE_URL set when it is built.",
    "no-api-route",
    status,
  );
}

/** Turn a non-successful or unexpected response into an ApiError. */
async function failureFor(response, path) {
  const isJson = (response.headers.get("content-type") || "").includes("json");
  const payload = isJson ? await response.json().catch(() => ({})) : {};
  if (typeof payload.detail === "string" && payload.detail) {
    return new ApiError(payload.detail, payload.code === "api_unreachable" ? "api-unreachable" : (response.status >= 500 ? "server" : "http"), response.status);
  }
  if (!isJson && (response.status === 404 || response.status === 405)) return notTheApi(path, response.status);
  if (response.status === 503) return new ApiError("The server is busy or starting up. Wait a few seconds and try again.", "server", 503);
  if (response.status === 413) return new ApiError("The file is too large for this server.", "http", 413);
  if (response.status >= 500) return new ApiError(`The server reported an error (HTTP ${response.status}).`, "server", response.status);
  return new ApiError(`The request was not accepted (HTTP ${response.status}).`, "http", response.status);
}

async function send(path, options) {
  try {
    return await fetch(`${API_BASE_URL}${path}`, options || {});
  } catch {
    throw await networkError(path);
  }
}

export async function api(path, options) {
  const response = await send(path, options);
  if (!response.ok) throw await failureFor(response, path);
  if (!(response.headers.get("content-type") || "").includes("json")) throw notTheApi(path, response.status);   // e.g. index.html served for an unknown path
  return response.json().catch(() => { throw new ApiError(`The API answered ${path} with something that is not valid JSON.`, "server", response.status); });
}

/** Fetch a binary file (a bundled sample) from the API as a File object, so it takes the normal upload path. */
export async function fetchFile(path, filename, type) {
  const response = await send(path);
  if (!response.ok) throw await failureFor(response, path);
  const blob = await response.blob();
  return new File([blob], filename, { type: type || blob.type });
}

export function queryString(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  });
  return search.toString();
}
