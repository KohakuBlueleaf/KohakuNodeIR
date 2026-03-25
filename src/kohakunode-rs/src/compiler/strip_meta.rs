//! IR pass that strips @meta annotations from all statements (L2 → L3).
//!
//! Port of `kohakunode/compiler/strip_meta.py`.

use crate::ast::{
    Assignment, Branch, FuncCall, Jump, Namespace, Parallel, Program, Statement, SubgraphDef,
    Switch,
};

/// Remove all `@meta` annotations from every statement in *program*.
///
/// Converts Level 2 KIR (with metadata for round-tripping) into
/// Level 3 KIR (pure execution logic). Recurses into `Namespace` and
/// `SubgraphDef` bodies.
pub fn strip_meta(program: &Program) -> Program {
    Program {
        body: strip_body(&program.body),
        mode: program.mode.clone(),
        line: program.line,
    }
}

fn strip_body(stmts: &[Statement]) -> Vec<Statement> {
    stmts.iter().map(strip_stmt).collect()
}

fn strip_stmt(stmt: &Statement) -> Statement {
    match stmt {
        Statement::Assignment(a) => Statement::Assignment(Assignment {
            target: a.target.clone(),
            value: a.value.clone(),
            metadata: None,
            line: a.line,
        }),
        Statement::FuncCall(f) => Statement::FuncCall(FuncCall {
            inputs: f.inputs.clone(),
            func_name: f.func_name.clone(),
            outputs: f.outputs.clone(),
            metadata: None,
            line: f.line,
        }),
        Statement::Branch(b) => Statement::Branch(Branch {
            condition: b.condition.clone(),
            true_label: b.true_label.clone(),
            false_label: b.false_label.clone(),
            metadata: None,
            line: b.line,
        }),
        Statement::Switch(s) => Statement::Switch(Switch {
            value: s.value.clone(),
            cases: s.cases.clone(),
            default_label: s.default_label.clone(),
            metadata: None,
            line: s.line,
        }),
        Statement::Jump(j) => Statement::Jump(Jump {
            target: j.target.clone(),
            metadata: None,
            line: j.line,
        }),
        Statement::Parallel(p) => Statement::Parallel(Parallel {
            labels: p.labels.clone(),
            metadata: None,
            line: p.line,
        }),
        Statement::Namespace(ns) => Statement::Namespace(Namespace {
            name: ns.name.clone(),
            body: strip_body(&ns.body),
            line: ns.line,
        }),
        Statement::SubgraphDef(sg) => Statement::SubgraphDef(SubgraphDef {
            name: sg.name.clone(),
            params: sg.params.clone(),
            outputs: sg.outputs.clone(),
            body: strip_body(&sg.body),
            line: sg.line,
        }),
        // ModeDecl and DataflowBlock carry no metadata — pass through unchanged.
        other => other.clone(),
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ast::{Expression, Identifier, MetaAnnotation, Value};
    use std::collections::HashMap;

    fn dummy_meta() -> Vec<MetaAnnotation> {
        let mut data = HashMap::new();
        data.insert("node_id".to_string(), Value::Str("abc".to_string()));
        vec![MetaAnnotation { data, line: None }]
    }

    #[test]
    fn strip_assignment_metadata() {
        let prog = Program {
            body: vec![Statement::Assignment(Assignment {
                target: "x".into(),
                value: Expression::Identifier(Identifier {
                    name: "y".into(),
                    line: None,
                }),
                metadata: Some(dummy_meta()),
                line: Some(1),
            })],
            mode: None,
            line: None,
        };

        let result = strip_meta(&prog);
        match &result.body[0] {
            Statement::Assignment(a) => {
                assert!(a.metadata.is_none(), "metadata should be stripped");
                assert_eq!(a.target, "x");
                assert_eq!(a.line, Some(1));
            }
            other => panic!("expected Assignment, got {other:?}"),
        }
    }

    #[test]
    fn strip_func_call_metadata() {
        let prog = Program {
            body: vec![Statement::FuncCall(FuncCall {
                inputs: vec![],
                func_name: "foo".into(),
                outputs: vec![],
                metadata: Some(dummy_meta()),
                line: None,
            })],
            mode: None,
            line: None,
        };

        let result = strip_meta(&prog);
        match &result.body[0] {
            Statement::FuncCall(f) => assert!(f.metadata.is_none()),
            other => panic!("expected FuncCall, got {other:?}"),
        }
    }

    #[test]
    fn strip_branch_metadata() {
        let prog = Program {
            body: vec![Statement::Branch(Branch {
                condition: Expression::Identifier(Identifier {
                    name: "cond".into(),
                    line: None,
                }),
                true_label: "yes".into(),
                false_label: "no".into(),
                metadata: Some(dummy_meta()),
                line: None,
            })],
            mode: None,
            line: None,
        };

        let result = strip_meta(&prog);
        match &result.body[0] {
            Statement::Branch(b) => assert!(b.metadata.is_none()),
            other => panic!("expected Branch, got {other:?}"),
        }
    }

    #[test]
    fn strip_jump_metadata() {
        let prog = Program {
            body: vec![Statement::Jump(Jump {
                target: "loop_top".into(),
                metadata: Some(dummy_meta()),
                line: None,
            })],
            mode: None,
            line: None,
        };

        let result = strip_meta(&prog);
        match &result.body[0] {
            Statement::Jump(j) => assert!(j.metadata.is_none()),
            other => panic!("expected Jump, got {other:?}"),
        }
    }

    #[test]
    fn strip_parallel_metadata() {
        let prog = Program {
            body: vec![Statement::Parallel(Parallel {
                labels: vec!["a".into(), "b".into()],
                metadata: Some(dummy_meta()),
                line: None,
            })],
            mode: None,
            line: None,
        };

        let result = strip_meta(&prog);
        match &result.body[0] {
            Statement::Parallel(p) => assert!(p.metadata.is_none()),
            other => panic!("expected Parallel, got {other:?}"),
        }
    }

    #[test]
    fn strip_namespace_recurses() {
        let prog = Program {
            body: vec![Statement::Namespace(Namespace {
                name: "ns".into(),
                body: vec![Statement::FuncCall(FuncCall {
                    inputs: vec![],
                    func_name: "bar".into(),
                    outputs: vec![],
                    metadata: Some(dummy_meta()),
                    line: None,
                })],
                line: None,
            })],
            mode: None,
            line: None,
        };

        let result = strip_meta(&prog);
        match &result.body[0] {
            Statement::Namespace(ns) => match &ns.body[0] {
                Statement::FuncCall(f) => assert!(f.metadata.is_none()),
                other => panic!("expected FuncCall inside Namespace, got {other:?}"),
            },
            other => panic!("expected Namespace, got {other:?}"),
        }
    }

    #[test]
    fn strip_preserves_mode() {
        let prog = Program {
            body: vec![],
            mode: Some("dataflow".into()),
            line: None,
        };
        let result = strip_meta(&prog);
        assert_eq!(result.mode, Some("dataflow".into()));
    }

    #[test]
    fn strip_no_metadata_is_noop() {
        let prog = Program {
            body: vec![Statement::Assignment(Assignment {
                target: "z".into(),
                value: Expression::Identifier(Identifier {
                    name: "w".into(),
                    line: None,
                }),
                metadata: None,
                line: None,
            })],
            mode: None,
            line: None,
        };
        let result = strip_meta(&prog);
        assert_eq!(result, prog);
    }
}
