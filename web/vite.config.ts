import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Served from https://moddingtavern.github.io/TavernMods/, so asset paths are relative.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: {
    rollupOptions: {
      input: { index: path.resolve(__dirname, "index.html"), builder: path.resolve(__dirname, "builder.html") },
    },
  },
})
