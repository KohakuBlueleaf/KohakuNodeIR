import { createApp } from "vue"
import workerUrl from "elkjs/lib/elk-worker.min.js?url"

import { configureElk } from "@kohaku/kir-graph"
import "@kohaku/kir-graph/style.css"

import App from "./App.vue"
import "./shell.css"

configureElk({ workerUrl })
createApp(App).mount("#app")
