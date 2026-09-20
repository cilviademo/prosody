import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri serves the dev server on a fixed port and expects a relative base.
export default defineConfig({
  plugins: [react()],
  base: "./",
  clearScreen: false,
  server: { port: 5183, strictPort: true },
  build: { target: "es2021", outDir: "dist", emptyOutDir: true },
});
