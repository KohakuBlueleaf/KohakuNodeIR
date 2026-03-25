import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import UnoCSS from "unocss/vite";
import AutoImport from "unplugin-auto-import/vite";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";

export default defineConfig({
  plugins: [
    vue(),
    UnoCSS(),
    AutoImport({
      imports: ["vue", "vue-router", "pinia"],
      resolvers: [ElementPlusResolver()],
    }),
    Components({
      resolvers: [ElementPlusResolver()],
    }),
  ],
  optimizeDeps: {
    exclude: ['kohakunode_rs'],
  },
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://localhost:48888",
        changeOrigin: true,
        // Also proxy WebSocket connections on this path prefix
        ws: true,
      },
    },
  },
});
