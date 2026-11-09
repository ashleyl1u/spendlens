/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import type { ProxyOptions } from "vite";
import { defineConfig } from "vite";

// Override with SPENDLENS_API_URL to point the dev server at a backend on another port.
const BACKEND = process.env.SPENDLENS_API_URL || "http://127.0.0.1:8000";

// API paths sent to the FastAPI backend. Some of them are also page URLs in the app
// (/accounts, /dashboard), so a browser navigation that asks for HTML still gets the
// app's index.html; only fetch() calls, which ask for JSON, reach the backend.
const API_PREFIXES = ["/auth", "/accounts", "/uploads", "/transactions", "/dashboard", "/assistant"];

const toBackend: ProxyOptions = {
  target: BACKEND,
  changeOrigin: true,
  bypass(req) {
    if (req.headers.accept?.includes("text/html")) return "/index.html";
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(API_PREFIXES.map((prefix) => [prefix, toBackend])),
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
