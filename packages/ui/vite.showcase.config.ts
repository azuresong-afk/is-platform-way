import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Витрина компонентов: npm run dev -w @platform/ui
export default defineConfig({
  root: "showcase",
  base: "./",
  plugins: [react()],
  build: { outDir: "../dist-showcase", emptyOutDir: true },
});
