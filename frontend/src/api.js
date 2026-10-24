const configuredApiBase = (import.meta.env.VITE_API_BASE_URL || "").trim();

export const API_BASE_URL = configuredApiBase
  ? (configuredApiBase.startsWith("http") ? configuredApiBase : "https://" + configuredApiBase).replace(/\/+$/, "")
  : "";

export async function api(path, options) {
  const response = await fetch(`${API_BASE_URL}${path}`, options || {});
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "The request could not be completed.");
  return payload;
}

export function queryString(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  });
  return search.toString();
}
