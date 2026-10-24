import { createApp } from "vue"
import { createPinia } from "pinia"
import elkWorker from "elkjs/lib/elk-worker.min.js?url"
import { configureElk } from "@kohaku/kir-graph"

import App from "./App.vue"

import "uno.css"
import "@kohaku/kir-graph/style.css"
import "./styles/base.css"
import "./styles/graph.css"
import "./styles/blocks.css"
import "./styles/sequence.css"
import "./styles/code.css"

// ELK lays graphs out in a worker, off the page's thread
configureElk({ workerUrl: elkWorker })

createApp(App).use(createPinia()).mount("#app")
