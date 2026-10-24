import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { fileURLToPath, URL } from "node:url"

// The dev gallery (dev/): every example in every view; examples come from scripts/generate/examples.py.
export default defineConfig({
  root: fileURLToPath(new URL("./dev", import.meta.url)),
  publicDir: "examples",
  plugins: [vue()],
  resolve: {
    alias: [
      { find: /^@kohaku\/kir-graph$/, replacement: fileURLToPath(new URL("./src/index.js", import.meta.url)) },
      { find: /^@kohaku\/kir-graph\/style\.css$/, replacement: fileURLToPath(new URL("./src/styles/index.css", import.meta.url)) },
    ],
  },
  server: { port: 5199, host: "127.0.0.1" },
  build: { outDir: fileURLToPath(new URL("./dist-dev", import.meta.url)), emptyOutDir: true, chunkSizeWarningLimit: 3000 },
})
