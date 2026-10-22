; Patterns are written to be mutually exclusive, so the result does not depend
; on whether an editor lets the first or the last matching pattern win.

; Comments: `##` is a section comment.
((comment) @comment.documentation
  (#match? @comment.documentation "^##"))
((comment) @comment
  (#not-match? @comment "^##"))

; Directives
[
  "@use"
  "@import"
  "@export"
  "@def"
  "@meta"
  "@hint"
  "@mode"
  "@dataflow"
  "@try"
  "@except"
  "@typehint"
] @keyword.directive

"as" @keyword

; Node names: builtins, library prefixes, nodes.
((node_name . (identifier) @function.builtin .)
  (#any-of? @function.builtin "branch" "switch" "jump" "parallel" "each" "collect"))
(node_name (identifier) @module . (identifier))
((node_name (identifier) @function.call .)
  (#not-any-of? @function.call "branch" "switch" "jump" "parallel" "each" "collect"))

(subgraph name: (identifier) @function)

; Labels and namespaces
(label) @label
(namespace name: (identifier) @label)

; Variables
(assignment name: (identifier) @variable)
(assignment value: (identifier) @variable)
(input_list (identifier) @variable)
(keyword_argument name: (identifier) @variable.parameter)
(keyword_argument value: (identifier) @variable)
(output_list (identifier) @variable)
(case value: (identifier) @variable)
(collect_capture value: (identifier) @variable)
(collect_capture target: (identifier) @variable)
(parameter name: (identifier) @variable.parameter)
(parameter default: (identifier) @variable)
(subgraph_output name: (identifier) @variable)
(except_clause name: (identifier) @variable)
(wildcard) @variable.builtin

; Directive arguments
(use_directive alias: (identifier) @module)
(import_directive alias: (identifier) @module)
(export_directive name: (identifier) @function)
(qualified_type (identifier) @module . (identifier))
(qualified_type (identifier) @type .)
(mode_directive mode: (identifier) @constant)
(attribute key: (identifier) @property)
(attribute value: (identifier) @variable)
(tuple (identifier) @variable)

; Types
((type_identifier) @type.builtin
  (#any-of? @type.builtin "int" "float" "str" "bool" "None" "list" "dict"))
((type_identifier) @type
  (#not-any-of? @type "int" "float" "str" "bool" "None" "list" "dict"))
(any_type) @type.builtin

; Literals
(string) @string
[(integer) (float)] @number
[(true) (false)] @boolean
(none) @constant.builtin

; Operators and punctuation
["=" "=>" "->" "|" "?"] @operator
["(" ")" "[" "]" "{" "}"] @punctuation.bracket
["," ":" "."] @punctuation.delimiter
