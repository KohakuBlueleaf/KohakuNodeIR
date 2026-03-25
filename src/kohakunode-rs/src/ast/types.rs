//! AST types for KohakuNodeIR.
//!
//! Matches the Python `kohakunode.ast.nodes` dataclasses exactly.
//! Each type is `Clone + Debug + PartialEq + Serialize + Deserialize`.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

fn is_false(b: &bool) -> bool {
    !*b
}

// ---------------------------------------------------------------------------
// Literal value — dynamically typed
// ---------------------------------------------------------------------------

/// A dynamically typed value (used in Literal nodes and MetaAnnotation data).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Value {
    None,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    List(Vec<Value>),
    Dict(HashMap<String, Value>),
}

impl Default for Value {
    fn default() -> Self {
        Value::None
    }
}

// ---------------------------------------------------------------------------
// Expressions
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum Expression {
    Identifier(Identifier),
    Literal(Literal),
    KeywordArg(KeywordArg),
    LabelRef(LabelRef),
    Wildcard(Wildcard),
}

impl Default for Expression {
    fn default() -> Self {
        Expression::Identifier(Identifier::default())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Identifier {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Literal {
    pub value: Value,
    /// One of: "int", "float", "str", "bool", "none", "list", "dict"
    pub literal_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct KeywordArg {
    pub name: String,
    pub value: Box<Expression>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct LabelRef {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Wildcard {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

// ---------------------------------------------------------------------------
// Other nodes
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct MetaAnnotation {
    pub data: HashMap<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Parameter {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub default: Option<Expression>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

// ---------------------------------------------------------------------------
// Type expressions (used by @typehint)
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct TypeExpr {
    pub name: String,
    #[serde(default, skip_serializing_if = "is_false")]
    pub is_optional: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub union_of: Option<Vec<TypeExpr>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct TypeHintEntry {
    pub func_name: String,
    pub input_types: Vec<TypeExpr>,
    pub output_types: Vec<TypeExpr>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct TypeHintBlock {
    pub entries: Vec<TypeHintEntry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

// ---------------------------------------------------------------------------
// Output target (either a variable name or a wildcard)
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum OutputTarget {
    Name(String),
    Wildcard,
}

impl Default for OutputTarget {
    fn default() -> Self {
        OutputTarget::Name(String::new())
    }
}

// ---------------------------------------------------------------------------
// Statements
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum Statement {
    Assignment(Assignment),
    FuncCall(FuncCall),
    Namespace(Namespace),
    SubgraphDef(SubgraphDef),
    DataflowBlock(DataflowBlock),
    ModeDecl(ModeDecl),
    Branch(Branch),
    Switch(Switch),
    Jump(Jump),
    Parallel(Parallel),
    TypeHintBlock(TypeHintBlock),
    TryExcept(TryExcept),
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct TryExcept {
    pub try_body: Vec<Statement>,
    pub except_body: Vec<Statement>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<Vec<MetaAnnotation>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Assignment {
    pub target: String,
    pub value: Expression,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub type_annotation: Option<TypeExpr>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<Vec<MetaAnnotation>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct FuncCall {
    pub inputs: Vec<Expression>,
    pub func_name: String,
    pub outputs: Vec<OutputTarget>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<Vec<MetaAnnotation>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Namespace {
    pub name: String,
    pub body: Vec<Statement>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct SubgraphDef {
    pub name: String,
    pub params: Vec<Parameter>,
    pub outputs: Vec<String>,
    pub body: Vec<Statement>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct DataflowBlock {
    pub body: Vec<Statement>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct ModeDecl {
    pub mode: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Branch {
    pub condition: Expression,
    pub true_label: String,
    pub false_label: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<Vec<MetaAnnotation>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Switch {
    pub value: Expression,
    pub cases: Vec<(Expression, String)>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub default_label: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<Vec<MetaAnnotation>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Jump {
    pub target: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<Vec<MetaAnnotation>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Parallel {
    pub labels: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<Vec<MetaAnnotation>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

// ---------------------------------------------------------------------------
// Root node
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Program {
    pub body: Vec<Statement>,
    /// "dataflow" or None
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mode: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub typehints: Option<Vec<TypeHintEntry>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_program_default() {
        let p = Program::default();
        assert!(p.body.is_empty());
        assert!(p.mode.is_none());
    }

    #[test]
    fn test_func_call() {
        let fc = FuncCall {
            inputs: vec![
                Expression::Identifier(Identifier {
                    name: "x".into(),
                    line: None,
                }),
                Expression::Literal(Literal {
                    value: Value::Int(42),
                    literal_type: "int".into(),
                    line: None,
                }),
            ],
            func_name: "add".into(),
            outputs: vec![OutputTarget::Name("result".into())],
            metadata: None,
            line: Some(1),
        };
        assert_eq!(fc.func_name, "add");
        assert_eq!(fc.inputs.len(), 2);
    }

    #[test]
    fn test_branch() {
        let b = Branch {
            condition: Expression::Identifier(Identifier {
                name: "cond".into(),
                line: None,
            }),
            true_label: "yes".into(),
            false_label: "no".into(),
            metadata: None,
            line: None,
        };
        assert_eq!(b.true_label, "yes");
    }

    #[test]
    fn test_json_roundtrip() {
        let prog = Program {
            body: vec![Statement::Assignment(Assignment {
                target: "x".into(),
                value: Expression::Literal(Literal {
                    value: Value::Int(42),
                    literal_type: "int".into(),
                    line: None,
                }),
                type_annotation: None,
                metadata: None,
                line: Some(1),
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        let json = serde_json::to_string(&prog).unwrap();
        let parsed: Program = serde_json::from_str(&json).unwrap();
        assert_eq!(prog, parsed);
    }
}
