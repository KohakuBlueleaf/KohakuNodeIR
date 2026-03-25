//! KIR parser: text → [`Program`].
//!
//! # Pipeline
//!
//! 1. [`indentation::preprocess`] transforms the raw KIR source into a flat
//!    string with explicit `INDENT\n` / `DEDENT\n` marker lines.
//! 2. The pest grammar (`kir.pest`) parses the preprocessed text.
//! 3. [`build_program`] walks the pest `Pairs` tree and produces the Rust AST
//!    types defined in `crate::ast`.

pub mod indentation;

#[cfg(feature = "pyo3")]
pub mod pyo3;

use pest::Parser as PestParser;
use pest_derive::Parser;

use crate::ast::{
    Assignment, Branch, DataflowBlock, Expression, FuncCall, Identifier, Jump, KeywordArg, Literal,
    MetaAnnotation, ModeDecl, Namespace, OutputTarget, Parallel, Parameter, Program, Statement,
    SubgraphDef, Switch, Value,
};

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Errors that can arise during parsing.
#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    /// Indentation preprocessing produced text the grammar cannot accept.
    #[error("Pest parse error: {0}")]
    Pest(#[from] pest::error::Error<Rule>),

    /// A grammar rule produced unexpected structure (should not happen with a
    /// correct grammar, but guards against programmer error).
    #[error("Internal parser error: {0}")]
    Internal(String),
}

// ---------------------------------------------------------------------------
// pest grammar
// ---------------------------------------------------------------------------

#[derive(Parser)]
#[grammar = "parser/kir.pest"]
struct KirParser;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Parse KIR source text and return a [`Program`] AST.
pub fn parse(input: &str) -> Result<Program, ParseError> {
    let preprocessed = indentation::preprocess(input);
    let pairs = KirParser::parse(Rule::program, &preprocessed)?;
    let program = build_program(pairs)?;
    Ok(program)
}

// ---------------------------------------------------------------------------
// AST builder — top-level
// ---------------------------------------------------------------------------

fn build_program(mut pairs: pest::iterators::Pairs<'_, Rule>) -> Result<Program, ParseError> {
    // The top-level pair is the `program` rule.
    let program_pair = pairs
        .next()
        .ok_or_else(|| ParseError::Internal("empty parse output".into()))?;
    assert_eq!(program_pair.as_rule(), Rule::program);

    let mut mode: Option<String> = None;
    let mut raw_stmts: Vec<RawStmt> = Vec::new();

    for pair in program_pair.into_inner() {
        match pair.as_rule() {
            Rule::statement => {
                let raw = build_statement(pair)?;
                raw_stmts.push(raw);
            }
            Rule::EOI | Rule::INDENT | Rule::DEDENT => {}
            _ => {} // blank lines etc.
        }
    }

    // Extract mode from ModeDecl statements; collect the rest as body.
    let mut body: Vec<Statement> = Vec::new();
    let mut pending_meta: Vec<MetaAnnotation> = Vec::new();

    for raw in raw_stmts {
        match raw {
            RawStmt::Stmt(Statement::ModeDecl(md)) => {
                mode = Some(md.mode.clone());
            }
            RawStmt::Meta(ma) => {
                pending_meta.push(ma);
            }
            RawStmt::Stmt(mut stmt) => {
                if !pending_meta.is_empty() {
                    attach_meta(&mut stmt, std::mem::take(&mut pending_meta));
                }
                body.push(stmt);
            }
        }
    }

    Ok(Program {
        body,
        mode,
        line: None,
    })
}

// ---------------------------------------------------------------------------
// Intermediate enum to hold either a concrete statement or a meta annotation
// before we know what statement follows it.
// ---------------------------------------------------------------------------

enum RawStmt {
    Stmt(Statement),
    Meta(MetaAnnotation),
}

// ---------------------------------------------------------------------------
// Statement builder
// ---------------------------------------------------------------------------

fn build_statement(pair: pest::iterators::Pair<'_, Rule>) -> Result<RawStmt, ParseError> {
    // statement = { simple_stmt | compound_stmt }
    let inner = pair
        .into_inner()
        .next()
        .ok_or_else(|| ParseError::Internal("empty statement".into()))?;

    match inner.as_rule() {
        Rule::simple_stmt => build_simple_stmt(inner),
        Rule::compound_stmt => build_compound_stmt(inner),
        r => Err(ParseError::Internal(format!(
            "unexpected rule in statement: {r:?}"
        ))),
    }
}

fn build_simple_stmt(pair: pest::iterators::Pair<'_, Rule>) -> Result<RawStmt, ParseError> {
    // simple_stmt = { (assignment | call_stmt | meta_anno | mode_decl) ~ NEWLINE+ }
    for child in pair.into_inner() {
        match child.as_rule() {
            Rule::assignment => return Ok(RawStmt::Stmt(build_assignment(child)?)),
            Rule::call_stmt => return Ok(RawStmt::Stmt(build_call_stmt(child)?)),
            Rule::meta_anno => return Ok(RawStmt::Meta(build_meta_anno(child)?)),
            Rule::mode_decl => return Ok(RawStmt::Stmt(build_mode_decl(child)?)),
            _ => {} // NEWLINE tokens
        }
    }
    Err(ParseError::Internal("empty simple_stmt".into()))
}

fn build_compound_stmt(pair: pest::iterators::Pair<'_, Rule>) -> Result<RawStmt, ParseError> {
    let child = pair
        .into_inner()
        .next()
        .ok_or_else(|| ParseError::Internal("empty compound_stmt".into()))?;

    match child.as_rule() {
        Rule::namespace_def => Ok(RawStmt::Stmt(build_namespace_def(child)?)),
        Rule::subgraph_def => Ok(RawStmt::Stmt(build_subgraph_def(child)?)),
        Rule::dataflow_block => Ok(RawStmt::Stmt(build_dataflow_block(child)?)),
        r => Err(ParseError::Internal(format!(
            "unexpected compound_stmt rule: {r:?}"
        ))),
    }
}

// ---------------------------------------------------------------------------
// Assignment
// ---------------------------------------------------------------------------

fn build_assignment(pair: pest::iterators::Pair<'_, Rule>) -> Result<Statement, ParseError> {
    let line = line_of(&pair);
    let mut inner = pair.into_inner();
    let name_pair = inner
        .next()
        .ok_or_else(|| ParseError::Internal("assignment: missing name".into()))?;
    let expr_pair = inner
        .next()
        .ok_or_else(|| ParseError::Internal("assignment: missing expr".into()))?;

    let target = name_pair.as_str().to_string();
    let value = build_expr(expr_pair)?;

    Ok(Statement::Assignment(Assignment {
        target,
        value,
        metadata: None,
        line,
    }))
}

// ---------------------------------------------------------------------------
// Call statement → FuncCall | Branch | Switch | Jump | Parallel
// ---------------------------------------------------------------------------

fn build_call_stmt(pair: pest::iterators::Pair<'_, Rule>) -> Result<Statement, ParseError> {
    let line = line_of(&pair);
    let mut inputs: Vec<Expression> = Vec::new();
    let mut func_name_str = String::new();
    let mut raw_outputs: Vec<RawOutput> = Vec::new();
    let mut seen_func = false;

    for child in pair.into_inner() {
        match child.as_rule() {
            Rule::call_in_list => {
                inputs = build_call_in_list(child)?;
            }
            Rule::func_name => {
                func_name_str = build_func_name(child);
                seen_func = true;
            }
            Rule::call_out_list => {
                if seen_func {
                    raw_outputs = build_call_out_list(child)?;
                }
            }
            _ => {}
        }
    }

    dispatch_call(func_name_str, inputs, raw_outputs, line)
}

fn build_func_name(pair: pest::iterators::Pair<'_, Rule>) -> String {
    pair.into_inner()
        .filter(|p| p.as_rule() == Rule::NAME)
        .map(|p| p.as_str())
        .collect::<Vec<_>>()
        .join(".")
}

fn build_call_in_list(
    pair: pest::iterators::Pair<'_, Rule>,
) -> Result<Vec<Expression>, ParseError> {
    let mut result = Vec::new();
    for child in pair.into_inner() {
        if child.as_rule() == Rule::call_in_item {
            result.push(build_call_in_item(child)?);
        }
    }
    Ok(result)
}

fn build_call_in_item(pair: pest::iterators::Pair<'_, Rule>) -> Result<Expression, ParseError> {
    let child = pair
        .into_inner()
        .next()
        .ok_or_else(|| ParseError::Internal("empty call_in_item".into()))?;

    match child.as_rule() {
        Rule::kwarg => build_kwarg(child),
        Rule::expr => build_expr(child),
        r => Err(ParseError::Internal(format!(
            "unexpected call_in_item rule: {r:?}"
        ))),
    }
}

fn build_kwarg(pair: pest::iterators::Pair<'_, Rule>) -> Result<Expression, ParseError> {
    let line = line_of(&pair);
    let mut inner = pair.into_inner();
    let name_pair = inner.next().unwrap();
    let expr_pair = inner.next().unwrap();
    let name = name_pair.as_str().to_string();
    let value = build_expr(expr_pair)?;
    Ok(Expression::KeywordArg(KeywordArg {
        name,
        value: Box::new(value),
        line,
    }))
}

// ---------------------------------------------------------------------------
// Raw output variants (before dispatch)
// ---------------------------------------------------------------------------

enum RawOutput {
    Name(String),
    Wildcard,
    LabelRef(String),
    SwitchCase(Expression, String),
    SwitchDefault(String),
}

fn build_call_out_list(
    pair: pest::iterators::Pair<'_, Rule>,
) -> Result<Vec<RawOutput>, ParseError> {
    let mut result = Vec::new();
    for child in pair.into_inner() {
        if child.as_rule() == Rule::call_out_item {
            result.push(build_call_out_item(child)?);
        }
    }
    Ok(result)
}

fn build_call_out_item(pair: pest::iterators::Pair<'_, Rule>) -> Result<RawOutput, ParseError> {
    let child = pair
        .into_inner()
        .next()
        .ok_or_else(|| ParseError::Internal("empty call_out_item".into()))?;

    match child.as_rule() {
        Rule::out_name => Ok(RawOutput::Name(
            child.into_inner().next().unwrap().as_str().to_string(),
        )),
        Rule::out_wildcard => Ok(RawOutput::Wildcard),
        Rule::out_label_ref => {
            let label = build_label_ref_str(child.into_inner().next().unwrap());
            Ok(RawOutput::LabelRef(label))
        }
        Rule::out_switch_case => {
            let mut inner = child.into_inner();
            let expr = build_expr(inner.next().unwrap())?;
            let label = build_label_ref_str(inner.next().unwrap());
            Ok(RawOutput::SwitchCase(expr, label))
        }
        Rule::out_switch_default => {
            let label_pair = child
                .into_inner()
                .find(|p| p.as_rule() == Rule::label_ref)
                .ok_or_else(|| ParseError::Internal("switch_default missing label_ref".into()))?;
            let label = build_label_ref_str(label_pair);
            Ok(RawOutput::SwitchDefault(label))
        }
        r => Err(ParseError::Internal(format!(
            "unexpected call_out_item: {r:?}"
        ))),
    }
}

fn build_label_ref_str(pair: pest::iterators::Pair<'_, Rule>) -> String {
    // pair.as_rule() == Rule::label_ref
    // The LABEL_REF token is "`name`"; strip backticks.
    let token = pair.into_inner().next().unwrap();
    token.as_str().trim_matches('`').to_string()
}

// ---------------------------------------------------------------------------
// Dispatch: func_name → concrete Statement type
// ---------------------------------------------------------------------------

fn dispatch_call(
    func_name: String,
    inputs: Vec<Expression>,
    raw_outputs: Vec<RawOutput>,
    line: Option<usize>,
) -> Result<Statement, ParseError> {
    match func_name.as_str() {
        "branch" => {
            let condition = inputs.into_iter().next().unwrap_or_default();
            let mut labels = raw_outputs.into_iter().filter_map(|o| match o {
                RawOutput::LabelRef(s) => Some(s),
                _ => None,
            });
            let true_label = labels.next().unwrap_or_default();
            let false_label = labels.next().unwrap_or_default();
            Ok(Statement::Branch(Branch {
                condition,
                true_label,
                false_label,
                metadata: None,
                line,
            }))
        }
        "switch" => {
            let value = inputs.into_iter().next().unwrap_or_default();
            let mut cases: Vec<(Expression, String)> = Vec::new();
            let mut default_label: Option<String> = None;
            for o in raw_outputs {
                match o {
                    RawOutput::SwitchCase(expr, label) => cases.push((expr, label)),
                    RawOutput::SwitchDefault(label) => default_label = Some(label),
                    _ => {}
                }
            }
            Ok(Statement::Switch(Switch {
                value,
                cases,
                default_label,
                metadata: None,
                line,
            }))
        }
        "jump" => {
            let target = raw_outputs
                .into_iter()
                .find_map(|o| match o {
                    RawOutput::LabelRef(s) => Some(s),
                    _ => None,
                })
                .unwrap_or_default();
            Ok(Statement::Jump(Jump {
                target,
                metadata: None,
                line,
            }))
        }
        "parallel" => {
            let labels = raw_outputs
                .into_iter()
                .filter_map(|o| match o {
                    RawOutput::LabelRef(s) => Some(s),
                    _ => None,
                })
                .collect();
            Ok(Statement::Parallel(Parallel {
                labels,
                metadata: None,
                line,
            }))
        }
        _ => {
            // Regular function call — outputs are Names or Wildcards only.
            let outputs = raw_outputs
                .into_iter()
                .map(|o| match o {
                    RawOutput::Name(s) => OutputTarget::Name(s),
                    RawOutput::Wildcard => OutputTarget::Wildcard,
                    // Label refs in outputs of non-builtins become names
                    // (shouldn't appear in practice).
                    RawOutput::LabelRef(s) => OutputTarget::Name(s),
                    RawOutput::SwitchCase(_, s) => OutputTarget::Name(s),
                    RawOutput::SwitchDefault(s) => OutputTarget::Name(s),
                })
                .collect();
            Ok(Statement::FuncCall(FuncCall {
                inputs,
                func_name,
                outputs,
                metadata: None,
                line,
            }))
        }
    }
}

// ---------------------------------------------------------------------------
// Namespace
// ---------------------------------------------------------------------------

fn build_namespace_def(pair: pest::iterators::Pair<'_, Rule>) -> Result<Statement, ParseError> {
    let child = pair
        .into_inner()
        .next()
        .ok_or_else(|| ParseError::Internal("empty namespace_def".into()))?;

    match child.as_rule() {
        Rule::namespace_body => build_namespace_body(child),
        Rule::namespace_empty => build_namespace_empty(child),
        r => Err(ParseError::Internal(format!(
            "unexpected namespace_def child: {r:?}"
        ))),
    }
}

fn build_namespace_body(pair: pest::iterators::Pair<'_, Rule>) -> Result<Statement, ParseError> {
    let line = line_of(&pair);
    let mut inner = pair.into_inner();
    let name = inner.next().unwrap().as_str().to_string();
    let raw_stmts = collect_body_stmts(inner)?;
    let body = process_body(raw_stmts);
    Ok(Statement::Namespace(Namespace { name, body, line }))
}

fn build_namespace_empty(pair: pest::iterators::Pair<'_, Rule>) -> Result<Statement, ParseError> {
    let line = line_of(&pair);
    let name = pair.into_inner().next().unwrap().as_str().to_string();
    Ok(Statement::Namespace(Namespace {
        name,
        body: Vec::new(),
        line,
    }))
}

// ---------------------------------------------------------------------------
// Subgraph definition
// ---------------------------------------------------------------------------

fn build_subgraph_def(pair: pest::iterators::Pair<'_, Rule>) -> Result<Statement, ParseError> {
    let line = line_of(&pair);
    let mut params: Vec<Parameter> = Vec::new();
    let mut name = String::new();
    let mut outputs: Vec<String> = Vec::new();
    let mut body_raw: Vec<RawStmt> = Vec::new();

    let mut seen_name = false;

    for child in pair.into_inner() {
        match child.as_rule() {
            Rule::param_list => {
                params = build_param_list(child)?;
            }
            Rule::NAME => {
                if !seen_name {
                    name = child.as_str().to_string();
                    seen_name = true;
                }
            }
            Rule::def_output_list => {
                outputs = child
                    .into_inner()
                    .filter(|p| p.as_rule() == Rule::NAME)
                    .map(|p| p.as_str().to_string())
                    .collect();
            }
            Rule::INDENT | Rule::DEDENT => {}
            Rule::statement => {
                body_raw.push(build_statement(child)?);
            }
            _ => {}
        }
    }

    let body = process_body(body_raw);
    Ok(Statement::SubgraphDef(SubgraphDef {
        name,
        params,
        outputs,
        body,
        line,
    }))
}

fn build_param_list(pair: pest::iterators::Pair<'_, Rule>) -> Result<Vec<Parameter>, ParseError> {
    let mut params = Vec::new();
    for child in pair.into_inner() {
        if child.as_rule() == Rule::param {
            params.push(build_param(child)?);
        }
    }
    Ok(params)
}

fn build_param(pair: pest::iterators::Pair<'_, Rule>) -> Result<Parameter, ParseError> {
    let child = pair
        .into_inner()
        .next()
        .ok_or_else(|| ParseError::Internal("empty param".into()))?;

    match child.as_rule() {
        Rule::param_plain => {
            let line = line_of(&child);
            let name = child.into_inner().next().unwrap().as_str().to_string();
            Ok(Parameter {
                name,
                default: None,
                line,
            })
        }
        Rule::param_with_default => {
            let line = line_of(&child);
            let mut inner = child.into_inner();
            let name = inner.next().unwrap().as_str().to_string();
            let default = build_expr(inner.next().unwrap())?;
            Ok(Parameter {
                name,
                default: Some(default),
                line,
            })
        }
        r => Err(ParseError::Internal(format!(
            "unexpected param rule: {r:?}"
        ))),
    }
}

// ---------------------------------------------------------------------------
// Dataflow block
// ---------------------------------------------------------------------------

fn build_dataflow_block(pair: pest::iterators::Pair<'_, Rule>) -> Result<Statement, ParseError> {
    let line = line_of(&pair);
    let raw_stmts = collect_body_stmts(pair.into_inner())?;
    let body = process_body(raw_stmts);
    Ok(Statement::DataflowBlock(DataflowBlock { body, line }))
}

// ---------------------------------------------------------------------------
// Meta annotation
// ---------------------------------------------------------------------------

fn build_meta_anno(pair: pest::iterators::Pair<'_, Rule>) -> Result<MetaAnnotation, ParseError> {
    let line = line_of(&pair);
    let mut data = std::collections::HashMap::new();

    for child in pair.into_inner() {
        if child.as_rule() == Rule::meta_pair {
            let mut inner = child.into_inner();
            let key = inner.next().unwrap().as_str().to_string();
            let val_pair = inner.next().unwrap();
            let value = build_meta_val(val_pair)?;
            data.insert(key, value);
        }
    }

    Ok(MetaAnnotation { data, line })
}

fn build_meta_val(pair: pest::iterators::Pair<'_, Rule>) -> Result<Value, ParseError> {
    // meta_val = { literal | meta_tuple | identifier }
    let child = pair
        .into_inner()
        .next()
        .ok_or_else(|| ParseError::Internal("empty meta_val".into()))?;

    match child.as_rule() {
        Rule::literal => {
            let lit = build_literal(child)?;
            Ok(lit.value)
        }
        Rule::meta_tuple => {
            let values: Result<Vec<Value>, ParseError> = child
                .into_inner()
                .filter(|p| p.as_rule() == Rule::meta_val)
                .map(build_meta_val)
                .collect();
            Ok(Value::List(values?))
        }
        Rule::identifier => {
            let name = child.into_inner().next().unwrap().as_str().to_string();
            Ok(Value::Str(name))
        }
        r => Err(ParseError::Internal(format!(
            "unexpected meta_val rule: {r:?}"
        ))),
    }
}

// ---------------------------------------------------------------------------
// Mode declaration
// ---------------------------------------------------------------------------

fn build_mode_decl(pair: pest::iterators::Pair<'_, Rule>) -> Result<Statement, ParseError> {
    let line = line_of(&pair);
    let mode = pair.into_inner().next().unwrap().as_str().to_string();
    Ok(Statement::ModeDecl(ModeDecl { mode, line }))
}

// ---------------------------------------------------------------------------
// Expressions
// ---------------------------------------------------------------------------

fn build_expr(pair: pest::iterators::Pair<'_, Rule>) -> Result<Expression, ParseError> {
    // expr = { literal | identifier }
    let child = pair
        .into_inner()
        .next()
        .ok_or_else(|| ParseError::Internal("empty expr".into()))?;

    match child.as_rule() {
        Rule::literal => {
            let lit = build_literal(child)?;
            Ok(Expression::Literal(lit))
        }
        Rule::identifier => {
            let line = line_of(&child);
            let name = child.into_inner().next().unwrap().as_str().to_string();
            Ok(Expression::Identifier(Identifier { name, line }))
        }
        r => Err(ParseError::Internal(format!("unexpected expr rule: {r:?}"))),
    }
}

fn build_literal(pair: pest::iterators::Pair<'_, Rule>) -> Result<Literal, ParseError> {
    // literal = { float_lit | int_lit | bool_lit | none_lit | string_lit | list_lit | dict_lit }
    let child = pair
        .into_inner()
        .next()
        .ok_or_else(|| ParseError::Internal("empty literal".into()))?;

    match child.as_rule() {
        Rule::int_lit => {
            let line = line_of(&child);
            let raw = child.into_inner().next().unwrap().as_str();
            let value = parse_int(raw)?;
            Ok(Literal {
                value: Value::Int(value),
                literal_type: "int".into(),
                line,
            })
        }
        Rule::float_lit => {
            let line = line_of(&child);
            let raw = child.into_inner().next().unwrap().as_str();
            let value: f64 = raw
                .parse()
                .map_err(|_| ParseError::Internal(format!("invalid float literal: {raw}")))?;
            Ok(Literal {
                value: Value::Float(value),
                literal_type: "float".into(),
                line,
            })
        }
        Rule::bool_lit => {
            let line = line_of(&child);
            let token = child.into_inner().next().unwrap();
            let value = match token.as_rule() {
                Rule::TRUE => true,
                Rule::FALSE => false,
                _ => unreachable!(),
            };
            Ok(Literal {
                value: Value::Bool(value),
                literal_type: "bool".into(),
                line,
            })
        }
        Rule::none_lit => {
            let line = line_of(&child);
            Ok(Literal {
                value: Value::None,
                literal_type: "none".into(),
                line,
            })
        }
        Rule::string_lit => {
            let line = line_of(&child);
            let raw = child.into_inner().next().unwrap().as_str();
            let value = parse_string(raw)?;
            Ok(Literal {
                value: Value::Str(value),
                literal_type: "str".into(),
                line,
            })
        }
        Rule::list_lit => {
            let line = line_of(&child);
            let items: Result<Vec<Value>, ParseError> = child
                .into_inner()
                .filter(|p| p.as_rule() == Rule::expr)
                .map(|p| build_expr(p).map(expr_to_value))
                .collect();
            Ok(Literal {
                value: Value::List(items?),
                literal_type: "list".into(),
                line,
            })
        }
        Rule::dict_lit => {
            let line = line_of(&child);
            let mut map = std::collections::HashMap::new();
            for pair in child.into_inner() {
                if pair.as_rule() == Rule::dict_pair {
                    let mut kv = pair.into_inner();
                    let k_expr = build_expr(kv.next().unwrap())?;
                    let v_expr = build_expr(kv.next().unwrap())?;
                    let key = match expr_to_value(k_expr) {
                        Value::Str(s) => s,
                        Value::Int(i) => i.to_string(),
                        Value::Float(f) => f.to_string(),
                        other => format!("{other:?}"),
                    };
                    map.insert(key, expr_to_value(v_expr));
                }
            }
            Ok(Literal {
                value: Value::Dict(map),
                literal_type: "dict".into(),
                line,
            })
        }
        r => Err(ParseError::Internal(format!(
            "unexpected literal rule: {r:?}"
        ))),
    }
}

/// Convert an Expression to a bare Value (for collection literals / meta).
fn expr_to_value(expr: Expression) -> Value {
    match expr {
        Expression::Literal(lit) => lit.value,
        Expression::Identifier(id) => Value::Str(id.name),
        _ => Value::None,
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Collect `statement` children from an iterator, skipping INDENT / DEDENT
/// and other structural tokens.
fn collect_body_stmts(pairs: pest::iterators::Pairs<'_, Rule>) -> Result<Vec<RawStmt>, ParseError> {
    let mut stmts = Vec::new();
    for pair in pairs {
        if pair.as_rule() == Rule::statement {
            stmts.push(build_statement(pair)?);
        }
    }
    Ok(stmts)
}

/// Walk a flat list of `RawStmt`, attaching pending `@meta` annotations to the
/// next eligible statement.
fn process_body(raw: Vec<RawStmt>) -> Vec<Statement> {
    let mut result = Vec::new();
    let mut pending_meta: Vec<MetaAnnotation> = Vec::new();

    for item in raw {
        match item {
            RawStmt::Meta(ma) => pending_meta.push(ma),
            RawStmt::Stmt(mut stmt) => {
                if !pending_meta.is_empty() {
                    attach_meta(&mut stmt, std::mem::take(&mut pending_meta));
                }
                result.push(stmt);
            }
        }
    }
    result
}

/// Attach `MetaAnnotation`s to a statement that has a `metadata` field.
fn attach_meta(stmt: &mut Statement, meta: Vec<MetaAnnotation>) {
    let field = match stmt {
        Statement::Assignment(s) => &mut s.metadata,
        Statement::FuncCall(s) => &mut s.metadata,
        Statement::Branch(s) => &mut s.metadata,
        Statement::Switch(s) => &mut s.metadata,
        Statement::Jump(s) => &mut s.metadata,
        Statement::Parallel(s) => &mut s.metadata,
        _ => return,
    };
    *field = Some(meta);
}

/// Extract the 1-based line number from the span of a pest Pair.
fn line_of(pair: &pest::iterators::Pair<'_, Rule>) -> Option<usize> {
    Some(pair.line_col().0)
}

/// Parse an integer literal that may be decimal, hex (0x), octal (0o), or
/// binary (0b).  Also handles a leading `+` or `-`.
fn parse_int(raw: &str) -> Result<i64, ParseError> {
    let (sign, s) = if let Some(rest) = raw.strip_prefix('-') {
        (-1i64, rest)
    } else if let Some(rest) = raw.strip_prefix('+') {
        (1, rest)
    } else {
        (1, raw)
    };

    let value: i64 = if let Some(hex) = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")) {
        i64::from_str_radix(hex, 16)
    } else if let Some(oct) = s.strip_prefix("0o").or_else(|| s.strip_prefix("0O")) {
        i64::from_str_radix(oct, 8)
    } else if let Some(bin) = s.strip_prefix("0b").or_else(|| s.strip_prefix("0B")) {
        i64::from_str_radix(bin, 2)
    } else {
        s.parse::<i64>()
    }
    .map_err(|_| ParseError::Internal(format!("invalid int literal: {raw}")))?;

    Ok(sign * value)
}

/// Unescape a KIR string literal (strips surrounding quotes, handles `\n`,
/// `\t`, `\\`, `\"`, `\'`).
fn parse_string(raw: &str) -> Result<String, ParseError> {
    // Detect and strip quote style.
    let (inner, quote_len): (&str, usize) = if raw.starts_with("\"\"\"") || raw.starts_with("'''") {
        (&raw[3..raw.len() - 3], 3)
    } else if raw.starts_with('"') || raw.starts_with('\'') {
        (&raw[1..raw.len() - 1], 1)
    } else {
        return Err(ParseError::Internal(format!(
            "malformed string literal: {raw}"
        )));
    };
    let _ = quote_len;

    let mut out = String::with_capacity(inner.len());
    let mut chars = inner.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch == '\\' {
            match chars.next() {
                Some('n') => out.push('\n'),
                Some('t') => out.push('\t'),
                Some('r') => out.push('\r'),
                Some('\\') => out.push('\\'),
                Some('"') => out.push('"'),
                Some('\'') => out.push('\''),
                Some('0') => out.push('\0'),
                Some(c) => {
                    out.push('\\');
                    out.push(c);
                }
                None => out.push('\\'),
            }
        } else {
            out.push(ch);
        }
    }
    Ok(out)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    // -----------------------------------------------------------------------
    // Unit tests for simple constructs
    // -----------------------------------------------------------------------

    /// Helper: assert an Expression is a Literal with the given value/type,
    /// ignoring the `line` field.
    fn assert_literal(expr: &Expression, expected_value: &Value, expected_type: &str) {
        match expr {
            Expression::Literal(lit) => {
                assert_eq!(&lit.value, expected_value, "literal value mismatch");
                assert_eq!(lit.literal_type, expected_type, "literal type mismatch");
            }
            other => panic!("expected Literal, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_assignment_int() {
        let prog = parse("x = 42\n").unwrap();
        assert_eq!(prog.body.len(), 1);
        match &prog.body[0] {
            Statement::Assignment(a) => {
                assert_eq!(a.target, "x");
                assert_literal(&a.value, &Value::Int(42), "int");
            }
            other => panic!("expected Assignment, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_func_call_simple() {
        let prog = parse("(x, y)add(result)\n").unwrap();
        assert_eq!(prog.body.len(), 1);
        match &prog.body[0] {
            Statement::FuncCall(fc) => {
                assert_eq!(fc.func_name, "add");
                assert_eq!(fc.inputs.len(), 2);
                assert_eq!(fc.outputs, vec![OutputTarget::Name("result".into())]);
            }
            other => panic!("expected FuncCall, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_branch() {
        let prog = parse("(cond)branch(`t`, `f`)\n").unwrap();
        assert_eq!(prog.body.len(), 1);
        match &prog.body[0] {
            Statement::Branch(b) => {
                assert_eq!(b.true_label, "t");
                assert_eq!(b.false_label, "f");
            }
            other => panic!("expected Branch, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_jump() {
        let prog = parse("()jump(`loop`)\n").unwrap();
        match &prog.body[0] {
            Statement::Jump(j) => assert_eq!(j.target, "loop"),
            other => panic!("expected Jump, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_parallel() {
        let prog = parse("()parallel(`a`, `b`)\n").unwrap();
        match &prog.body[0] {
            Statement::Parallel(p) => assert_eq!(p.labels, vec!["a", "b"]),
            other => panic!("expected Parallel, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_switch() {
        let prog = parse("(day)switch(1=>`monday`, _=>`other`)\n").unwrap();
        match &prog.body[0] {
            Statement::Switch(s) => {
                assert_eq!(s.cases.len(), 1);
                assert_eq!(s.default_label, Some("other".into()));
            }
            other => panic!("expected Switch, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_string_literal() {
        let prog = parse("(\"Hello, World!\")print()\n").unwrap();
        match &prog.body[0] {
            Statement::FuncCall(fc) => {
                assert_eq!(fc.func_name, "print");
                assert_literal(&fc.inputs[0], &Value::Str("Hello, World!".into()), "str");
            }
            other => panic!("expected FuncCall, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_bool_literal() {
        let prog = parse("x = True\n").unwrap();
        match &prog.body[0] {
            Statement::Assignment(a) => {
                assert_literal(&a.value, &Value::Bool(true), "bool");
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn test_parse_none_literal() {
        let prog = parse("x = None\n").unwrap();
        match &prog.body[0] {
            Statement::Assignment(a) => {
                assert_literal(&a.value, &Value::None, "none");
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn test_parse_namespace_with_body() {
        let src = "loop:\n    ()jump(`loop`)\n";
        let prog = parse(src).unwrap();
        match &prog.body[0] {
            Statement::Namespace(ns) => {
                assert_eq!(ns.name, "loop");
                assert_eq!(ns.body.len(), 1);
            }
            other => panic!("expected Namespace, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_empty_namespace() {
        let src = "done:\nx = 1\n";
        let prog = parse(src).unwrap();
        match &prog.body[0] {
            Statement::Namespace(ns) => {
                assert_eq!(ns.name, "done");
                assert!(ns.body.is_empty());
            }
            other => panic!("expected empty Namespace, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_mode_decl() {
        let prog = parse("@mode dataflow\n").unwrap();
        assert_eq!(prog.mode, Some("dataflow".into()));
        assert!(prog.body.is_empty()); // ModeDecl is extracted, not left in body
    }

    #[test]
    fn test_parse_keyword_arg() {
        let prog = parse("(data, threshold=0.5)filter(result)\n").unwrap();
        match &prog.body[0] {
            Statement::FuncCall(fc) => {
                assert_eq!(fc.inputs.len(), 2);
                match &fc.inputs[1] {
                    Expression::KeywordArg(kw) => {
                        assert_eq!(kw.name, "threshold");
                    }
                    other => panic!("expected kwarg, got {other:?}"),
                }
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn test_parse_subgraph_def() {
        let src = "@def (a, b)clamp(result):\n    (a, b)min_val(lo)\n";
        let prog = parse(src).unwrap();
        match &prog.body[0] {
            Statement::SubgraphDef(sd) => {
                assert_eq!(sd.name, "clamp");
                assert_eq!(sd.params.len(), 2);
                assert_eq!(sd.outputs, vec!["result"]);
                assert_eq!(sd.body.len(), 1);
            }
            other => panic!("expected SubgraphDef, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_dataflow_block() {
        let src = "@dataflow:\n    x = 1\n    (x)print()\n";
        let prog = parse(src).unwrap();
        match &prog.body[0] {
            Statement::DataflowBlock(df) => {
                assert_eq!(df.body.len(), 2);
            }
            other => panic!("expected DataflowBlock, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_meta_annotation() {
        let src = "@meta pos=42\n(x)print()\n";
        let prog = parse(src).unwrap();
        assert_eq!(prog.body.len(), 1);
        match &prog.body[0] {
            Statement::FuncCall(fc) => {
                let meta = fc.metadata.as_ref().expect("metadata should be set");
                assert_eq!(meta[0].data.get("pos"), Some(&Value::Int(42)));
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn test_parse_wildcard_output() {
        let prog = parse("(x)discard(_, result)\n").unwrap();
        match &prog.body[0] {
            Statement::FuncCall(fc) => {
                assert_eq!(fc.outputs[0], OutputTarget::Wildcard);
                assert_eq!(fc.outputs[1], OutputTarget::Name("result".into()));
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn test_parse_empty_call() {
        let prog = parse("()generate(value)\n").unwrap();
        match &prog.body[0] {
            Statement::FuncCall(fc) => {
                assert!(fc.inputs.is_empty());
                assert_eq!(fc.func_name, "generate");
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn test_parse_dotted_func_name() {
        let prog = parse("(x)image.blur(out)\n").unwrap();
        match &prog.body[0] {
            Statement::FuncCall(fc) => assert_eq!(fc.func_name, "image.blur"),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn test_parse_float_literal() {
        let prog = parse("x = 3.14\n").unwrap();
        match &prog.body[0] {
            Statement::Assignment(a) => {
                assert_literal(&a.value, &Value::Float(3.14), "float");
            }
            other => panic!("{other:?}"),
        }
    }

    // -----------------------------------------------------------------------
    // Integration tests: parse each .kir file in examples/kir_basics/
    // -----------------------------------------------------------------------

    fn kir_examples_dir() -> std::path::PathBuf {
        // Navigate from the crate root (kohakunode-rs/) up to the repo root.
        let manifest = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        manifest
            .parent() // src/
            .unwrap()
            .parent() // repo root
            .unwrap()
            .join("examples")
            .join("kir_basics")
    }

    #[test]
    fn test_parse_hello_world_kir() {
        let path = kir_examples_dir().join("hello_world.kir");
        let src = fs::read_to_string(&path).unwrap_or_else(|_| panic!("cannot read {path:?}"));
        parse(&src).unwrap_or_else(|e| panic!("hello_world.kir failed: {e}"));
    }

    #[test]
    fn test_parse_basic_math_kir() {
        let path = kir_examples_dir().join("basic_math.kir");
        let src = fs::read_to_string(&path).unwrap_or_else(|_| panic!("cannot read {path:?}"));
        parse(&src).unwrap_or_else(|e| panic!("basic_math.kir failed: {e}"));
    }

    #[test]
    fn test_parse_branching_kir() {
        let path = kir_examples_dir().join("branching.kir");
        let src = fs::read_to_string(&path).unwrap_or_else(|_| panic!("cannot read {path:?}"));
        parse(&src).unwrap_or_else(|e| panic!("branching.kir failed: {e}"));
    }

    #[test]
    fn test_parse_control_flow_kir() {
        let path = kir_examples_dir().join("control_flow.kir");
        let src = fs::read_to_string(&path).unwrap_or_else(|_| panic!("cannot read {path:?}"));
        parse(&src).unwrap_or_else(|e| panic!("control_flow.kir failed: {e}"));
    }

    #[test]
    fn test_parse_switch_demo_kir() {
        let path = kir_examples_dir().join("switch_demo.kir");
        let src = fs::read_to_string(&path).unwrap_or_else(|_| panic!("cannot read {path:?}"));
        parse(&src).unwrap_or_else(|e| panic!("switch_demo.kir failed: {e}"));
    }

    #[test]
    fn test_parse_parallel_demo_kir() {
        let path = kir_examples_dir().join("parallel_demo.kir");
        let src = fs::read_to_string(&path).unwrap_or_else(|_| panic!("cannot read {path:?}"));
        parse(&src).unwrap_or_else(|e| panic!("parallel_demo.kir failed: {e}"));
    }

    #[test]
    fn test_parse_subgraph_demo_kir() {
        let path = kir_examples_dir().join("subgraph_demo.kir");
        let src = fs::read_to_string(&path).unwrap_or_else(|_| panic!("cannot read {path:?}"));
        parse(&src).unwrap_or_else(|e| panic!("subgraph_demo.kir failed: {e}"));
    }

    #[test]
    fn test_parse_data_pipeline_kir() {
        let path = kir_examples_dir().join("data_pipeline.kir");
        let src = fs::read_to_string(&path).unwrap_or_else(|_| panic!("cannot read {path:?}"));
        parse(&src).unwrap_or_else(|e| panic!("data_pipeline.kir failed: {e}"));
    }

    #[test]
    fn test_parse_string_processing_kir() {
        let path = kir_examples_dir().join("string_processing.kir");
        let src = fs::read_to_string(&path).unwrap_or_else(|_| panic!("cannot read {path:?}"));
        parse(&src).unwrap_or_else(|e| panic!("string_processing.kir failed: {e}"));
    }

    #[test]
    fn test_parse_mixed_mode_kir() {
        let path = kir_examples_dir().join("mixed_mode.kir");
        let src = fs::read_to_string(&path).unwrap_or_else(|_| panic!("cannot read {path:?}"));
        parse(&src).unwrap_or_else(|e| panic!("mixed_mode.kir failed: {e}"));
    }
}
