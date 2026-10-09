import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// One ES module that HA loads as a custom panel (see custom_components/vafabmiljo/panel.py).
export default defineConfig({
  plugins: [react()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "../custom_components/vafabmiljo/www",
    emptyOutDir: true,
    lib: { entry: "src/main.tsx", formats: ["es"], fileName: () => "panel.js" },
  },
});
