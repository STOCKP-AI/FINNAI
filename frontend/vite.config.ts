/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

/**
 * Security headers for the static site. The same values are used by `vite preview` (so the
 * end-to-end tests run under the production Content-Security-Policy) and written to
 * dist/_headers, which Cloudflare Pages applies to every response.
 * connect-src lists the API's exact origin: never a wildcard such as *.onrender.com.
 */
export function securityHeaders(apiBase: string): Record<string, string> {
  const api = new URL(apiBase).origin;
  const csp = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'", // React style attributes and the chart library
    "img-src 'self' data:",
    "font-src 'self' data:",
    `connect-src 'self' ${api}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
  return {
    "Content-Security-Policy": csp,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000",
  };
}

function cloudflareHeaders(headers: Record<string, string>): Plugin {
  const lines = ["/*", ...Object.entries(headers).map(([k, v]) => `  ${k}: ${v}`), ""];
  lines.push("/assets/*", "  Cache-Control: public, max-age=31536000, immutable", "");
  return {
    name: "cloudflare-headers",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "_headers", source: lines.join("\n") });
    },
  };
}

// The API address comes from VITE_API_BASE_URL (.env.local in development, the Cloudflare Pages
// build settings in production). Nothing secret ever goes into a VITE_ variable: it ships to browsers.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const apiBase = env.VITE_API_BASE_URL || "http://localhost:8000";
  if (process.env.CF_PAGES && !/^https:\/\//.test(env.VITE_API_BASE_URL ?? "")) {
    // A Cloudflare build without the API address would ship a site that calls localhost.
    throw new Error("Set VITE_API_BASE_URL (https://...) in the Cloudflare Pages build settings.");
  }
  const headers = securityHeaders(apiBase);
  return {
    plugins: [react(), tailwindcss(), cloudflareHeaders(headers)],
    server: { port: 5173, strictPort: true },
    preview: { headers },
    build: { sourcemap: true },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
      css: false,
    },
  };
});
