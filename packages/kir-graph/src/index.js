/**
 * kir-graph: KIR programs drawn from a `.kirgraph` document (version 3).
 *
 *   import { KirGraph, configureElk } from "@kohaku/kir-graph"
 *   import "@kohaku/kir-graph/style.css"
 *
 * `KirGraph` draws one graph in a view (`VIEW_NAMES`) with an overlay of live
 * data, or edits it (`editable`); the model, geometry and layout functions
 * are exported for tools that need them without the component; the model
 * alone, without Vue or ELK, is `@kohaku/kir-graph/model`.
 */

export { default as KirGraph } from "./render/KirGraph.vue"
export { default as Icon } from "./render/Icon.vue"
export { default as LiteralWidget } from "./render/flow/LiteralWidget.vue"
export { GRAPH_VIEWS, STATEMENT_VIEWS, VIEW_NAMES, viewData } from "./views.js"
export * from "./model/index.js"
export { fontsReady, resetMeasure, textWidth } from "./geometry/measure.js"
export { configureElk } from "./layout/elk.js"
export { layoutView, planLayout, readLayout } from "./layout/build.js"
export { createMemory, keepLayout, placeLayout } from "./layout/place.js"
export { orthoRoute } from "./layout/route.js"
export { checkLayout, layoutOk } from "./layout/checks.js"
export { STATUSES } from "./render/kinds.js"
