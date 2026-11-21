import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// mode "offline": автономная сборка для GitHub Pages (без сервера) в ../webapp
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === "offline" ? "./" : "/",
  build: mode === "offline" ? { outDir: "../webapp", emptyOutDir: false } : {},
  server: { proxy: { "/api": "http://localhost:8000" } },
}));
