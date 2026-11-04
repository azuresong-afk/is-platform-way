/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Library mode: JS-модуль без зависимостей-пиров; CSS и шрифты копирует scripts/copy-assets.mjs,
// чтобы шрифты остались отдельными файлами (CSP разрешает шрифты только с 'self', data: нельзя).
export default defineConfig({
  plugins: [react()],
  build: {
    lib: { entry: "src/index.ts", formats: ["es"], fileName: () => "index.js" },
    rollupOptions: {
      external: ["react", "react-dom", "react/jsx-runtime", "react-router-dom", "lucide-react"],
    },
    sourcemap: true,
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test-setup.ts"],
    css: false,
  },
});
