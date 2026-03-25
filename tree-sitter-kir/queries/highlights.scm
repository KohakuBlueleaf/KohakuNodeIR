; ── Comments ──────────────────────────────────────────────────────────────────
(comment) @comment

; ── String literals ───────────────────────────────────────────────────────────
(string) @string

; ── Numeric literals ──────────────────────────────────────────────────────────
(integer) @number
(float) @number

; ── Built-in constants ────────────────────────────────────────────────────────
(boolean) @constant.builtin
(none) @constant.builtin

; ── Wildcard placeholder ──────────────────────────────────────────────────────
(out_wildcard) @constant.builtin
(wildcard) @constant.builtin

; ── Label references  `name` ─────────────────────────────────────────────────
(label_ref) @label
(out_label_ref (label_ref) @label)
(out_switch_case (label_ref) @label)
(out_switch_default (label_ref) @label)

; ── Identifiers (default: variable) ──────────────────────────────────────────
(identifier) @variable

; ── Function calls  — highlight the function name ────────────────────────────
(call_stmt name: (func_name (identifier) @function))

; ── Built-in control-flow verbs ───────────────────────────────────────────────
; branch / switch / jump / parallel appear as func_name identifiers.
; We match them by value using #eq? predicates.
(call_stmt
  name: (func_name
    (identifier) @keyword.control
    (#any-of? @keyword.control "branch" "switch" "jump" "parallel")))

; ── Namespace labels ──────────────────────────────────────────────────────────
(namespace_def name: (identifier) @label)

; ── Assignment target ─────────────────────────────────────────────────────────
(assignment name: (identifier) @variable)

; ── Keyword argument keys ─────────────────────────────────────────────────────
(kwarg key: (identifier) @variable.parameter)

; ── @meta annotation ─────────────────────────────────────────────────────────
(meta_annotation "@meta" @attribute)
(meta_pair key: (identifier) @attribute)

; ── @dataflow keyword ─────────────────────────────────────────────────────────
(dataflow_block "@dataflow" @keyword)

; ── @typehint keyword ────────────────────────────────────────────────────────
(typehint_block "@typehint" @keyword)
(typehint_entry name: (func_name (identifier) @function))

; ── @try / @except keywords ──────────────────────────────────────────────────
(try_except_block "@try" @keyword.control)
(try_except_block "@except" @keyword.control)

; ── Type expressions ─────────────────────────────────────────────────────────
(type_name (identifier) @type)
(type_optional (identifier) @type)
(type_any) @type.builtin
"|" @operator

; ── Typed assignment type annotation ─────────────────────────────────────────
(assignment type: (type_expr) @type)

; ── @mode keyword ─────────────────────────────────────────────────────────────
(mode_decl "@mode" @keyword)
(mode_decl mode: (identifier) @constant)

; ── @def keyword + subgraph name ─────────────────────────────────────────────
(subgraph_def "@def" @keyword)
(subgraph_def name: (identifier) @function.definition)

; ── Subgraph parameter names ─────────────────────────────────────────────────
(param name: (identifier) @variable.parameter)

; ── Punctuation ───────────────────────────────────────────────────────────────
"(" @punctuation.bracket
")" @punctuation.bracket
"[" @punctuation.bracket
"]" @punctuation.bracket
"{" @punctuation.bracket
"}" @punctuation.bracket
":" @punctuation.delimiter
"," @punctuation.delimiter
"=" @operator
"=>" @operator
"." @punctuation.delimiter
