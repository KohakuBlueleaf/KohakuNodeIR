//! Dead code elimination pass — remove assignments whose outputs are never used.
//!
//! Mirror of `kohakunode/compiler/dead_code.py`.

use std::collections::HashSet;

use crate::ast::{Expression, Namespace, Program, Statement, SubgraphDef, TryExcept};

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Remove assignments whose target variable is never referenced by any other
/// statement in the same (or child) scope.
///
/// FuncCalls are always preserved (potential side effects).
/// Control-flow nodes (Branch, Switch, Jump, Parallel) are always preserved.
/// TypeHintBlock nodes are always preserved.
///
/// The function applies a fixed-point loop: it keeps eliminating until no
/// more dead assignments remain.
pub fn dead_code(program: &Program) -> Program {
    let new_body = eliminate_body(&program.body);
    Program {
        body: new_body,
        mode: program.mode.clone(),
        typehints: program.typehints.clone(),
        line: program.line,
    }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

fn collect_used_names(stmts: &[Statement]) -> HashSet<String> {
    let mut used = HashSet::new();
    for stmt in stmts {
        collect_used_in_stmt(stmt, &mut used);
    }
    used
}

fn collect_used_in_expr(expr: &Expression, used: &mut HashSet<String>) {
    match expr {
        Expression::Identifier(id) => {
            used.insert(id.name.clone());
        }
        Expression::KeywordArg(kw) => {
            collect_used_in_expr(&kw.value, used);
        }
        _ => {}
    }
}

fn collect_used_in_stmt(stmt: &Statement, used: &mut HashSet<String>) {
    match stmt {
        Statement::Assignment(a) => {
            collect_used_in_expr(&a.value, used);
        }
        Statement::FuncCall(f) => {
            for inp in &f.inputs {
                collect_used_in_expr(inp, used);
            }
        }
        Statement::Branch(b) => {
            collect_used_in_expr(&b.condition, used);
        }
        Statement::Switch(s) => {
            collect_used_in_expr(&s.value, used);
            for (case_expr, _) in &s.cases {
                collect_used_in_expr(case_expr, used);
            }
        }
        Statement::Namespace(ns) => {
            for s in &ns.body {
                collect_used_in_stmt(s, used);
            }
        }
        Statement::SubgraphDef(sg) => {
            for s in &sg.body {
                collect_used_in_stmt(s, used);
            }
        }
        Statement::TryExcept(t) => {
            for s in &t.try_body {
                collect_used_in_stmt(s, used);
            }
            for s in &t.except_body {
                collect_used_in_stmt(s, used);
            }
        }
        _ => {}
    }
}

fn eliminate_body(stmts: &[Statement]) -> Vec<Statement> {
    let mut current: Vec<Statement> = stmts.to_vec();

    loop {
        let used = collect_used_names(&current);
        let mut new_stmts: Vec<Statement> = Vec::with_capacity(current.len());
        let mut changed = false;

        for stmt in &current {
            match stmt {
                Statement::Assignment(a) => {
                    if !used.contains(&a.target) {
                        // Dead — drop
                        changed = true;
                        continue;
                    }
                    new_stmts.push(stmt.clone());
                }
                Statement::Namespace(ns) => {
                    let new_body = eliminate_body(&ns.body);
                    if new_body != ns.body {
                        changed = true;
                    }
                    new_stmts.push(Statement::Namespace(Namespace {
                        name: ns.name.clone(),
                        body: new_body,
                        line: ns.line,
                    }));
                }
                Statement::SubgraphDef(sg) => {
                    let new_body = eliminate_body(&sg.body);
                    if new_body != sg.body {
                        changed = true;
                    }
                    new_stmts.push(Statement::SubgraphDef(SubgraphDef {
                        name: sg.name.clone(),
                        params: sg.params.clone(),
                        outputs: sg.outputs.clone(),
                        body: new_body,
                        line: sg.line,
                    }));
                }
                Statement::TryExcept(t) => {
                    let new_try = eliminate_body(&t.try_body);
                    let new_except = eliminate_body(&t.except_body);
                    if new_try != t.try_body || new_except != t.except_body {
                        changed = true;
                    }
                    new_stmts.push(Statement::TryExcept(TryExcept {
                        try_body: new_try,
                        except_body: new_except,
                        metadata: t.metadata.clone(),
                        line: t.line,
                    }));
                }
                other => new_stmts.push(other.clone()),
            }
        }

        if !changed {
            return new_stmts;
        }
        current = new_stmts;
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ast::{Assignment, Expression, FuncCall, Identifier, Literal, OutputTarget, Value};

    fn assign(target: &str, value: Expression) -> Statement {
        Statement::Assignment(Assignment {
            target: target.into(),
            value,
            type_annotation: None,
            metadata: None,
            line: None,
        })
    }

    fn id_expr(name: &str) -> Expression {
        Expression::Identifier(Identifier {
            name: name.into(),
            line: None,
        })
    }

    fn int_lit() -> Expression {
        Expression::Literal(Literal {
            value: Value::Int(1),
            literal_type: "int".into(),
            line: None,
        })
    }

    fn func_call(inputs: Vec<Expression>, func_name: &str, outputs: Vec<&str>) -> Statement {
        Statement::FuncCall(FuncCall {
            inputs,
            func_name: func_name.into(),
            outputs: outputs
                .into_iter()
                .map(|n| OutputTarget::Name(n.into()))
                .collect(),
            metadata: None,
            line: None,
        })
    }

    // ------------------------------------------------------------------
    // Unused assignment removed
    // ------------------------------------------------------------------

    #[test]
    fn unused_assignment_removed() {
        // x = 1   (never used)
        // y = f() (side effect, kept)
        let prog = Program {
            body: vec![
                assign("x", int_lit()),
                func_call(vec![], "f", vec!["y"]),
            ],
            mode: None,
            typehints: None,
            line: None,
        };
        let result = dead_code(&prog);
        // x should be gone
        assert!(
            result
                .body
                .iter()
                .all(|s| !matches!(s, Statement::Assignment(a) if a.target == "x")),
            "unused assignment 'x' should be removed"
        );
        // y should remain
        assert!(
            result
                .body
                .iter()
                .any(|s| matches!(s, Statement::FuncCall(f) if f.func_name == "f")),
            "func call should be kept"
        );
    }

    // ------------------------------------------------------------------
    // Used assignment kept
    // ------------------------------------------------------------------

    #[test]
    fn used_assignment_kept() {
        // x = 1
        // (x)print()
        let prog = Program {
            body: vec![
                assign("x", int_lit()),
                func_call(vec![id_expr("x")], "print", vec![]),
            ],
            mode: None,
            typehints: None,
            line: None,
        };
        let result = dead_code(&prog);
        assert!(
            result
                .body
                .iter()
                .any(|s| matches!(s, Statement::Assignment(a) if a.target == "x")),
            "used assignment 'x' should be kept"
        );
    }

    // ------------------------------------------------------------------
    // FuncCall always kept even with unused outputs
    // ------------------------------------------------------------------

    #[test]
    fn func_call_always_kept() {
        // z = side_effect() but z is never used
        let prog = Program {
            body: vec![func_call(vec![], "side_effect", vec!["z"])],
            mode: None,
            typehints: None,
            line: None,
        };
        let result = dead_code(&prog);
        assert!(
            result
                .body
                .iter()
                .any(|s| matches!(s, Statement::FuncCall(f) if f.func_name == "side_effect")),
            "FuncCall should always be kept"
        );
    }

    // ------------------------------------------------------------------
    // Chain: only remove the root dead assignment
    // ------------------------------------------------------------------

    #[test]
    fn chain_dead_propagates() {
        // a = 1  (only used by b)
        // b = a  (only used by c)
        // c = b  (never used — dead)
        // After one pass c is dead, then b is dead, then a is dead.
        let prog = Program {
            body: vec![
                assign("a", int_lit()),
                assign("b", id_expr("a")),
                assign("c", id_expr("b")),
            ],
            mode: None,
            typehints: None,
            line: None,
        };
        let result = dead_code(&prog);
        assert!(
            result.body.is_empty(),
            "all three should be eliminated as a chain"
        );
    }
}
