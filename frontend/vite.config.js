import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Where the dashboard server forwards /api/* requests. 127.0.0.1 (not "localhost") on purpose: the backend is started with
// --host 127.0.0.1 in the documented commands, and "localhost" resolves to ::1 first on some machines.
const apiTarget = process.env.VITE_DEV_API_TARGET || "http://127.0.0.1:8000";

/**
 * When the backend is not running, Vite's own proxy answers an empty HTTP 500, which the page can only describe as "HTTP 500".
 * This handler is registered first and answers HTTP 502 with a message that names the address it tried and what to do.
 */
export function explainUnreachableApi(proxy) {
  proxy.on("error", (error, _request, response) => {
    if (!response || typeof response.writeHead !== "function" || response.headersSent || response.writableEnded) return;
    response.writeHead(502, { "Content-Type": "application/json" });
    response.end(JSON.stringify({
      code: "api_unreachable",
      detail: `The dashboard server is running but cannot reach the API at ${apiTarget} (${error.code || error.message}). ` +
        "Start the backend (see the README); this page reconnects by itself once it answers.",
    }));
  });
}

const apiProxy = { "/api": { target: apiTarget, configure: explainUnreachableApi } };

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: apiProxy,
  },
  // `npm run preview` serves the production build; it forwards /api the same way, so a local build can be tried without a separate host.
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy: apiProxy,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Plotly (about 4.7 MB) is its own chunk, fetched only when a page with a chart opens; the entry chunk stays small.
    chunkSizeWarningLimit: 4800,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    include: ["src/**/*.test.{js,jsx}"],
    restoreMocks: true,
  },
});
