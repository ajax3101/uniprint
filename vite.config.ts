import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectDirectory = dirname(fileURLToPath(import.meta.url));
const root = resolve(projectDirectory, "web");

export default defineConfig({
  root,
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    outDir: resolve(projectDirectory, "src/uniprint/static"),
    emptyOutDir: true,
  },
});
