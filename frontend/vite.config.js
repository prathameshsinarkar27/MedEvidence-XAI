import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The repo-root .env is shared with the backend; only VITE_* vars are read here.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "VITE_");
  const target = env.VITE_API_PROXY_TARGET || "http://localhost:8000";
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: { "/api": { target, changeOrigin: true } },
    },
  };
});
