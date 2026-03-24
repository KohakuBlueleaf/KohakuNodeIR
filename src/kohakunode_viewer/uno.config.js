import { defineConfig, presetUno, presetAttributify, presetIcons } from "unocss";

export default defineConfig({
  presets: [presetUno(), presetAttributify(), presetIcons()],
  theme: {
    colors: {
      "node-bg": "#1e1e2e",
      "node-header": "#313244",
      "node-border": "#45475a",
      "node-selected": "#89b4fa",
      "port-data": "#89b4fa",
      "port-control": "#fab387",
      "wire-data": "#89b4fa",
      "wire-control": "#fab387",
      "canvas-bg": "#11111b",
      "canvas-grid": "#1e1e2e",
      "editor-panel": "#181825",
    },
  },
});
