/// <reference types="vitest" />
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const ui = (p: string) => fileURLToPath(new URL(`../packages/ui/src/${p}`, import.meta.url));

// Оболочка собирается из исходников @platform/ui того же репозитория (одна версия, без публикации).
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^@platform\/ui\/styles\.css$/, replacement: ui("styles.css") },
      { find: /^@platform\/ui$/, replacement: ui("index.ts") },
    ],
  },
  server: {
    port: 5173,
    proxy: {
      // Для разработки без шлюза: API платформы и заглушки продуктов на портах из контракта.
      "/api/platform": { target: "http://127.0.0.1:18010", rewrite: (p) => p.replace(/^\/api\/platform/, "") },
      "/api/scanner": { target: "http://127.0.0.1:18000", rewrite: (p) => p.replace(/^\/api\/scanner/, "") },
      "/api/vm": { target: "http://127.0.0.1:18001", rewrite: (p) => p.replace(/^\/api\/vm/, "") },
      "/api/grc": { target: "http://127.0.0.1:18002", rewrite: (p) => p.replace(/^\/api\/grc/, "") },
    },
  },
  build: { sourcemap: false, assetsInlineLimit: 0 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: [fileURLToPath(new URL("./src/test-setup.ts", import.meta.url))],
    css: false,
  },
});
