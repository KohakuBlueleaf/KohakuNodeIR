// Tree-sitter grammar for KohakuNodeIR (.kir)
//
// Corresponds to src/kohakunode/grammar/kir.lark (LALR version).
//
// Indentation is handled by an external scanner (src/scanner.c) that
// emits INDENT, DEDENT, and NEWLINE tokens — the same pattern used by
// tree-sitter-python.  All other whitespace and comments are consumed
// by the grammar's `extras` list so they are never visible to rules.

module.exports = grammar({
  name: "kir",

  // ---------------------------------------------------------------------------
  // External scanner tokens
  // INDENT, DEDENT, NEWLINE are produced by src/scanner.c.
  // ---------------------------------------------------------------------------
  externals: ($) => [$._indent, $._dedent, $._newline],

  // ---------------------------------------------------------------------------
  // Extras: tokens that may appear anywhere between other tokens.
  // Horizontal whitespace and line comments are always ignored.
  // ---------------------------------------------------------------------------
  extras: ($) => [$.comment, /[ \t]/],

  // ---------------------------------------------------------------------------
  // Conflict hints: the parser may see ambiguities around optional trailing
  // commas in lists; declare them so tree-sitter can resolve via GLR or
  // precedence.
  // ---------------------------------------------------------------------------
  conflicts: ($) => [
    [$.call_in_list],
    [$.call_out_list],
    [$.param_list],
    [$.def_output_list],
    [$.list_lit],
    [$.dict_lit],
  ],

  // ---------------------------------------------------------------------------
  // Entry point
  // ---------------------------------------------------------------------------
  rules: {
    // program  ::= ( _newline | statement )*
    program: ($) => repeat(choice($._newline, $.statement)),

    // -------------------------------------------------------------------------
    // Statements
    // -------------------------------------------------------------------------

    statement: ($) =>
      choice(
        seq($._simple_stmt, $._newline),
        $._compound_stmt
      ),

    _simple_stmt: ($) =>
      choice($.assignment, $.call_stmt, $.meta_annotation, $.mode_decl),

    _compound_stmt: ($) =>
      choice(
        $.namespace_def,
        $.subgraph_def,
        $.dataflow_block,
        $.typehint_block,
        $.try_except_block
      ),

    // -------------------------------------------------------------------------
    // Assignment:  name = expr  OR  name: type = expr
    // -------------------------------------------------------------------------
    assignment: ($) =>
      choice(
        seq(
          field("name", $.identifier),
          ":",
          field("type", $.type_expr),
          "=",
          field("value", $._expr)
        ),
        seq(field("name", $.identifier), "=", field("value", $._expr))
      ),

    // -------------------------------------------------------------------------
    // Type expressions
    // -------------------------------------------------------------------------
    type_expr: ($) => choice($.type_union, $._type_atom),

    type_union: ($) =>
      seq($._type_atom, repeat1(seq("|", $._type_atom))),

    _type_atom: ($) =>
      choice($.type_optional, $.type_any, $.type_name),

    type_optional: ($) => seq($.identifier, "?"),
    type_name: ($) => $.identifier,
    type_any: ($) => "_",

    // -------------------------------------------------------------------------
    // @typehint block
    // -------------------------------------------------------------------------
    typehint_block: ($) =>
      seq(
        "@typehint",
        ":",
        $._newline,
        $._indent,
        repeat1(choice($.typehint_entry, $._newline)),
        $._dedent
      ),

    typehint_entry: ($) =>
      seq(
        "(",
        optional($.type_list),
        ")",
        field("name", $.func_name),
        "(",
        optional($.type_list),
        ")",
        $._newline
      ),

    type_list: ($) =>
      seq($.type_expr, repeat(seq(",", $.type_expr)), optional(",")),

    // -------------------------------------------------------------------------
    // @try / @except block
    // -------------------------------------------------------------------------
    try_except_block: ($) =>
      seq(
        "@try",
        ":",
        $._newline,
        $._indent,
        repeat1(choice($.statement, $._newline)),
        $._dedent,
        "@except",
        ":",
        $._newline,
        $._indent,
        repeat1(choice($.statement, $._newline)),
        $._dedent
      ),

    // -------------------------------------------------------------------------
    // Expressions
    // -------------------------------------------------------------------------
    _expr: ($) => choice($._literal, $.identifier),

    // -------------------------------------------------------------------------
    // Literals
    // -------------------------------------------------------------------------
    _literal: ($) =>
      choice(
        $.integer,
        $.float,
        $.boolean,
        $.none,
        $.string,
        $.list_lit,
        $.dict_lit
      ),

    integer: (_) =>
      token(
        choice(
          /[+-]?0[xX][0-9a-fA-F]+/, // hex
          /[+-]?0[oO][0-7]+/, // octal
          /[+-]?0[bB][01]+/, // binary
          /[+-]?\d+/ // decimal
        )
      ),

    // FLOAT priority: match before integer when there is a decimal point or
    // exponent.  tree-sitter resolves longest-match automatically; the regex
    // ordering in the `choice` is enough.
    float: (_) =>
      token(
        choice(
          /[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?/,
          /[+-]?\d+[eE][+-]?\d+/
        )
      ),

    boolean: (_) => token(choice("True", "False")),

    none: (_) => token("None"),

    // String: triple-quoted variants listed first so the longer token wins.
    string: (_) =>
      token(
        choice(
          /"""(\\[\s\S]|[^\\"]|"(?!""))*"""/,
          /'''(\\[\s\S]|[^\\']|'(?!''))*'''/,
          /"(\\.|[^"\\])*"/,
          /'(\\.|[^'\\])*'/
        )
      ),

    list_lit: ($) =>
      choice(
        seq("[", "]"),
        seq("[", $._expr, repeat(seq(",", $._expr)), optional(","), "]")
      ),

    dict_lit: ($) =>
      choice(
        seq("{", "}"),
        seq(
          "{",
          $.dict_pair,
          repeat(seq(",", $.dict_pair)),
          optional(","),
          "}"
        )
      ),

    dict_pair: ($) => seq($._expr, ":", $._expr),

    // Meta tuple:  ( val , val ... )   — only valid in @meta values.
    meta_tuple: ($) =>
      seq(
        "(",
        $._meta_val,
        ",",
        $._meta_val,
        repeat(seq(",", $._meta_val)),
        optional(","),
        ")"
      ),

    // -------------------------------------------------------------------------
    // Identifier and wildcard
    // -------------------------------------------------------------------------
    identifier: (_) => /[a-zA-Z_][a-zA-Z0-9_]*/,

    wildcard: (_) => token("_"),

    // -------------------------------------------------------------------------
    // Label reference:  `name`
    // -------------------------------------------------------------------------
    label_ref: (_) => token(/`[a-zA-Z_][a-zA-Z0-9_]*`/),

    // -------------------------------------------------------------------------
    // Unified call statement:  (inputs) func_name (outputs)
    //
    // Covers:
    //   Regular calls  — (x, y)add(result)
    //   branch         — (cond)branch(`t`, `f`)
    //   switch         — (val)switch(0=>`a`, _=>`default`)
    //   jump           — ()jump(`target`)
    //   parallel       — ()parallel(`a`, `b`)
    // -------------------------------------------------------------------------
    call_stmt: ($) =>
      seq(
        "(",
        optional($.call_in_list),
        ")",
        field("name", $.func_name),
        "(",
        optional($.call_out_list),
        ")"
      ),

    // Dotted function name:  name  or  namespace.name
    func_name: ($) =>
      seq($.identifier, repeat(seq(".", $.identifier))),

    // Input list — positional and keyword args
    call_in_list: ($) =>
      seq(
        $._call_in_item,
        repeat(seq(",", $._call_in_item)),
        optional(",")
      ),

    _call_in_item: ($) => choice($.kwarg, $._expr),

    kwarg: ($) =>
      seq(field("key", $.identifier), "=", field("value", $._expr)),

    // Output list — names, wildcards, label refs, switch cases
    call_out_list: ($) =>
      seq(
        $._call_out_item,
        repeat(seq(",", $._call_out_item)),
        optional(",")
      ),

    // Ordering matters: switch variants must be tried before bare wildcard /
    // name so that "_ =>" is not reduced to a plain wildcard first.
    _call_out_item: ($) =>
      choice(
        $.out_switch_default,
        $.out_switch_case,
        $.out_label_ref,
        $.out_name,
        $.out_wildcard
      ),

    out_name: ($) => $.identifier,
    out_wildcard: (_) => token("_"),
    out_label_ref: ($) => $.label_ref,
    out_switch_case: ($) => seq($._expr, "=>", $.label_ref),
    out_switch_default: ($) => seq("_", "=>", $.label_ref),

    // -------------------------------------------------------------------------
    // Namespace definition
    //
    // Non-empty body:   name: NEWLINE INDENT stmts DEDENT
    // Empty body:       name: NEWLINE            (nothing after, before parent DEDENT)
    // -------------------------------------------------------------------------
    namespace_def: ($) =>
      choice(
        seq(
          field("name", $.identifier),
          ":",
          $._newline,
          $._indent,
          repeat1(choice($._newline, $.statement)),
          $._dedent
        ),
        seq(field("name", $.identifier), ":")
      ),

    // -------------------------------------------------------------------------
    // Subgraph definition
    //
    //   @def (params) name (outputs):
    //       body
    // -------------------------------------------------------------------------
    subgraph_def: ($) =>
      seq(
        "@def",
        "(",
        optional($.param_list),
        ")",
        field("name", $.identifier),
        "(",
        optional($.def_output_list),
        ")",
        ":",
        $._newline,
        $._indent,
        repeat1(choice($._newline, $.statement)),
        $._dedent
      ),

    param_list: ($) =>
      seq($.param, repeat(seq(",", $.param)), optional(",")),

    param: ($) =>
      choice(
        seq(field("name", $.identifier), "=", field("default", $._expr)),
        field("name", $.identifier)
      ),

    def_output_list: ($) =>
      seq($.identifier, repeat(seq(",", $.identifier)), optional(",")),

    // -------------------------------------------------------------------------
    // Dataflow block
    //
    //   @dataflow:
    //       statements...
    // -------------------------------------------------------------------------
    dataflow_block: ($) =>
      seq(
        "@dataflow",
        ":",
        $._newline,
        $._indent,
        repeat1(choice($._newline, $.statement)),
        $._dedent
      ),

    // -------------------------------------------------------------------------
    // Metadata annotation
    //
    //   @meta key=value key2=value2 ...
    // -------------------------------------------------------------------------
    meta_annotation: ($) => seq("@meta", repeat1($.meta_pair)),

    meta_pair: ($) =>
      seq(field("key", $.identifier), "=", field("value", $._meta_val)),

    _meta_val: ($) => choice($._literal, $.meta_tuple, $.identifier),

    // -------------------------------------------------------------------------
    // Mode declaration
    //
    //   @mode dataflow
    // -------------------------------------------------------------------------
    mode_decl: ($) => seq("@mode", field("mode", $.identifier)),

    // -------------------------------------------------------------------------
    // Comment:  # ...  to end of line
    // -------------------------------------------------------------------------
    comment: (_) => token(/#[^\r\n]*/),
  },
});
