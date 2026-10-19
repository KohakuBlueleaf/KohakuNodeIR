import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import UnoCSS from "unocss/vite"
import { fileURLToPath, URL } from "node:url"

// Backend the dev server proxies to; set KIR_API_TARGET when it runs elsewhere.
const apiTarget = process.env.KIR_API_TARGET || "http://127.0.0.1:48888"

export default defineConfig({
  plugins: [vue(), UnoCSS()],
  resolve: {
    alias: [{ find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) }],
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
