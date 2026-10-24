/**
 * The model of a `.kirgraph` document without any drawing: plain ES modules
 * with no Vue or ELK import, for tools, servers and tests that read or edit
 * graphs (`@kohaku/kir-graph/model`).
 */

export { EXPRESSIONS, FORMATS, checkDocument, graphModel, inputExpr, nodeKey, outputNames, regionChain, regionNodes } from "./graph.js"
export { isStatement, statementTree } from "./tree.js"
export { edgeKey, edgeType, handleId, isBackEdge, parseHandle, sourceHandle, targetHandle } from "./ports.js"
export { formatLiteral, literalKind, parseLiteral, shortLiteral } from "./literal.js"
export { CTRL, UNTYPED, typeColor, typeHead, typeKind } from "./types.js"
