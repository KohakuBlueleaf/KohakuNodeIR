import { createApp } from "vue"
import { createPinia } from "pinia"

import App from "./App.vue"

import "uno.css"
import "./styles/base.css"
import "./styles/graph.css"
import "./styles/robo.css"
import "./styles/blocks.css"
import "./styles/sequence.css"
import "./styles/code.css"

createApp(App).use(createPinia()).mount("#app")
