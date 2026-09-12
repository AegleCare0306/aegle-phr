import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// No `define` block and no VITE_* defaults: nothing configuration-shaped is
// baked into the bundle. The backend URL and access key arrive at runtime
// via query parameters and live in localStorage. Anything compiled into a
// Vercel bundle is public.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
