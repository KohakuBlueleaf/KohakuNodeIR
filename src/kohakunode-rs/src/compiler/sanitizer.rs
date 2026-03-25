//! Configurable L3 Sanitizer that composes compiler passes.
//!
//! Mirror of `kohakunode/compiler/sanitizer.py`.

use crate::ast::Program;
use crate::compiler::dataflow::compile_dataflow;
use crate::compiler::dead_code::dead_code;
use crate::compiler::strip_meta::strip_meta;
use crate::compiler::type_check::type_check;

// ---------------------------------------------------------------------------
// SanitizerConfig
// ---------------------------------------------------------------------------

/// Feature flags controlling which passes the :struct:`Sanitizer` runs.
///
/// All flags default to `true` (all passes enabled).
#[derive(Clone, Debug, PartialEq)]
pub struct SanitizerConfig {
    /// Run `strip_meta` — remove @meta annotations (L2 → L3).
    pub strip_meta: bool,
    /// Run `compile_dataflow` — topologically sort dataflow statements.
    pub resolve_dataflow: bool,
    /// Run `type_check` — validate types against @typehint declarations.
    pub type_check: bool,
    /// Run `dead_code` — remove unused assignments.
    pub remove_dead_code: bool,
}

impl Default for SanitizerConfig {
    fn default() -> Self {
        SanitizerConfig {
            strip_meta: true,
            resolve_dataflow: true,
            type_check: true,
            remove_dead_code: true,
        }
    }
}

// ---------------------------------------------------------------------------
// Sanitizer
// ---------------------------------------------------------------------------

/// Apply enabled sanitizer passes to *program* in fixed order:
///
/// 1. `strip_meta`       — remove @meta annotations
/// 2. `resolve_dataflow` — topologically sort dataflow statements
/// 3. `type_check`       — validate types against @typehint declarations
/// 4. `remove_dead_code` — eliminate unused assignments
///
/// # Errors
///
/// Returns `Err(Vec<String>)` if `type_check` is enabled and finds type
/// mismatches, or `Err(vec![String])` if `resolve_dataflow` encounters a
/// cycle or illegal construct.
pub fn sanitize(
    program: &Program,
    config: &SanitizerConfig,
) -> Result<Program, Vec<String>> {
    let mut current = program.clone();

    if config.strip_meta {
        current = strip_meta(&current);
    }

    if config.resolve_dataflow {
        current = compile_dataflow(&current).map_err(|e| vec![e])?;
    }

    if config.type_check {
        current = type_check(&current)?;
    }

    if config.remove_dead_code {
        current = dead_code(&current);
    }

    Ok(current)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ast::{
        Assignment, Expression, FuncCall, Identifier, Literal, MetaAnnotation, OutputTarget,
        Program, Statement, TypeExpr, TypeHintEntry, Value,
    };
    use std::collections::HashMap;

    fn int_lit_expr() -> Expression {
        Expression::Literal(Literal {
            value: Value::Int(1),
            literal_type: "int".into(),
            line: None,
        })
    }

    fn id_expr(name: &str) -> Expression {
        Expression::Identifier(Identifier {
            name: name.into(),
            line: None,
        })
    }

    fn dummy_meta() -> Vec<MetaAnnotation> {
        let mut data = HashMap::new();
        data.insert("node_id".to_string(), Value::Str("abc".to_string()));
        vec![MetaAnnotation { data, line: None }]
    }

    fn int_type() -> TypeExpr {
        TypeExpr {
            name: "int".to_string(),
            is_optional: false,
            union_of: None,
            line: None,
        }
    }

    // ------------------------------------------------------------------
    // strip_meta toggle
    // ------------------------------------------------------------------

    #[test]
    fn strip_meta_toggle_works() {
        let prog = Program {
            body: vec![Statement::Assignment(Assignment {
                target: "x".into(),
                value: int_lit_expr(),
                type_annotation: None,
                metadata: Some(dummy_meta()),
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };

        // With strip_meta ON
        let cfg_on = SanitizerConfig {
            strip_meta: true,
            resolve_dataflow: false,
            type_check: false,
            remove_dead_code: false,
        };
        let result = sanitize(&prog, &cfg_on).unwrap();
        match &result.body[0] {
            Statement::Assignment(a) => assert!(a.metadata.is_none()),
            other => panic!("unexpected {other:?}"),
        }

        // With strip_meta OFF
        let cfg_off = SanitizerConfig {
            strip_meta: false,
            resolve_dataflow: false,
            type_check: false,
            remove_dead_code: false,
        };
        let result_off = sanitize(&prog, &cfg_off).unwrap();
        match &result_off.body[0] {
            Statement::Assignment(a) => assert!(a.metadata.is_some()),
            other => panic!("unexpected {other:?}"),
        }
    }

    // ------------------------------------------------------------------
    // type_check toggle
    // ------------------------------------------------------------------

    #[test]
    fn type_check_toggle_errors_when_on() {
        // add expects (int, int), we pass a float
        let hint = TypeHintEntry {
            func_name: "add".into(),
            input_types: vec![int_type(), int_type()],
            output_types: vec![int_type()],
            line: None,
        };
        let float_expr = Expression::Literal(Literal {
            value: Value::Float(1.0),
            literal_type: "float".into(),
            line: None,
        });
        let prog = Program {
            body: vec![Statement::FuncCall(FuncCall {
                inputs: vec![float_expr, int_lit_expr()],
                func_name: "add".into(),
                outputs: vec![OutputTarget::Name("r".into())],
                metadata: None,
                line: Some(1),
            })],
            mode: None,
            typehints: Some(vec![hint]),
            line: None,
        };

        let cfg_on = SanitizerConfig {
            strip_meta: false,
            resolve_dataflow: false,
            type_check: true,
            remove_dead_code: false,
        };
        assert!(sanitize(&prog, &cfg_on).is_err());

        let cfg_off = SanitizerConfig {
            strip_meta: false,
            resolve_dataflow: false,
            type_check: false,
            remove_dead_code: false,
        };
        assert!(sanitize(&prog, &cfg_off).is_ok());
    }

    // ------------------------------------------------------------------
    // remove_dead_code toggle
    // ------------------------------------------------------------------

    #[test]
    fn dead_code_toggle_works() {
        // x = 1 (never used)
        let prog = Program {
            body: vec![Statement::Assignment(Assignment {
                target: "x".into(),
                value: int_lit_expr(),
                type_annotation: None,
                metadata: None,
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };

        let cfg_on = SanitizerConfig {
            strip_meta: false,
            resolve_dataflow: false,
            type_check: false,
            remove_dead_code: true,
        };
        let result = sanitize(&prog, &cfg_on).unwrap();
        assert!(result.body.is_empty(), "dead assignment should be removed");

        let cfg_off = SanitizerConfig {
            strip_meta: false,
            resolve_dataflow: false,
            type_check: false,
            remove_dead_code: false,
        };
        let result_off = sanitize(&prog, &cfg_off).unwrap();
        assert_eq!(result_off.body.len(), 1, "assignment should be kept when dead_code is off");
    }

    // ------------------------------------------------------------------
    // All passes together — default config
    // ------------------------------------------------------------------

    #[test]
    fn default_config_runs_all_passes() {
        let prog = Program {
            body: vec![Statement::Assignment(Assignment {
                target: "x".into(),
                value: int_lit_expr(),
                type_annotation: None,
                metadata: Some(dummy_meta()),
                line: None,
            })],
            mode: None,
            typehints: None,
            line: None,
        };
        let result = sanitize(&prog, &SanitizerConfig::default()).unwrap();
        // meta stripped AND x dead-eliminated
        assert!(result.body.is_empty());
    }
}
