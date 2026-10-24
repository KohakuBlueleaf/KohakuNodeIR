/**
 * kir-graph: KIR programs drawn from a `.kirgraph` document (version 3).
 *
 *   import { KirGraph, configureElk } from "@kohaku/kir-graph"
 *   import "@kohaku/kir-graph/style.css"
 *
 * `KirGraph` draws one graph in a view (`VIEW_NAMES`) with an overlay of live
 * data; the model, geometry and layout functions are exported for tools that
 * need them without the component.
 */

export { default as KirGraph } from "./render/KirGraph.vue"
export { default as Icon } from "./render/Icon.vue"
export { GRAPH_VIEWS, STATEMENT_VIEWS, VIEW_NAMES, viewData } from "./views.js"
export { FORMATS, checkDocument, graphModel, inputExpr, nodeKey, outputNames, regionChain, regionNodes } from "./model/graph.js"
export { isStatement, statementTree } from "./model/tree.js"
export { edgeKey, isBackEdge } from "./model/ports.js"
export { formatLiteral, shortLiteral } from "./model/literal.js"
export { typeColor } from "./model/types.js"
export { fontsReady, resetMeasure, textWidth } from "./geometry/measure.js"
export { configureElk } from "./layout/elk.js"
export { layoutView, planLayout, readLayout } from "./layout/build.js"
export { checkLayout, layoutOk } from "./layout/checks.js"
export { STATUSES } from "./render/kinds.js"
