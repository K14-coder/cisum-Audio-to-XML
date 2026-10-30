import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs separately (FastAPI on :8000 by default); the dev server proxies /api to it.
const apiTarget = process.env.VITE_API_PROXY ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: false },
    },
  },
  preview: {
    proxy: {
      "/api": { target: apiTarget, changeOrigin: false },
    },
  },
  build: {
    // OpenSheetMusicDisplay is large; it's loaded lazily in its own chunk.
    chunkSizeWarningLimit: 2500,
  },
});
