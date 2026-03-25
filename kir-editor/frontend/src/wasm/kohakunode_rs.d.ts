/* tslint:disable */
/* eslint-disable */

/**
 * Run auto-layout on a KirGraph JSON string, return updated JSON.
 */
export function auto_layout(graph_json: string): string;

/**
 * Compile dataflow ordering on a Program JSON string.
 */
export function compile_dataflow(program_json: string): string;

/**
 * Compile a KirGraph JSON string (L1) to a KIR Program JSON string (L2).
 */
export function compile_kirgraph(kirgraph_json: string): string;

/**
 * Decompile a Program JSON string (L2) back to a KirGraph JSON string (L1).
 */
export function decompile(program_json: string): string;

/**
 * Parse KIR source and extract a graph as a JSON string.
 */
export function kir_to_graph(source: string): string;

/**
 * Run layout optimizer on a KirGraph JSON string, return updated JSON.
 */
export function optimize_layout(graph_json: string, max_iterations: number): string;

/**
 * Parse KIR source text and return the AST as a JSON string.
 */
export function parse_kir(text: string): string;

/**
 * Score a KirGraph layout, return the total score.
 */
export function score_layout(graph_json: string): number;

/**
 * Initialise `console_error_panic_hook` for better WASM error messages.
 */
export function start(): void;

/**
 * Strip all `@meta` annotations from a Program JSON string.
 */
export function strip_meta(program_json: string): string;

/**
 * Serialize a Program JSON string back to KIR source text.
 */
export function write_kir(program_json: string): string;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly auto_layout: (a: number, b: number) => [number, number, number, number];
    readonly compile_dataflow: (a: number, b: number) => [number, number, number, number];
    readonly compile_kirgraph: (a: number, b: number) => [number, number, number, number];
    readonly decompile: (a: number, b: number) => [number, number, number, number];
    readonly kir_to_graph: (a: number, b: number) => [number, number, number, number];
    readonly optimize_layout: (a: number, b: number, c: number) => [number, number, number, number];
    readonly parse_kir: (a: number, b: number) => [number, number, number, number];
    readonly score_layout: (a: number, b: number) => [number, number, number];
    readonly start: () => void;
    readonly strip_meta: (a: number, b: number) => [number, number, number, number];
    readonly write_kir: (a: number, b: number) => [number, number, number, number];
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __externref_table_dealloc: (a: number) => void;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
