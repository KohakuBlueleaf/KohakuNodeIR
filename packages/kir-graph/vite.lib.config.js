import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { fileURLToPath, URL } from "node:url"

// The library as consumers install it: dist/kir-graph.js (ES module, components compiled) and
// dist/kir-graph.css; Vue, Vue Flow and ELK stay the consumer's own (peer dependencies).
const PEERS = [/^vue$/, /^@vue-flow\//, /^elkjs(\/|$)/]

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: fileURLToPath(new URL("./dist", import.meta.url)),
    emptyOutDir: true,
    sourcemap: true,
    // The stylesheet is an entry of its own, so it is not inlined into the module
    cssCodeSplit: true,
    lib: {
      entry: {
        "kir-graph": fileURLToPath(new URL("./src/index.js", import.meta.url)),
        "kir-graph-style": fileURLToPath(new URL("./src/styles/index.css", import.meta.url)),
      },
      formats: ["es"],
    },
    rolldownOptions: { external: (id) => PEERS.some((p) => p.test(id)) },
  },
})
