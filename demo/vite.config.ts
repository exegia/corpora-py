import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { reactRouter } from "@react-router/dev/vite";
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss(), reactRouter()],
  root: "src/mainview",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
		port: 5173,
		strictPort: true,
	},
});
