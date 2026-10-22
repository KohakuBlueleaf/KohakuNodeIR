/**
 * Tree-sitter grammar for KIR v2 (Kohaku Node IR).
 *
 * Mirrors docs/spec/language.md and src/kohakunode/syntax/kir.lark.
 * Indentation comes from the external scanner (src/scanner.c): INDENT, DEDENT
 * and NEWLINE are zero-width tokens, and the line breaks themselves are extras.
 * Inside ( [ { no external token is valid, so line breaks there are plain
 * whitespace. The scanner also lexes the directives, so they end at a word
 * boundary (`@metax` is an error).
 */

const commaSep1 = (rule) => seq(rule, repeat(seq(",", rule)), optional(","));

const DIRECTIVES = ["@use", "@def", "@meta", "@hint", "@mode", "@dataflow", "@try", "@except", "@typehint", "@import", "@export"];

module.exports = grammar({
  name: "kir",

  // The order must match `enum TokenType` in src/scanner.c.
  externals: ($) => [$._indent, $._dedent, $._newline, ...DIRECTIVES, $._error_sentinel],

  extras: ($) => [$.comment, /\s/],

  word: ($) => $.identifier,

  // Never identifiers, even where the keyword itself is not valid.
  reserved: {
    global: (_) => ["True", "False", "None", "_"],
  },

  rules: {
    source_file: ($) => seq(
      repeat(seq(choice($.use_directive, $.import_directive, $.export_directive), $._newline)),
      repeat($._statement),
    ),

    _statement: ($) => choice(seq($._simple_statement, $._newline), $._compound_statement),

    _simple_statement: ($) =>
      choice($.assignment, $.call, $.meta_directive, $.hint_directive, $.mode_directive),

    _compound_statement: ($) =>
      choice($.namespace, $.subgraph, $.dataflow_block, $.try_block, $.typehint_block),

    block: ($) => seq($._indent, repeat1($._statement), $._dedent),

    // ------------------------------------------------------------ simple

    use_directive: ($) =>
      seq("@use", field("library", $.string), optional(seq("as", field("alias", $.identifier)))),

    import_directive: ($) =>
      seq("@import", field("module", $.string), "as", field("alias", $.identifier)),

    export_directive: ($) => seq("@export", field("name", $.identifier)),

    assignment: ($) =>
      seq(
        field("name", $.identifier),
        optional(seq(":", field("type", $._type))),
        "=",
        field("value", $._expression),
      ),

    call: ($) =>
      seq(field("inputs", $.input_list), field("node", $.node_name), field("outputs", $.output_list)),

    node_name: ($) => seq($.identifier, repeat(seq(".", $.identifier))),

    input_list: ($) => seq("(", optional(commaSep1(choice($._expression, $.keyword_argument))), ")"),

    keyword_argument: ($) => seq(field("name", $.identifier), "=", field("value", $._expression)),

    output_list: ($) => seq("(", optional(commaSep1(choice($.identifier, $.wildcard, $.label, $.case))), ")"),

    case: ($) =>
      seq(field("value", choice($._literal, $.identifier, $.wildcard)), "=>", field("label", $.label)),

    meta_directive: ($) => seq("@meta", repeat1($.attribute)),

    hint_directive: ($) => seq("@hint", repeat1($.attribute)),

    attribute: ($) => seq(field("key", $.identifier), "=", field("value", $._attribute_value)),

    _attribute_value: ($) => choice($._literal, $.identifier, $.tuple),

    // Python tuple syntax: `()`, `(x,)`, `(x, y)`.
    tuple: ($) =>
      seq(
        "(",
        optional(seq($._attribute_value, ",", optional(commaSep1($._attribute_value)))),
        ")",
      ),

    mode_directive: ($) => seq("@mode", field("mode", $.identifier)),

    // ------------------------------------------------------------ compound

    namespace: ($) => seq(field("name", $.identifier), ":", choice(field("body", $.block), $._newline)),

    subgraph: ($) =>
      seq(
        "@def",
        field("parameters", $.parameter_list),
        field("name", $.identifier),
        field("outputs", $.subgraph_output_list),
        ":",
        field("body", $.block),
      ),

    parameter_list: ($) => seq("(", optional(commaSep1($.parameter)), ")"),

    parameter: ($) =>
      seq(
        field("name", $.identifier),
        optional(seq(":", field("type", $._type))),
        optional(seq("=", field("default", $._expression))),
      ),

    subgraph_output_list: ($) => seq("(", optional(commaSep1($.subgraph_output)), ")"),

    subgraph_output: ($) => seq(field("name", $.identifier), optional(seq(":", field("type", $._type)))),

    dataflow_block: ($) => seq("@dataflow", ":", field("body", $.block)),

    try_block: ($) => seq("@try", ":", field("body", $.block), field("handler", $.except_clause)),

    except_clause: ($) => seq("@except", optional(field("name", $.identifier)), ":", field("body", $.block)),

    typehint_block: ($) => seq("@typehint", ":", $._indent, repeat1($.signature), $._dedent),

    signature: ($) =>
      seq(field("inputs", $.type_list), field("node", $.node_name), field("outputs", $.type_list), $._newline),

    type_list: ($) => seq("(", optional(commaSep1($._type)), ")"),

    // ------------------------------------------------------------ types

    _type: ($) => choice($.union_type, $._type_atom),

    union_type: ($) => seq($._type_atom, repeat1(seq("|", $._type_atom))),

    _type_atom: ($) =>
      choice(
        alias($.wildcard, $.any_type),
        alias($.none, $.type_identifier),
        $._type_identifier,
        $.generic_type,
        $.optional_type,
      ),

    _type_identifier: ($) => choice(alias($.identifier, $.type_identifier), $.qualified_type),

    qualified_type: ($) => seq($.identifier, repeat1(seq(".", $.identifier))),

    generic_type: ($) =>
      seq(field("name", $._type_identifier), "[", $._type, repeat(seq(",", $._type)), "]"),

    optional_type: ($) => seq(choice($._type_identifier, $.generic_type), "?"),

    // ------------------------------------------------------------ values

    _expression: ($) => choice($._literal, $.identifier),

    _literal: ($) => choice($.integer, $.float, $.true, $.false, $.none, $.string, $.list, $.dict),

    list: ($) => seq("[", optional(commaSep1($._literal)), "]"),

    dict: ($) => seq("{", optional(commaSep1($.dict_entry)), "}"),

    dict_entry: ($) => seq(field("key", $._literal), ":", field("value", $._literal)),

    // ------------------------------------------------------------ tokens

    identifier: (_) => /[A-Za-z_][A-Za-z0-9_]*/,

    wildcard: (_) => "_",

    label: (_) => token(seq("`", /[A-Za-z_][A-Za-z0-9_]*/, "`")),

    true: (_) => "True",
    false: (_) => "False",
    none: (_) => "None",

    // ASCII digits only (`\d` would also match other Unicode digits).
    integer: (_) =>
      token(seq(optional(/[+-]/), choice(/0[xX][0-9a-fA-F]+/, /0[oO][0-7]+/, /0[bB][01]+/, /[0-9]+/))),

    float: (_) =>
      token(
        seq(
          optional(/[+-]/),
          choice(/[0-9]+\.[0-9]*([eE][+-]?[0-9]+)?/, /\.[0-9]+([eE][+-]?[0-9]+)?/, /[0-9]+[eE][+-]?[0-9]+/),
        ),
      ),

    string: (_) =>
      token(
        choice(
          seq('"""', repeat(choice(/[^"\\]/, /\\(.|\r?\n)/, /"[^"\\]/, /""[^"\\]/)), '"""'),
          seq("'''", repeat(choice(/[^'\\]/, /\\(.|\r?\n)/, /'[^'\\]/, /''[^'\\]/)), "'''"),
          seq('"', repeat(choice(/[^"\\\r\n]/, /\\./)), '"'),
          seq("'", repeat(choice(/[^'\\\r\n]/, /\\./)), "'"),
        ),
      ),

    comment: (_) => token(seq("#", /[^\r\n]*/)),
  },
});
