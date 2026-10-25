const configuredApiBase = (import.meta.env.VITE_API_BASE_URL || "").trim();

export const API_BASE_URL = configuredApiBase
  ? (configuredApiBase.startsWith("http") ? configuredApiBase : "https://" + configuredApiBase).replace(/\/+$/, "")
  : "";

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

function messageFor(response, payload) {
  if (typeof payload?.detail === "string" && payload.detail) return payload.detail;
  if (response.status === 503) return "The server is busy or starting up. Wait a few seconds and try again.";
  if (response.status === 413) return "The file is too large for this server.";
  if (response.status >= 500) return `The server reported an error (HTTP ${response.status}).`;
  return `The request was not accepted (HTTP ${response.status}).`;
}

export async function api(path, options) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, options || {});
  } catch {
    throw new Error(`Cannot reach the API at ${apiHostLabel()}. Start the backend or check your connection.`);
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(messageFor(response, payload));
  return payload;
}

/** Fetch a binary file (a bundled sample) from the API as a File object, so it takes the normal upload path. */
export async function fetchFile(path, filename, type) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw new Error(`Cannot reach the API at ${apiHostLabel()}. Start the backend or check your connection.`);
  }
  if (!response.ok) throw new Error(messageFor(response, {}));
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
