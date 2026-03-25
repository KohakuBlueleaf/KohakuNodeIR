//! KIR serializer: walks a [`Program`] AST and emits valid `.kir` source text.
//!
//! This is a port of `src/kohakunode/serializer/writer.py`.
//! The public entry point is [`write`].

#[cfg(feature = "pyo3")]
pub mod pyo3;

use crate::ast::{
    Assignment, Branch, DataflowBlock, Expression, FuncCall, Jump, Literal, MetaAnnotation,
    Namespace, OutputTarget, Parallel, Parameter, Program, Statement, SubgraphDef, Switch,
    TryExcept, TypeExpr, TypeHintBlock, Value,
};

const INDENT: &str = "    ";

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Serialize a [`Program`] to `.kir` source text.
///
/// The returned string always ends with a single newline.
pub fn write(program: &Program) -> String {
    let mut lines: Vec<String> = Vec::new();

    if let Some(mode) = &program.mode {
        lines.push(write_mode_decl_str(mode));
        lines.push(String::new());
    }

    if let Some(typehints) = &program.typehints {
        if !typehints.is_empty() {
            let block = TypeHintBlock {
                entries: typehints.clone(),
                line: None,
            };
            lines.extend(write_typehint_block(&block, 0));
            lines.push(String::new());
        }
    }

    for stmt in &program.body {
        lines.extend(write_statement(stmt, 0));
    }

    let mut text = lines.join("\n");
    if !text.is_empty() && !text.ends_with('\n') {
        text.push('\n');
    }
    text
}

// ---------------------------------------------------------------------------
// Statement dispatcher
// ---------------------------------------------------------------------------

fn write_statement(stmt: &Statement, indent_level: usize) -> Vec<String> {
    match stmt {
        Statement::ModeDecl(node) => vec![write_mode_decl_str(&node.mode)],
        Statement::Assignment(node) => write_assignment(node, indent_level),
        Statement::FuncCall(node) => write_func_call(node, indent_level),
        Statement::Branch(node) => write_branch(node, indent_level),
        Statement::Switch(node) => write_switch(node, indent_level),
        Statement::Jump(node) => write_jump(node, indent_level),
        Statement::Parallel(node) => write_parallel(node, indent_level),
        Statement::Namespace(node) => write_namespace(node, indent_level),
        Statement::SubgraphDef(node) => write_subgraph_def(node, indent_level),
        Statement::DataflowBlock(node) => write_dataflow_block(node, indent_level),
        Statement::TypeHintBlock(node) => write_typehint_block(node, indent_level),
        Statement::TryExcept(node) => write_try_except(node, indent_level),
    }
}

// ---------------------------------------------------------------------------
// Statement writers
// ---------------------------------------------------------------------------

fn write_assignment(node: &Assignment, indent_level: usize) -> Vec<String> {
    let mut lines = write_meta_lines(node.metadata.as_deref(), indent_level);
    let prefix = indent(indent_level);
    let value_str = write_expression(&node.value);
    if let Some(ty) = &node.type_annotation {
        lines.push(format!(
            "{}{}: {} = {}",
            prefix,
            node.target,
            write_type_expr(ty),
            value_str
        ));
    } else {
        lines.push(format!("{}{} = {}", prefix, node.target, value_str));
    }
    lines
}

fn write_func_call(node: &FuncCall, indent_level: usize) -> Vec<String> {
    let mut lines = write_meta_lines(node.metadata.as_deref(), indent_level);
    let prefix = indent(indent_level);
    let inputs_str = format_input_list(&node.inputs);
    let outputs_str = format_output_list(&node.outputs);
    lines.push(format!(
        "{}({}){}({})",
        prefix, inputs_str, node.func_name, outputs_str
    ));
    lines
}

fn write_branch(node: &Branch, indent_level: usize) -> Vec<String> {
    let mut lines = write_meta_lines(node.metadata.as_deref(), indent_level);
    let prefix = indent(indent_level);
    let cond_str = write_expression(&node.condition);
    lines.push(format!(
        "{}({})branch(`{}`, `{}`)",
        prefix, cond_str, node.true_label, node.false_label
    ));
    lines
}

fn write_switch(node: &Switch, indent_level: usize) -> Vec<String> {
    let mut lines = write_meta_lines(node.metadata.as_deref(), indent_level);
    let prefix = indent(indent_level);
    let val_str = write_expression(&node.value);

    let mut case_parts: Vec<String> = node
        .cases
        .iter()
        .map(|(expr, label)| format!("{}=>`{}`", write_expression(expr), label))
        .collect();

    if let Some(default_label) = &node.default_label {
        case_parts.push(format!("_=>`{}`", default_label));
    }

    let cases_str = case_parts.join(", ");
    lines.push(format!("{}({})switch({})", prefix, val_str, cases_str));
    lines
}

fn write_jump(node: &Jump, indent_level: usize) -> Vec<String> {
    let mut lines = write_meta_lines(node.metadata.as_deref(), indent_level);
    let prefix = indent(indent_level);
    lines.push(format!("{}()jump(`{}`)", prefix, node.target));
    lines
}

fn write_parallel(node: &Parallel, indent_level: usize) -> Vec<String> {
    let mut lines = write_meta_lines(node.metadata.as_deref(), indent_level);
    let prefix = indent(indent_level);
    let labels_str = node
        .labels
        .iter()
        .map(|lbl| format!("`{}`", lbl))
        .collect::<Vec<_>>()
        .join(", ");
    lines.push(format!("{}()parallel({})", prefix, labels_str));
    lines
}

fn write_namespace(node: &Namespace, indent_level: usize) -> Vec<String> {
    let prefix = indent(indent_level);
    let mut lines = vec![format!("{}{}:", prefix, node.name)];
    for stmt in &node.body {
        lines.extend(write_statement(stmt, indent_level + 1));
    }
    lines
}

fn write_subgraph_def(node: &SubgraphDef, indent_level: usize) -> Vec<String> {
    let prefix = indent(indent_level);
    let params_str = format_param_list(&node.params);
    let outputs_str = node.outputs.join(", ");
    let mut lines = vec![format!(
        "{}@def {}({})({})",
        prefix, node.name, params_str, outputs_str
    )];
    for stmt in &node.body {
        lines.extend(write_statement(stmt, indent_level + 1));
    }
    lines.push(String::new()); // blank line after each @def block
    lines
}

fn write_dataflow_block(node: &DataflowBlock, indent_level: usize) -> Vec<String> {
    let prefix = indent(indent_level);
    let mut lines = vec![format!("{}@dataflow:", prefix)];
    for stmt in &node.body {
        lines.extend(write_statement(stmt, indent_level + 1));
    }
    lines
}

fn write_typehint_block(node: &TypeHintBlock, indent_level: usize) -> Vec<String> {
    let prefix = indent(indent_level);
    let inner_prefix = indent(indent_level + 1);
    let mut lines = vec![format!("{}@typehint:", prefix)];
    for entry in &node.entries {
        let inputs_str = entry
            .input_types
            .iter()
            .map(write_type_expr)
            .collect::<Vec<_>>()
            .join(", ");
        let outputs_str = entry
            .output_types
            .iter()
            .map(write_type_expr)
            .collect::<Vec<_>>()
            .join(", ");
        lines.push(format!(
            "{}({}){}({})",
            inner_prefix, inputs_str, entry.func_name, outputs_str
        ));
    }
    lines
}

fn write_try_except(node: &TryExcept, indent_level: usize) -> Vec<String> {
    let mut lines = write_meta_lines(node.metadata.as_deref(), indent_level);
    let prefix = indent(indent_level);
    lines.push(format!("{}@try:", prefix));
    for stmt in &node.try_body {
        lines.extend(write_statement(stmt, indent_level + 1));
    }
    lines.push(format!("{}@except:", prefix));
    for stmt in &node.except_body {
        lines.extend(write_statement(stmt, indent_level + 1));
    }
    lines
}

// ---------------------------------------------------------------------------
// Non-statement writers
// ---------------------------------------------------------------------------

fn write_mode_decl_str(mode: &str) -> String {
    format!("@mode {}", mode)
}

fn write_type_expr(ty: &TypeExpr) -> String {
    if let Some(members) = &ty.union_of {
        return members
            .iter()
            .map(write_type_expr)
            .collect::<Vec<_>>()
            .join("|");
    }
    if ty.is_optional {
        format!("{}?", ty.name)
    } else {
        ty.name.clone()
    }
}

fn write_meta(meta: &MetaAnnotation, indent_level: usize) -> String {
    let prefix = indent(indent_level);
    // Sort keys for deterministic output.
    let mut keys: Vec<&String> = meta.data.keys().collect();
    keys.sort();
    let pairs: Vec<String> = keys
        .iter()
        .map(|k| format!("{}={}", k, write_meta_value(&meta.data[*k])))
        .collect();
    format!("{}@meta {}", prefix, pairs.join(" "))
}

fn write_expression(expr: &Expression) -> String {
    match expr {
        Expression::Literal(lit) => write_literal(lit),
        Expression::Identifier(id) => id.name.clone(),
        Expression::LabelRef(lr) => format!("`{}`", lr.name),
        Expression::KeywordArg(kw) => {
            format!("{}={}", kw.name, write_expression(&kw.value))
        }
        Expression::Wildcard(_) => "_".to_string(),
    }
}

fn write_literal(lit: &Literal) -> String {
    match &lit.value {
        Value::None => "None".to_string(),
        Value::Bool(b) => if *b { "True" } else { "False" }.to_string(),
        Value::Int(i) => i.to_string(),
        Value::Float(f) => {
            // Preserve a decimal point so the output is unambiguously a float.
            let text = format!("{:?}", f);
            // Rust's {:?} for floats always includes a decimal point.
            text
        }
        Value::Str(s) => {
            if s.contains('\n') {
                // Multi-line: use triple quotes
                let escaped = s.replace('\\', "\\\\").replace("\"\"\"", "\\\"\\\"\\\"");
                format!("\"\"\"{}\"\"\"", escaped)
            } else {
                // Single-line: use double quotes
                let escaped = s.replace('\\', "\\\\").replace('"', "\\\"");
                format!("\"{}\"", escaped)
            }
        }
        Value::List(items) => {
            // Wrap items in Literal nodes with dummy type to reuse write_literal,
            // but since Value is the recursive type, we write them directly.
            let parts: Vec<String> = items.iter().map(write_value).collect();
            format!("[{}]", parts.join(", "))
        }
        Value::Dict(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let parts: Vec<String> = keys
                .iter()
                .map(|k| {
                    let k_str = write_value(&Value::Str((*k).clone()));
                    let v_str = write_value(&map[*k]);
                    format!("{}: {}", k_str, v_str)
                })
                .collect();
            format!("{{{}}}", parts.join(", "))
        }
    }
}

/// Serialize a raw [`Value`] (used for list/dict contents and meta values).
fn write_value(value: &Value) -> String {
    match value {
        Value::None => "None".to_string(),
        Value::Bool(b) => if *b { "True" } else { "False" }.to_string(),
        Value::Int(i) => i.to_string(),
        Value::Float(f) => format!("{:?}", f),
        Value::Str(s) => {
            if s.contains('\n') {
                let escaped = s.replace('\\', "\\\\").replace("\"\"\"", "\\\"\\\"\\\"");
                format!("\"\"\"{}\"\"\"", escaped)
            } else {
                let escaped = s.replace('\\', "\\\\").replace('"', "\\\"");
                format!("\"{}\"", escaped)
            }
        }
        Value::List(items) => {
            let parts: Vec<String> = items.iter().map(write_value).collect();
            format!("[{}]", parts.join(", "))
        }
        Value::Dict(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let parts: Vec<String> = keys
                .iter()
                .map(|k| {
                    let k_str = write_value(&Value::Str((*k).clone()));
                    let v_str = write_value(&map[*k]);
                    format!("{}: {}", k_str, v_str)
                })
                .collect();
            format!("{{{}}}", parts.join(", "))
        }
    }
}

fn write_meta_value(value: &Value) -> String {
    match value {
        Value::None => "None".to_string(),
        Value::Bool(b) => if *b { "True" } else { "False" }.to_string(),
        Value::Int(i) => i.to_string(),
        Value::Float(f) => format!("{:?}", f),
        Value::Str(s) => {
            let escaped = s.replace('\\', "\\\\").replace('"', "\\\"");
            format!("\"{}\"", escaped)
        }
        Value::List(items) => {
            let inner: Vec<String> = items.iter().map(write_meta_value).collect();
            format!("[{}]", inner.join(", "))
        }
        Value::Dict(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let parts: Vec<String> = keys
                .iter()
                .map(|k| {
                    let k_str = write_meta_value(&Value::Str((*k).clone()));
                    let v_str = write_meta_value(&map[*k]);
                    format!("{}: {}", k_str, v_str)
                })
                .collect();
            format!("{{{}}}", parts.join(", "))
        }
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn indent(level: usize) -> String {
    INDENT.repeat(level)
}

fn write_meta_lines(metadata: Option<&[MetaAnnotation]>, indent_level: usize) -> Vec<String> {
    match metadata {
        Some(metas) if !metas.is_empty() => {
            metas.iter().map(|m| write_meta(m, indent_level)).collect()
        }
        _ => Vec::new(),
    }
}

fn format_input_list(inputs: &[Expression]) -> String {
    inputs
        .iter()
        .map(write_expression)
        .collect::<Vec<_>>()
        .join(", ")
}

fn format_output_list(outputs: &[OutputTarget]) -> String {
    outputs
        .iter()
        .map(|o| match o {
            OutputTarget::Name(s) => s.clone(),
            OutputTarget::Wildcard => "_".to_string(),
        })
        .collect::<Vec<_>>()
        .join(", ")
}

fn format_param_list(params: &[Parameter]) -> String {
    params
        .iter()
        .map(|p| match &p.default {
            Some(default) => format!("{}={}", p.name, write_expression(default)),
            None => p.name.clone(),
        })
        .collect::<Vec<_>>()
        .join(", ")
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;
    use crate::ast::{
        Assignment, Branch, DataflowBlock, Expression, FuncCall, Identifier, Jump, Literal,
        MetaAnnotation, Namespace, OutputTarget, Parallel, Parameter, Program, Statement,
        SubgraphDef, Switch, Value,
    };

    // ---- literal formatting ------------------------------------------------

    #[test]
    fn test_literal_int() {
        let lit = Literal {
            value: Value::Int(42),
            literal_type: "int".into(),
            line: None,
        };
        assert_eq!(write_literal(&lit), "42");
    }

    #[test]
    fn test_literal_float() {
        let lit = Literal {
            value: Value::Float(3.14),
            literal_type: "float".into(),
            line: None,
        };
        let s = write_literal(&lit);
        assert!(
            s.contains('.'),
            "float must contain a decimal point, got: {s}"
        );
        assert!(s.starts_with("3."), "unexpected float repr: {s}");
    }

    #[test]
    fn test_literal_string_simple() {
        let lit = Literal {
            value: Value::Str("hello".into()),
            literal_type: "str".into(),
            line: None,
        };
        assert_eq!(write_literal(&lit), r#""hello""#);
    }

    #[test]
    fn test_literal_string_with_quotes() {
        let lit = Literal {
            value: Value::Str(r#"say "hi""#.into()),
            literal_type: "str".into(),
            line: None,
        };
        assert_eq!(write_literal(&lit), r#""say \"hi\"""#);
    }

    #[test]
    fn test_literal_string_multiline() {
        let lit = Literal {
            value: Value::Str("line1\nline2".into()),
            literal_type: "str".into(),
            line: None,
        };
        let s = write_literal(&lit);
        assert!(s.starts_with("\"\"\""), "expected triple-quoted string");
        assert!(s.ends_with("\"\"\""), "expected triple-quoted string");
        assert!(s.contains("line1\nline2"));
    }

    #[test]
    fn test_literal_bool() {
        let t = Literal {
            value: Value::Bool(true),
            literal_type: "bool".into(),
            line: None,
        };
        let f = Literal {
            value: Value::Bool(false),
            literal_type: "bool".into(),
            line: None,
        };
        assert_eq!(write_literal(&t), "True");
        assert_eq!(write_literal(&f), "False");
    }

    #[test]
    fn test_literal_none() {
        let lit = Literal {
            value: Value::None,
            literal_type: "none".into(),
            line: None,
        };
        assert_eq!(write_literal(&lit), "None");
    }

    #[test]
    fn test_literal_list() {
        let lit = Literal {
            value: Value::List(vec![Value::Int(1), Value::Int(2), Value::Int(3)]),
            literal_type: "list".into(),
            line: None,
        };
        assert_eq!(write_literal(&lit), "[1, 2, 3]");
    }

    #[test]
    fn test_literal_dict() {
        let mut map = HashMap::new();
        map.insert("a".to_string(), Value::Int(1));
        let lit = Literal {
            value: Value::Dict(map),
            literal_type: "dict".into(),
            line: None,
        };
        assert_eq!(write_literal(&lit), r#"{"a": 1}"#);
    }

    // ---- assignment -------------------------------------------------------

    #[test]
    fn test_assignment_no_meta() {
        let prog = Program {
            body: vec![Statement::Assignment(Assignment {
                target: "x".into(),
                value: Expression::Literal(Literal {
                    value: Value::Int(1),
                    literal_type: "int".into(),
                    line: None,
                }),
                type_annotation: None,
                metadata: None,
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "x = 1\n");
    }

    #[test]
    fn test_assignment_with_meta() {
        let mut meta_data = HashMap::new();
        meta_data.insert("key".to_string(), Value::Str("val".into()));
        let prog = Program {
            body: vec![Statement::Assignment(Assignment {
                target: "x".into(),
                value: Expression::Literal(Literal {
                    value: Value::Int(1),
                    literal_type: "int".into(),
                    line: None,
                }),
                type_annotation: None,
                metadata: Some(vec![MetaAnnotation {
                    data: meta_data,
                    line: None,
                }]),
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        let out = write(&prog);
        assert_eq!(out, "@meta key=\"val\"\nx = 1\n");
    }

    // ---- func_call --------------------------------------------------------

    #[test]
    fn test_func_call_basic() {
        let prog = Program {
            body: vec![Statement::FuncCall(FuncCall {
                inputs: vec![
                    Expression::Identifier(Identifier {
                        name: "a".into(),
                        line: None,
                    }),
                    Expression::Identifier(Identifier {
                        name: "b".into(),
                        line: None,
                    }),
                ],
                func_name: "add".into(),
                outputs: vec![OutputTarget::Name("result".into())],
                metadata: None,
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "(a, b)add(result)\n");
    }

    #[test]
    fn test_func_call_wildcard_output() {
        let prog = Program {
            body: vec![Statement::FuncCall(FuncCall {
                inputs: vec![],
                func_name: "noop".into(),
                outputs: vec![OutputTarget::Wildcard],
                metadata: None,
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "()noop(_)\n");
    }

    // ---- branch -----------------------------------------------------------

    #[test]
    fn test_branch() {
        let prog = Program {
            body: vec![Statement::Branch(Branch {
                condition: Expression::Identifier(Identifier {
                    name: "cond".into(),
                    line: None,
                }),
                true_label: "yes".into(),
                false_label: "no".into(),
                metadata: None,
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "(cond)branch(`yes`, `no`)\n");
    }

    // ---- switch -----------------------------------------------------------

    #[test]
    fn test_switch_with_default() {
        let prog = Program {
            body: vec![Statement::Switch(Switch {
                value: Expression::Identifier(Identifier {
                    name: "v".into(),
                    line: None,
                }),
                cases: vec![(
                    Expression::Literal(Literal {
                        value: Value::Int(0),
                        literal_type: "int".into(),
                        line: None,
                    }),
                    "zero".into(),
                )],
                default_label: Some("other".into()),
                metadata: None,
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "(v)switch(0=>`zero`, _=>`other`)\n");
    }

    // ---- jump / parallel --------------------------------------------------

    #[test]
    fn test_jump() {
        let prog = Program {
            body: vec![Statement::Jump(Jump {
                target: "end".into(),
                metadata: None,
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "()jump(`end`)\n");
    }

    #[test]
    fn test_parallel() {
        let prog = Program {
            body: vec![Statement::Parallel(Parallel {
                labels: vec!["a".into(), "b".into()],
                metadata: None,
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "()parallel(`a`, `b`)\n");
    }

    // ---- mode decl --------------------------------------------------------

    #[test]
    fn test_mode_decl() {
        let prog = Program {
            body: vec![],
            mode: Some("dataflow".into()),
            typehints: None,
            line: None,
        };
        // No body: the blank separator line collapses into the trailing newline.
        assert_eq!(write(&prog), "@mode dataflow\n");
    }

    #[test]
    fn test_mode_decl_with_body() {
        let prog = Program {
            body: vec![Statement::Assignment(Assignment {
                target: "x".into(),
                value: Expression::Literal(Literal {
                    value: Value::Int(1),
                    literal_type: "int".into(),
                    line: None,
                }),
                type_annotation: None,
                metadata: None,
                line: None,
            })],
            mode: Some("dataflow".into()),
            typehints: None,
            line: None,
        };
        // With body: blank line separates the @mode from the first statement.
        assert_eq!(write(&prog), "@mode dataflow\n\nx = 1\n");
    }

    // ---- namespace indentation --------------------------------------------

    #[test]
    fn test_namespace_indentation() {
        let prog = Program {
            body: vec![Statement::Namespace(Namespace {
                name: "main".into(),
                body: vec![Statement::Assignment(Assignment {
                    target: "x".into(),
                    value: Expression::Literal(Literal {
                        value: Value::Int(1),
                        literal_type: "int".into(),
                        line: None,
                    }),
                    type_annotation: None,
                    metadata: None,
                    line: None,
                })],
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "main:\n    x = 1\n");
    }

    #[test]
    fn test_nested_namespace_indentation() {
        let prog = Program {
            body: vec![Statement::Namespace(Namespace {
                name: "outer".into(),
                body: vec![Statement::Namespace(Namespace {
                    name: "inner".into(),
                    body: vec![Statement::Jump(Jump {
                        target: "end".into(),
                        metadata: None,
                        line: None,
                    })],
                    line: None,
                })],
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "outer:\n    inner:\n        ()jump(`end`)\n");
    }

    // ---- @dataflow block --------------------------------------------------

    #[test]
    fn test_dataflow_block_indentation() {
        let prog = Program {
            body: vec![Statement::DataflowBlock(DataflowBlock {
                body: vec![Statement::FuncCall(FuncCall {
                    inputs: vec![Expression::Identifier(Identifier {
                        name: "x".into(),
                        line: None,
                    })],
                    func_name: "f".into(),
                    outputs: vec![OutputTarget::Name("y".into())],
                    metadata: None,
                    line: None,
                })],
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "@dataflow:\n    (x)f(y)\n");
    }

    // ---- @def subgraph ----------------------------------------------------

    #[test]
    fn test_subgraph_def_basic() {
        let prog = Program {
            body: vec![Statement::SubgraphDef(SubgraphDef {
                name: "my_func".into(),
                params: vec![
                    Parameter {
                        name: "a".into(),
                        default: None,
                        line: None,
                    },
                    Parameter {
                        name: "b".into(),
                        default: Some(Expression::Literal(Literal {
                            value: Value::Int(0),
                            literal_type: "int".into(),
                            line: None,
                        })),
                        line: None,
                    },
                ],
                outputs: vec!["out".into()],
                body: vec![Statement::Jump(Jump {
                    target: "end".into(),
                    metadata: None,
                    line: None,
                })],
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        let out = write(&prog);
        assert!(out.starts_with("@def my_func(a, b=0)(out)"));
        assert!(out.contains("    ()jump(`end`)"));
        // The blank-line entry at the end of the @def block collapses to the
        // trailing newline when there are no further statements after it.
        assert!(out.ends_with("    ()jump(`end`)\n"));
    }

    // ---- @typehint block --------------------------------------------------

    #[test]
    fn test_typehint_block_write() {
        use crate::ast::{TypeExpr, TypeHintEntry};

        let prog = Program {
            body: vec![],
            mode: None,
            typehints: Some(vec![TypeHintEntry {
                func_name: "add".into(),
                input_types: vec![
                    TypeExpr {
                        name: "int".into(),
                        is_optional: false,
                        union_of: None,
                        line: None,
                    },
                    TypeExpr {
                        name: "int".into(),
                        is_optional: false,
                        union_of: None,
                        line: None,
                    },
                ],
                output_types: vec![TypeExpr {
                    name: "int".into(),
                    is_optional: false,
                    union_of: None,
                    line: None,
                }],
                line: None,
            }]),
            line: None,
        };
        let out = write(&prog);
        assert!(out.contains("@typehint:"), "missing @typehint header");
        assert!(out.contains("(int, int)add(int)"), "missing entry");
    }

    #[test]
    fn test_typehint_optional_type_write() {
        use crate::ast::{TypeExpr, TypeHintEntry};

        let prog = Program {
            body: vec![],
            mode: None,
            typehints: Some(vec![TypeHintEntry {
                func_name: "maybe".into(),
                input_types: vec![TypeExpr {
                    name: "str".into(),
                    is_optional: true,
                    union_of: None,
                    line: None,
                }],
                output_types: vec![],
                line: None,
            }]),
            line: None,
        };
        let out = write(&prog);
        assert!(out.contains("(str?)maybe()"), "expected optional type str?");
    }

    #[test]
    fn test_typehint_union_type_write() {
        use crate::ast::{TypeExpr, TypeHintEntry};

        let prog = Program {
            body: vec![],
            mode: None,
            typehints: Some(vec![TypeHintEntry {
                func_name: "process".into(),
                input_types: vec![TypeExpr {
                    name: "int|float".into(),
                    is_optional: false,
                    union_of: Some(vec![
                        TypeExpr {
                            name: "int".into(),
                            is_optional: false,
                            union_of: None,
                            line: None,
                        },
                        TypeExpr {
                            name: "float".into(),
                            is_optional: false,
                            union_of: None,
                            line: None,
                        },
                    ]),
                    line: None,
                }],
                output_types: vec![],
                line: None,
            }]),
            line: None,
        };
        let out = write(&prog);
        assert!(out.contains("int|float"), "expected union type int|float");
    }

    // ---- typed assignment -------------------------------------------------

    #[test]
    fn test_typed_assignment_write() {
        use crate::ast::TypeExpr;

        let prog = Program {
            body: vec![Statement::Assignment(Assignment {
                target: "x".into(),
                value: Expression::Literal(Literal {
                    value: Value::Int(42),
                    literal_type: "int".into(),
                    line: None,
                }),
                type_annotation: Some(TypeExpr {
                    name: "int".into(),
                    is_optional: false,
                    union_of: None,
                    line: None,
                }),
                metadata: None,
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        assert_eq!(write(&prog), "x: int = 42\n");
    }

    // ---- @try/@except block -----------------------------------------------

    #[test]
    fn test_try_except_write() {
        use crate::ast::TryExcept;

        let prog = Program {
            body: vec![Statement::TryExcept(TryExcept {
                try_body: vec![Statement::Assignment(Assignment {
                    target: "x".into(),
                    value: Expression::Literal(Literal {
                        value: Value::Int(1),
                        literal_type: "int".into(),
                        line: None,
                    }),
                    type_annotation: None,
                    metadata: None,
                    line: None,
                })],
                except_body: vec![Statement::Assignment(Assignment {
                    target: "x".into(),
                    value: Expression::Literal(Literal {
                        value: Value::Int(0),
                        literal_type: "int".into(),
                        line: None,
                    }),
                    type_annotation: None,
                    metadata: None,
                    line: None,
                })],
                metadata: None,
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        let out = write(&prog);
        assert!(out.contains("@try:"), "missing @try:");
        assert!(out.contains("@except:"), "missing @except:");
        assert!(out.contains("    x = 1"), "missing try body");
        assert!(out.contains("    x = 0"), "missing except body");
    }

    #[test]
    fn test_subgraph_blank_line_before_next_stmt() {
        // When a @def is followed by another statement, the blank line from
        // write_subgraph_def creates a true blank line separator in the output.
        let prog = Program {
            body: vec![
                Statement::SubgraphDef(SubgraphDef {
                    name: "f".into(),
                    params: vec![],
                    outputs: vec![],
                    body: vec![],
                    line: None,
                }),
                Statement::Assignment(Assignment {
                    target: "x".into(),
                    value: Expression::Literal(Literal {
                        value: Value::Int(1),
                        literal_type: "int".into(),
                        line: None,
                    }),
                    type_annotation: None,
                    metadata: None,
                    line: None,
                }),
            ],
            mode: None,
            typehints: None,
            line: None,
        };
        let out = write(&prog);
        assert!(
            out.contains("\n\n"),
            "expected blank line between @def and next statement"
        );
        assert!(out.contains("@def f()()"));
        assert!(out.contains("x = 1"));
    }
}
