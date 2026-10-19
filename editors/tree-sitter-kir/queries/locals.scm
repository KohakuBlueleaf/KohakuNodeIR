; A subgraph body is its own scope; the file is the outer scope.
(source_file) @local.scope
(subgraph) @local.scope

(parameter name: (identifier) @local.definition.parameter)
(subgraph_output name: (identifier) @local.definition.var)
(assignment name: (identifier) @local.definition.var)
(output_list (identifier) @local.definition.var)
(except_clause name: (identifier) @local.definition.var)

(input_list (identifier) @local.reference)
(keyword_argument value: (identifier) @local.reference)
(assignment value: (identifier) @local.reference)
(parameter default: (identifier) @local.reference)
(case value: (identifier) @local.reference)
