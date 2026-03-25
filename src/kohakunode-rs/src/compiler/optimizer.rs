//! L4 compiler optimizer: ParallelPathDetector, BranchSimplifier,
//! DeadNamespaceEliminator, CommonSubexprEliminator.
//!
//! Mirror of `kohakunode/compiler/optimizer.py`.

use std::collections::{HashMap, HashSet};

use crate::ast::{
    Assignment, Expression, FuncCall, Identifier, Jump, Namespace, OutputTarget, Parallel,
    Program, Statement, SubgraphDef, TryExcept,
};

use crate::compiler::dead_code::dead_code;

// ---------------------------------------------------------------------------
// Known sub-pass names
// ---------------------------------------------------------------------------

pub const ALL_PASSES: &[&str] = &["parallel_detect", "branch_simplify", "dead_code", "cse"];

// ---------------------------------------------------------------------------
// Optimizer entry point
// ---------------------------------------------------------------------------

/// Apply a sequence of L4 optimization sub-passes to *program*.
///
/// # Parameters
/// - `passes`: ordered list of sub-pass names to run. `None` means all four.
///
/// # Errors
/// Returns `Err(String)` if an unknown sub-pass name is supplied.
pub fn optimize(program: &Program, passes: Option<&[&str]>) -> Result<Program, String> {
    let selected: Vec<&str> = match passes {
        Some(p) => p.to_vec(),
        None => ALL_PASSES.to_vec(),
    };

    // Validate
    for name in &selected {
        if !ALL_PASSES.contains(name) {
            return Err(format!(
                "Unknown optimizer sub-pass '{}'. Valid options: {:?}",
                name, ALL_PASSES
            ));
        }
    }

    let mut current = program.clone();
    for name in &selected {
        current = match *name {
            "parallel_detect" => parallel_detect(&current),
            "branch_simplify" => {
                let simplified = branch_simplify(&current);
                dead_namespace_eliminate(&simplified)
            }
            "dead_code" => dead_code(&current),
            "cse" => cse(&current),
            _ => unreachable!(),
        };
    }

    Ok(current)
}

// ---------------------------------------------------------------------------
// ParallelPathDetector
// ---------------------------------------------------------------------------

/// Detect independent statement groups and wrap them in Namespace + Parallel.
pub fn parallel_detect(program: &Program) -> Program {
    let stmts = &program.body;
    if stmts.len() < 2 {
        return program.clone();
    }

    let outputs_per: Vec<HashSet<String>> = stmts.iter().map(stmt_outputs).collect();
    let inputs_per: Vec<HashSet<String>> = stmts.iter().map(stmt_inputs).collect();

    // Union-Find
    let mut parent: Vec<usize> = (0..stmts.len()).collect();

    fn find(parent: &mut Vec<usize>, x: usize) -> usize {
        if parent[x] != x {
            parent[x] = {
                let p = parent[x];
                find(parent, p)
            };
        }
        parent[x]
    }

    fn union(parent: &mut Vec<usize>, x: usize, y: usize) {
        let rx = find(parent, x);
        let ry = find(parent, y);
        parent[rx] = ry;
    }

    for i in 0..stmts.len() {
        for j in (i + 1)..stmts.len() {
            if !outputs_per[i].is_disjoint(&inputs_per[j])
                || !outputs_per[j].is_disjoint(&inputs_per[i])
            {
                union(&mut parent, i, j);
            }
        }
    }

    // Group by root
    let mut groups: HashMap<usize, Vec<usize>> = HashMap::new();
    for i in 0..stmts.len() {
        let root = find(&mut parent, i);
        groups.entry(root).or_default().push(i);
    }

    if groups.len() < 2 {
        return program.clone();
    }

    // Build namespace wrappers + parallel node
    let mut new_body: Vec<Statement> = Vec::new();
    let mut labels: Vec<String> = Vec::new();
    let mut sorted_groups: Vec<Vec<usize>> = groups.into_values().collect();
    sorted_groups.sort_by_key(|g| g[0]);

    for (g_idx, idxs) in sorted_groups.iter().enumerate() {
        let label = format!("__parallel_group_{g_idx}");
        labels.push(label.clone());
        let mut sorted_idxs = idxs.clone();
        sorted_idxs.sort_unstable();
        let ns_body: Vec<Statement> = sorted_idxs.iter().map(|&i| stmts[i].clone()).collect();
        new_body.push(Statement::Namespace(Namespace {
            name: label,
            body: ns_body,
            line: None,
        }));
    }

    new_body.push(Statement::Parallel(Parallel {
        labels,
        metadata: None,
        line: None,
    }));

    Program {
        body: new_body,
        mode: program.mode.clone(),
        typehints: program.typehints.clone(),
        line: program.line,
    }
}

// ---------------------------------------------------------------------------
// BranchSimplifier
// ---------------------------------------------------------------------------

/// Replace Branch nodes with literal True/False conditions with Jump nodes.
pub fn branch_simplify(program: &Program) -> Program {
    let new_body = simplify_body(&program.body);
    Program {
        body: new_body,
        mode: program.mode.clone(),
        typehints: program.typehints.clone(),
        line: program.line,
    }
}

fn simplify_body(stmts: &[Statement]) -> Vec<Statement> {
    stmts.iter().map(simplify_stmt).collect()
}

fn simplify_stmt(stmt: &Statement) -> Statement {
    match stmt {
        Statement::Branch(b) => {
            if let Expression::Literal(lit) = &b.condition {
                if lit.literal_type == "bool" {
                    match &lit.value {
                        crate::ast::Value::Bool(true) => {
                            return Statement::Jump(Jump {
                                target: b.true_label.clone(),
                                metadata: None,
                                line: b.line,
                            });
                        }
                        crate::ast::Value::Bool(false) => {
                            return Statement::Jump(Jump {
                                target: b.false_label.clone(),
                                metadata: None,
                                line: b.line,
                            });
                        }
                        _ => {}
                    }
                }
            }
            stmt.clone()
        }
        Statement::Namespace(ns) => Statement::Namespace(Namespace {
            name: ns.name.clone(),
            body: simplify_body(&ns.body),
            line: ns.line,
        }),
        Statement::SubgraphDef(sg) => Statement::SubgraphDef(SubgraphDef {
            name: sg.name.clone(),
            params: sg.params.clone(),
            outputs: sg.outputs.clone(),
            body: simplify_body(&sg.body),
            line: sg.line,
        }),
        Statement::TryExcept(t) => Statement::TryExcept(TryExcept {
            try_body: simplify_body(&t.try_body),
            except_body: simplify_body(&t.except_body),
            metadata: t.metadata.clone(),
            line: t.line,
        }),
        other => other.clone(),
    }
}

// ---------------------------------------------------------------------------
// DeadNamespaceEliminator
// ---------------------------------------------------------------------------

/// Remove Namespace nodes that are unreachable (not targeted by any jump).
pub fn dead_namespace_eliminate(program: &Program) -> Program {
    let reachable = collect_reachable_labels(&program.body);
    let new_body = remove_unreachable_namespaces(&program.body, &reachable);
    Program {
        body: new_body,
        mode: program.mode.clone(),
        typehints: program.typehints.clone(),
        line: program.line,
    }
}

fn collect_reachable_labels(stmts: &[Statement]) -> HashSet<String> {
    let mut labels = HashSet::new();
    for stmt in stmts {
        match stmt {
            Statement::Jump(j) => {
                labels.insert(j.target.clone());
            }
            Statement::Branch(b) => {
                labels.insert(b.true_label.clone());
                labels.insert(b.false_label.clone());
            }
            Statement::Switch(s) => {
                for (_, lbl) in &s.cases {
                    labels.insert(lbl.clone());
                }
                if let Some(ref dl) = s.default_label {
                    labels.insert(dl.clone());
                }
            }
            Statement::Parallel(p) => {
                labels.extend(p.labels.iter().cloned());
            }
            Statement::Namespace(ns) => {
                labels.extend(collect_reachable_labels(&ns.body));
            }
            Statement::SubgraphDef(sg) => {
                labels.extend(collect_reachable_labels(&sg.body));
            }
            _ => {}
        }
    }
    labels
}

fn remove_unreachable_namespaces(
    stmts: &[Statement],
    reachable: &HashSet<String>,
) -> Vec<Statement> {
    let mut result = Vec::new();
    for stmt in stmts {
        match stmt {
            Statement::Namespace(ns) => {
                if !reachable.contains(&ns.name) {
                    // Unreachable — drop
                    continue;
                }
                let new_body = remove_unreachable_namespaces(&ns.body, reachable);
                result.push(Statement::Namespace(Namespace {
                    name: ns.name.clone(),
                    body: new_body,
                    line: ns.line,
                }));
            }
            other => result.push(other.clone()),
        }
    }
    result
}

// ---------------------------------------------------------------------------
// CommonSubexprEliminator (CSE)
// ---------------------------------------------------------------------------

/// Eliminate duplicate FuncCalls with the same func_name + structurally
/// identical inputs, replacing later occurrences with assignments.
pub fn cse(program: &Program) -> Program {
    let new_body = cse_body(&program.body);
    Program {
        body: new_body,
        mode: program.mode.clone(),
        typehints: program.typehints.clone(),
        line: program.line,
    }
}

fn expr_key(expr: &Expression) -> String {
    match expr {
        Expression::Identifier(id) => format!("id:{}", id.name),
        Expression::Literal(lit) => format!("lit:{}:{:?}", lit.literal_type, lit.value),
        Expression::KeywordArg(kw) => format!("kw:{}:{}", kw.name, expr_key(&kw.value)),
        other => format!("other:{other:?}"),
    }
}

fn call_key(f: &FuncCall) -> String {
    let input_keys: Vec<String> = f.inputs.iter().map(expr_key).collect();
    format!("{}({})", f.func_name, input_keys.join(","))
}

fn cse_body(stmts: &[Statement]) -> Vec<Statement> {
    let mut seen: HashMap<String, Vec<String>> = HashMap::new();
    let mut result: Vec<Statement> = Vec::new();

    for stmt in stmts {
        match stmt {
            Statement::FuncCall(f) => {
                let key = call_key(f);
                let concrete: Vec<String> = f
                    .outputs
                    .iter()
                    .filter_map(|o| match o {
                        OutputTarget::Name(n) => Some(n.clone()),
                        OutputTarget::Wildcard => None,
                    })
                    .collect();

                if let Some(first_outputs) = seen.get(&key) {
                    if !concrete.is_empty() {
                        for (new_name, orig_name) in concrete.iter().zip(first_outputs.iter()) {
                            result.push(Statement::Assignment(Assignment {
                                target: new_name.clone(),
                                value: Expression::Identifier(Identifier {
                                    name: orig_name.clone(),
                                    line: None,
                                }),
                                type_annotation: None,
                                metadata: None,
                                line: f.line,
                            }));
                        }
                    }
                } else {
                    if !concrete.is_empty() {
                        seen.insert(key, concrete);
                    }
                    result.push(stmt.clone());
                }
            }
            Statement::Namespace(ns) => {
                result.push(Statement::Namespace(Namespace {
                    name: ns.name.clone(),
                    body: cse_body(&ns.body),
                    line: ns.line,
                }));
            }
            Statement::SubgraphDef(sg) => {
                result.push(Statement::SubgraphDef(SubgraphDef {
                    name: sg.name.clone(),
                    params: sg.params.clone(),
                    outputs: sg.outputs.clone(),
                    body: cse_body(&sg.body),
                    line: sg.line,
                }));
            }
            Statement::TryExcept(t) => {
                result.push(Statement::TryExcept(TryExcept {
                    try_body: cse_body(&t.try_body),
                    except_body: cse_body(&t.except_body),
                    metadata: t.metadata.clone(),
                    line: t.line,
                }));
            }
            other => result.push(other.clone()),
        }
    }

    result
}

// ---------------------------------------------------------------------------
// Utility: collect outputs / inputs of a statement
// ---------------------------------------------------------------------------

fn stmt_outputs(stmt: &Statement) -> HashSet<String> {
    let mut out = HashSet::new();
    match stmt {
        Statement::Assignment(a) => {
            out.insert(a.target.clone());
        }
        Statement::FuncCall(f) => {
            for o in &f.outputs {
                if let OutputTarget::Name(n) = o {
                    out.insert(n.clone());
                }
            }
        }
        _ => {}
    }
    out
}

fn stmt_inputs(stmt: &Statement) -> HashSet<String> {
    let mut inp = HashSet::new();
    match stmt {
        Statement::Assignment(a) => {
            collect_id_names(&a.value, &mut inp);
        }
        Statement::FuncCall(f) => {
            for i in &f.inputs {
                collect_id_names(i, &mut inp);
            }
        }
        Statement::Branch(b) => {
            collect_id_names(&b.condition, &mut inp);
        }
        Statement::Switch(s) => {
            collect_id_names(&s.value, &mut inp);
        }
        _ => {}
    }
    inp
}

fn collect_id_names(expr: &Expression, names: &mut HashSet<String>) {
    match expr {
        Expression::Identifier(id) => {
            names.insert(id.name.clone());
        }
        Expression::KeywordArg(kw) => {
            collect_id_names(&kw.value, names);
        }
        _ => {}
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ast::{
        Assignment, Branch, Expression, FuncCall, Identifier, Literal, OutputTarget, Value,
    };

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

    fn int_lit(n: i64) -> Expression {
        Expression::Literal(Literal {
            value: Value::Int(n),
            literal_type: "int".into(),
            line: None,
        })
    }

    fn bool_lit(b: bool) -> Expression {
        Expression::Literal(Literal {
            value: Value::Bool(b),
            literal_type: "bool".into(),
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

    fn branch_stmt(cond: Expression, true_lbl: &str, false_lbl: &str) -> Statement {
        Statement::Branch(Branch {
            condition: cond,
            true_label: true_lbl.into(),
            false_label: false_lbl.into(),
            metadata: None,
            line: Some(1),
        })
    }

    fn make_prog(body: Vec<Statement>) -> Program {
        Program {
            body,
            mode: None,
            typehints: None,
            line: None,
        }
    }

    // ------------------------------------------------------------------
    // BranchSimplifier
    // ------------------------------------------------------------------

    #[test]
    fn branch_true_becomes_jump_to_true_arm() {
        let prog = make_prog(vec![branch_stmt(bool_lit(true), "yes", "no")]);
        let result = branch_simplify(&prog);
        assert_eq!(result.body.len(), 1);
        match &result.body[0] {
            Statement::Jump(j) => assert_eq!(j.target, "yes"),
            other => panic!("expected Jump, got {other:?}"),
        }
    }

    #[test]
    fn branch_false_becomes_jump_to_false_arm() {
        let prog = make_prog(vec![branch_stmt(bool_lit(false), "yes", "no")]);
        let result = branch_simplify(&prog);
        match &result.body[0] {
            Statement::Jump(j) => assert_eq!(j.target, "no"),
            other => panic!("expected Jump, got {other:?}"),
        }
    }

    #[test]
    fn branch_dynamic_cond_unchanged() {
        let prog = make_prog(vec![branch_stmt(id_expr("cond"), "yes", "no")]);
        let result = branch_simplify(&prog);
        assert!(matches!(result.body[0], Statement::Branch(_)));
    }

    // ------------------------------------------------------------------
    // DeadNamespaceEliminator
    // ------------------------------------------------------------------

    #[test]
    fn unreachable_namespace_removed() {
        let prog = make_prog(vec![
            Statement::Namespace(Namespace {
                name: "dead_ns".into(),
                body: vec![],
                line: None,
            }),
            Statement::Jump(crate::ast::Jump {
                target: "live_ns".into(),
                metadata: None,
                line: None,
            }),
            Statement::Namespace(Namespace {
                name: "live_ns".into(),
                body: vec![],
                line: None,
            }),
        ]);
        let result = dead_namespace_eliminate(&prog);
        let ns_names: Vec<&str> = result
            .body
            .iter()
            .filter_map(|s| match s {
                Statement::Namespace(ns) => Some(ns.name.as_str()),
                _ => None,
            })
            .collect();
        assert!(
            !ns_names.contains(&"dead_ns"),
            "dead_ns should be removed"
        );
        assert!(
            ns_names.contains(&"live_ns"),
            "live_ns should be kept"
        );
    }

    // ------------------------------------------------------------------
    // ParallelPathDetector
    // ------------------------------------------------------------------

    #[test]
    fn independent_paths_detected() {
        // x = 1   — no deps
        // y = 2   — no deps, independent of x
        let prog = make_prog(vec![assign("x", int_lit(1)), assign("y", int_lit(2))]);
        let result = parallel_detect(&prog);
        // Should contain a Parallel node
        let has_parallel = result
            .body
            .iter()
            .any(|s| matches!(s, Statement::Parallel(_)));
        assert!(has_parallel, "independent statements should produce a Parallel node");
    }

    #[test]
    fn dependent_path_not_split() {
        // x = 1, y = x  — y depends on x
        let prog = make_prog(vec![assign("x", int_lit(1)), assign("y", id_expr("x"))]);
        let result = parallel_detect(&prog);
        let has_parallel = result
            .body
            .iter()
            .any(|s| matches!(s, Statement::Parallel(_)));
        assert!(
            !has_parallel,
            "dependent statements should NOT produce a Parallel node"
        );
    }

    // ------------------------------------------------------------------
    // CSE
    // ------------------------------------------------------------------

    #[test]
    fn duplicate_call_replaced_by_assignment() {
        // (1, 2)add -> r1
        // (1, 2)add -> r2   — same as r1, should become r2 = r1
        let call1 = func_call(vec![int_lit(1), int_lit(2)], "add", vec!["r1"]);
        let call2 = func_call(vec![int_lit(1), int_lit(2)], "add", vec!["r2"]);
        let prog = make_prog(vec![call1, call2]);
        let result = cse(&prog);
        assert_eq!(result.body.len(), 2);
        // Second stmt should now be an assignment r2 = r1
        match &result.body[1] {
            Statement::Assignment(a) => {
                assert_eq!(a.target, "r2");
                match &a.value {
                    Expression::Identifier(id) => assert_eq!(id.name, "r1"),
                    other => panic!("expected Identifier, got {other:?}"),
                }
            }
            other => panic!("expected Assignment, got {other:?}"),
        }
    }

    #[test]
    fn different_calls_not_deduplicated() {
        let call1 = func_call(vec![int_lit(1)], "f", vec!["a"]);
        let call2 = func_call(vec![int_lit(2)], "f", vec!["b"]);
        let prog = make_prog(vec![call1, call2]);
        let result = cse(&prog);
        assert!(
            result
                .body
                .iter()
                .all(|s| matches!(s, Statement::FuncCall(_))),
            "different calls should both be kept as FuncCall"
        );
    }

    // ------------------------------------------------------------------
    // optimize() — full pipeline
    // ------------------------------------------------------------------

    #[test]
    fn optimize_all_passes_run() {
        let prog = make_prog(vec![assign("x", int_lit(1))]);
        let result = optimize(&prog, None).unwrap();
        // x is dead (never used) — dead_code pass should remove it
        assert!(
            result.body.is_empty(),
            "dead assignment should be eliminated by full optimizer"
        );
    }

    #[test]
    fn optimize_unknown_pass_errors() {
        let prog = make_prog(vec![]);
        let result = optimize(&prog, Some(&["unknown_pass"]));
        assert!(result.is_err());
    }

    #[test]
    fn optimize_subset_of_passes() {
        // Only run branch_simplify — dead assignment x should remain
        let prog = make_prog(vec![
            assign("x", int_lit(1)),
            branch_stmt(bool_lit(true), "yes", "no"),
        ]);
        let result = optimize(&prog, Some(&["branch_simplify"])).unwrap();
        // Branch should be simplified to Jump
        assert!(result.body.iter().any(|s| matches!(s, Statement::Jump(_))));
        // x should still be there (dead_code not run)
        assert!(
            result
                .body
                .iter()
                .any(|s| matches!(s, Statement::Assignment(a) if a.target == "x"))
        );
    }
}
