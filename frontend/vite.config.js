import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Where the backend is. Matches `port` in config.yaml, and follows the same
// PORT override the backend honours - so moving the API off a busy port is
// two matching env vars rather than an edit in two files that then drift.
//
//   PORT=8004 .venv/Scripts/python.exe main.py
//   VITE_API_PORT=8004 npm run dev
const API_PORT = process.env.VITE_API_PORT || process.env.PORT || "8003";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Proxy keeps the frontend calling same-origin `/api/...` in dev.
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${API_PORT}`,
        changeOrigin: true,
        // Without this, a backend that is not running shows up as an opaque
        // 500 from Vite. Saying which port failed is the difference between
        // "the app is broken" and "start the backend".
        configure: (proxy) => {
          proxy.on("error", (err) => {
            console.error(
              `\n[vite] cannot reach the API on 127.0.0.1:${API_PORT} — ${err.message}` +
                `\n       start it with: PORT=${API_PORT} .venv/Scripts/python.exe main.py\n`,
            );
          });
        },
      },
    },
  },
});
