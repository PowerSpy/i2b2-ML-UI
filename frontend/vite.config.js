import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Proxy keeps the frontend calling same-origin `/api/...` in dev.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8003",
        changeOrigin: true,
      },
    },
  },
});
