import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import UnoCSS from "unocss/vite"
import { fileURLToPath, URL } from "node:url"

// Backend the dev server proxies to; set KIR_API_TARGET when it runs elsewhere.
const apiTarget = process.env.KIR_API_TARGET || "http://127.0.0.1:48888"
const graphLib = (path) => fileURLToPath(new URL(`../../../packages/kir-graph/${path}`, import.meta.url))

export default defineConfig({
  plugins: [vue(), UnoCSS()],
  resolve: {
    alias: [
      { find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) },
      // The display library from its source in this repository (packages/kir-graph)
      { find: /^@kohaku\/kir-graph$/, replacement: graphLib("src/index.js") },
      { find: /^@kohaku\/kir-graph\/style\.css$/, replacement: graphLib("src/styles/index.css") },
    ],
    // One copy of what the library shares with the editor, the editor's
    dedupe: ["vue", "@vue-flow/core", "@vue-flow/background", "@vue-flow/controls", "@vue-flow/minimap", "elkjs"],
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("elkjs")) return "elk"
          if (id.includes("@codemirror") || id.includes("codemirror")) return "codemirror"
          if (id.includes("@vue-flow")) return "vue-flow"
          if (id.includes("node_modules/vue") || id.includes("node_modules/pinia")) return "vue-vendor"
        },
      },
    },
  },
})
