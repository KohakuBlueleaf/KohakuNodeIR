import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";

import "element-plus/theme-chalk/dark/css-vars.css";
import "virtual:uno.css";
import "./styles/global.css";

// Enable Element Plus dark mode globally
document.documentElement.classList.add("dark");

const app = createApp(App);
app.use(createPinia());
app.mount("#app");
