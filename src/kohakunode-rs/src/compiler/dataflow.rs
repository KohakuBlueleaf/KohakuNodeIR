//! Dataflow-to-sequential compiler pass.
//!
//! Port of `kohakunode/compiler/dataflow.py` and
//! `kohakunode/compiler/passes.py` (DependencyGraphBuilder + topological_sort).
//!
//! Handles two forms:
//! 1. Whole-file dataflow (`mode = Some("dataflow")`): topologically sort all
//!    statements and clear the mode flag.
//! 2. Scoped `@dataflow:` blocks (`Statement::DataflowBlock`): sort the block
//!    body and inline the sorted statements into the parent scope.

use std::collections::{HashMap, HashSet, VecDeque};

use crate::ast::{Expression, Namespace, OutputTarget, Program, Statement, SubgraphDef};

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Compile dataflow ordering: topologically sort dataflow statements and
/// inline `DataflowBlock` nodes into their parent scope.
///
/// Returns a new `Program` with the same `mode` (cleared to `None` for
/// whole-file dataflow) and a reordered body.
///
/// # Errors
///
/// Returns an error string if:
/// - A control-flow statement appears inside a whole-file dataflow program.
/// - A dependency cycle is detected.
pub fn compile_dataflow(program: &Program) -> Result<Program, String> {
    // Whole-file dataflow mode.
    if program.mode.as_deref() == Some("dataflow") {
        for stmt in &program.body {
            if is_control_flow(stmt) {
                return Err(format!(
                    "Control-flow construct '{}' is not allowed in dataflow mode \
                     and cannot be compiled to sequential IR. Remove or lower all \
                     control-flow nodes before running the dataflow compiler.",
                    stmt_kind_name(stmt)
                ));
            }
        }
        let sorted = topological_sort(&program.body)?;
        return Ok(Program {
            body: sorted,
            mode: None,
            line: program.line,
        });
    }

    // Scoped @dataflow: blocks.
    let (new_body, changed) = expand_dataflow_blocks(&program.body)?;
    if !changed {
        return Ok(program.clone());
    }
    Ok(Program {
        body: new_body,
        mode: program.mode.clone(),
        line: program.line,
    })
}

// ---------------------------------------------------------------------------
// Control-flow predicate
// ---------------------------------------------------------------------------

fn is_control_flow(stmt: &Statement) -> bool {
    matches!(
        stmt,
        Statement::Branch(_)
            | Statement::Jump(_)
            | Statement::Namespace(_)
            | Statement::Parallel(_)
            | Statement::Switch(_)
    )
}

fn stmt_kind_name(stmt: &Statement) -> &'static str {
    match stmt {
        Statement::Assignment(_) => "Assignment",
        Statement::FuncCall(_) => "FuncCall",
        Statement::Namespace(_) => "Namespace",
        Statement::SubgraphDef(_) => "SubgraphDef",
        Statement::DataflowBlock(_) => "DataflowBlock",
        Statement::ModeDecl(_) => "ModeDecl",
        Statement::Branch(_) => "Branch",
        Statement::Switch(_) => "Switch",
        Statement::Jump(_) => "Jump",
        Statement::Parallel(_) => "Parallel",
    }
}

// ---------------------------------------------------------------------------
// expand_dataflow_blocks — recursively replace DataflowBlock with sorted body
// ---------------------------------------------------------------------------

/// Returns `(new_body, changed)`. `changed` is false when no DataflowBlock
/// was found anywhere in the tree (mirrors the Python sentinel trick).
fn expand_dataflow_blocks(stmts: &[Statement]) -> Result<(Vec<Statement>, bool), String> {
    let mut found = false;
    let mut new_body: Vec<Statement> = Vec::with_capacity(stmts.len());

    for stmt in stmts {
        match stmt {
            Statement::DataflowBlock(block) => {
                found = true;
                let sorted = topological_sort(&block.body)?;
                new_body.extend(sorted);
            }
            Statement::Namespace(ns) => {
                let (inner, changed) = expand_dataflow_blocks(&ns.body)?;
                if changed {
                    found = true;
                    new_body.push(Statement::Namespace(Namespace {
                        name: ns.name.clone(),
                        body: inner,
                        line: ns.line,
                    }));
                } else {
                    new_body.push(stmt.clone());
                }
            }
            Statement::SubgraphDef(sg) => {
                let (inner, changed) = expand_dataflow_blocks(&sg.body)?;
                if changed {
                    found = true;
                    new_body.push(Statement::SubgraphDef(SubgraphDef {
                        name: sg.name.clone(),
                        params: sg.params.clone(),
                        outputs: sg.outputs.clone(),
                        body: inner,
                        line: sg.line,
                    }));
                } else {
                    new_body.push(stmt.clone());
                }
            }
            other => new_body.push(other.clone()),
        }
    }

    Ok((new_body, found))
}

// ---------------------------------------------------------------------------
// Dependency graph builder
// ---------------------------------------------------------------------------

/// Build `output_var → {input_vars}` adjacency map from a flat statement list.
fn build_dependency_graph(stmts: &[Statement]) -> HashMap<String, HashSet<String>> {
    let mut graph: HashMap<String, HashSet<String>> = HashMap::new();

    for stmt in stmts {
        match stmt {
            Statement::Assignment(a) => {
                let deps = collect_identifier_names(&a.value);
                graph.insert(a.target.clone(), deps);
            }
            Statement::FuncCall(f) => {
                let input_names: HashSet<String> =
                    f.inputs.iter().flat_map(collect_identifier_names).collect();

                let output_names: HashSet<String> = f
                    .outputs
                    .iter()
                    .filter_map(|o| match o {
                        OutputTarget::Name(n) => Some(n.clone()),
                        OutputTarget::Wildcard => None,
                    })
                    .collect();

                for out in &f.outputs {
                    if let OutputTarget::Name(name) = out {
                        // Exclude self-references (update pattern).
                        let deps: HashSet<String> =
                            input_names.difference(&output_names).cloned().collect();
                        graph.insert(name.clone(), deps);
                    }
                }
            }
            // Namespaces should not appear in dataflow mode; skip silently.
            _ => {}
        }
    }

    graph
}

/// Collect all `Identifier` names referenced in an expression (non-recursive
/// beyond KeywordArg, matching the Python implementation).
fn collect_identifier_names(expr: &Expression) -> HashSet<String> {
    let mut names = HashSet::new();
    match expr {
        Expression::Identifier(id) => {
            names.insert(id.name.clone());
        }
        Expression::KeywordArg(kw) => {
            names.extend(collect_identifier_names(&kw.value));
        }
        _ => {}
    }
    names
}

// ---------------------------------------------------------------------------
// Kahn's topological sort
// ---------------------------------------------------------------------------

fn topological_sort(stmts: &[Statement]) -> Result<Vec<Statement>, String> {
    let graph = build_dependency_graph(stmts);

    // Map each output variable name → index in `stmts` for O(1) lookup.
    // When a FuncCall has multiple outputs they all point to the same index.
    let mut var_to_idx: HashMap<String, usize> = HashMap::new();
    for (i, stmt) in stmts.iter().enumerate() {
        match stmt {
            Statement::Assignment(a) => {
                var_to_idx.insert(a.target.clone(), i);
            }
            Statement::FuncCall(f) => {
                for out in &f.outputs {
                    if let OutputTarget::Name(name) = out {
                        var_to_idx.insert(name.clone(), i);
                    }
                }
            }
            _ => {}
        }
    }

    let all_outputs: HashSet<&String> = graph.keys().collect();

    // Compute in-degrees and dependents list.
    let mut in_degree: HashMap<&String, usize> = graph.keys().map(|v| (v, 0usize)).collect();
    let mut dependents: HashMap<&String, Vec<&String>> =
        graph.keys().map(|v| (v, Vec::new())).collect();

    for (var, deps) in &graph {
        for dep in deps {
            if all_outputs.contains(dep) {
                *in_degree.get_mut(var).unwrap() += 1;
                dependents.get_mut(dep).unwrap().push(var);
            }
        }
    }

    // Kahn's algorithm — start from zero-in-degree nodes.
    let mut queue: VecDeque<&String> = in_degree
        .iter()
        .filter(|(_, &deg)| deg == 0)
        .map(|(v, _)| *v)
        .collect();

    let mut seen_idxs: HashSet<usize> = HashSet::new();
    let mut sorted_stmts: Vec<Statement> = Vec::new();
    let mut processed_count = 0usize;

    while let Some(var) = queue.pop_front() {
        processed_count += 1;

        if let Some(&idx) = var_to_idx.get(var) {
            if seen_idxs.insert(idx) {
                sorted_stmts.push(stmts[idx].clone());
            }
        }

        for dep_var in &dependents[var] {
            let deg = in_degree.get_mut(*dep_var).unwrap();
            *deg -= 1;
            if *deg == 0 {
                queue.push_back(dep_var);
            }
        }
    }

    // Cycle detection.
    if processed_count != all_outputs.len() {
        let unresolved: Vec<String> = all_outputs
            .iter()
            .filter(|v| in_degree[*v] > 0)
            .map(|v| (*v).clone())
            .collect();
        let mut unresolved_sorted = unresolved;
        unresolved_sorted.sort();
        return Err(format!(
            "Cycle detected in dependency graph involving variable(s): {}",
            unresolved_sorted.join(", ")
        ));
    }

    // Append statements that produce no tracked outputs (e.g. all-wildcard
    // FuncCalls) preserving their original relative order.
    for (i, stmt) in stmts.iter().enumerate() {
        if !seen_idxs.contains(&i) {
            sorted_stmts.push(stmt.clone());
        }
    }

    Ok(sorted_stmts)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ast::{
        Assignment, DataflowBlock, Expression, FuncCall, Identifier, Literal, OutputTarget, Value,
    };

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

    fn assign(target: &str, value: Expression) -> Statement {
        Statement::Assignment(Assignment {
            target: target.into(),
            value,
            metadata: None,
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

    // Helper: extract output variable names from a sorted statement list in order.
    fn output_names(stmts: &[Statement]) -> Vec<String> {
        let mut names = Vec::new();
        for stmt in stmts {
            match stmt {
                Statement::Assignment(a) => names.push(a.target.clone()),
                Statement::FuncCall(f) => {
                    for out in &f.outputs {
                        if let OutputTarget::Name(n) = out {
                            names.push(n.clone());
                        }
                    }
                }
                _ => {}
            }
        }
        names
    }

    // ------------------------------------------------------------------
    // DataflowBlock inlining
    // ------------------------------------------------------------------

    /// z = x + y, but x and y are defined after z in source order.
    /// After compile_dataflow the block is inlined and x, y appear before z.
    #[test]
    fn dataflow_block_sorted_and_inlined() {
        // Source order: z depends on x and y; x and y are defined after z.
        // z = add(x, y)
        // x = 1
        // y = 2
        let block_body = vec![
            func_call(vec![id_expr("x"), id_expr("y")], "add", vec!["z"]),
            assign("x", int_lit(1)),
            assign("y", int_lit(2)),
        ];

        let prog = Program {
            body: vec![Statement::DataflowBlock(DataflowBlock {
                body: block_body,
                line: None,
            })],
            mode: None,
            line: None,
        };

        let result = compile_dataflow(&prog).unwrap();

        // DataflowBlock wrapper must be gone — statements inlined directly.
        assert!(
            result
                .body
                .iter()
                .all(|s| !matches!(s, Statement::DataflowBlock(_))),
            "DataflowBlock should be inlined"
        );

        let names = output_names(&result.body);
        // x and y must appear before z.
        let pos_x = names.iter().position(|n| n == "x").unwrap();
        let pos_y = names.iter().position(|n| n == "y").unwrap();
        let pos_z = names.iter().position(|n| n == "z").unwrap();
        assert!(pos_x < pos_z, "x must come before z");
        assert!(pos_y < pos_z, "y must come before z");
    }

    /// When there is no DataflowBlock (and mode != "dataflow"), the program
    /// is returned unchanged.
    #[test]
    fn no_dataflow_block_returns_unchanged() {
        let prog = Program {
            body: vec![assign("x", int_lit(1))],
            mode: None,
            line: None,
        };
        let result = compile_dataflow(&prog).unwrap();
        assert_eq!(result, prog);
    }

    // ------------------------------------------------------------------
    // Whole-file dataflow mode
    // ------------------------------------------------------------------

    #[test]
    fn whole_file_dataflow_sorted() {
        // z = add(x, y)  — defined first but depends on x and y
        // x = 1
        // y = 2
        let prog = Program {
            body: vec![
                func_call(vec![id_expr("x"), id_expr("y")], "add", vec!["z"]),
                assign("x", int_lit(1)),
                assign("y", int_lit(2)),
            ],
            mode: Some("dataflow".into()),
            line: None,
        };

        let result = compile_dataflow(&prog).unwrap();
        assert_eq!(result.mode, None, "mode should be cleared after compile");

        let names = output_names(&result.body);
        let pos_x = names.iter().position(|n| n == "x").unwrap();
        let pos_y = names.iter().position(|n| n == "y").unwrap();
        let pos_z = names.iter().position(|n| n == "z").unwrap();
        assert!(pos_x < pos_z);
        assert!(pos_y < pos_z);
    }

    #[test]
    fn whole_file_dataflow_rejects_control_flow() {
        use crate::ast::Jump;
        let prog = Program {
            body: vec![Statement::Jump(Jump {
                target: "somewhere".into(),
                metadata: None,
                line: None,
            })],
            mode: Some("dataflow".into()),
            line: None,
        };
        assert!(compile_dataflow(&prog).is_err());
    }

    // ------------------------------------------------------------------
    // Cycle detection
    // ------------------------------------------------------------------

    #[test]
    fn cycle_returns_error() {
        // x = f(y), y = f(x) — direct cycle
        let prog = Program {
            body: vec![Statement::DataflowBlock(DataflowBlock {
                body: vec![
                    func_call(vec![id_expr("y")], "f", vec!["x"]),
                    func_call(vec![id_expr("x")], "f", vec!["y"]),
                ],
                line: None,
            })],
            mode: None,
            line: None,
        };
        let result = compile_dataflow(&prog);
        assert!(result.is_err(), "should return error on cycle");
        assert!(result.unwrap_err().contains("Cycle"));
    }

    // ------------------------------------------------------------------
    // Linear chain
    // ------------------------------------------------------------------

    #[test]
    fn linear_chain_out_of_order() {
        // c = f(b), b = f(a), a = 1  — three-step chain in reverse order
        let prog = Program {
            body: vec![Statement::DataflowBlock(DataflowBlock {
                body: vec![
                    func_call(vec![id_expr("b")], "step", vec!["c"]),
                    func_call(vec![id_expr("a")], "step", vec!["b"]),
                    assign("a", int_lit(0)),
                ],
                line: None,
            })],
            mode: None,
            line: None,
        };

        let result = compile_dataflow(&prog).unwrap();
        let names = output_names(&result.body);
        let pa = names.iter().position(|n| n == "a").unwrap();
        let pb = names.iter().position(|n| n == "b").unwrap();
        let pc = names.iter().position(|n| n == "c").unwrap();
        assert!(pa < pb);
        assert!(pb < pc);
    }

    // ------------------------------------------------------------------
    // Wildcard outputs are appended after sorted outputs
    // ------------------------------------------------------------------

    #[test]
    fn wildcard_outputs_appended_last() {
        use crate::ast::FuncCall as FC;

        let wildcard_stmt = Statement::FuncCall(FC {
            inputs: vec![],
            func_name: "side_effect".into(),
            outputs: vec![OutputTarget::Wildcard],
            metadata: None,
            line: None,
        });

        let prog = Program {
            body: vec![Statement::DataflowBlock(DataflowBlock {
                body: vec![wildcard_stmt.clone(), assign("x", int_lit(1))],
                line: None,
            })],
            mode: None,
            line: None,
        };

        let result = compile_dataflow(&prog).unwrap();
        // The wildcard statement should come after the tracked assignment.
        let wc_pos = result
            .body
            .iter()
            .position(|s| matches!(s, Statement::FuncCall(f) if f.func_name == "side_effect"))
            .unwrap();
        let x_pos = result
            .body
            .iter()
            .position(|s| matches!(s, Statement::Assignment(a) if a.target == "x"))
            .unwrap();
        assert!(
            x_pos < wc_pos,
            "tracked assignment should precede wildcard call"
        );
    }

    // ------------------------------------------------------------------
    // SubgraphDef body is processed
    // ------------------------------------------------------------------

    #[test]
    fn subgraph_def_dataflow_block_expanded() {
        use crate::ast::SubgraphDef;

        let inner_block = Statement::DataflowBlock(DataflowBlock {
            body: vec![
                func_call(vec![id_expr("x")], "f", vec!["y"]),
                assign("x", int_lit(5)),
            ],
            line: None,
        });

        let prog = Program {
            body: vec![Statement::SubgraphDef(SubgraphDef {
                name: "my_graph".into(),
                params: vec![],
                outputs: vec!["y".into()],
                body: vec![inner_block],
                line: None,
            })],
            mode: None,
            line: None,
        };

        let result = compile_dataflow(&prog).unwrap();
        match &result.body[0] {
            Statement::SubgraphDef(sg) => {
                assert!(
                    sg.body
                        .iter()
                        .all(|s| !matches!(s, Statement::DataflowBlock(_))),
                    "DataflowBlock inside SubgraphDef should be inlined"
                );
                let names = output_names(&sg.body);
                let px = names.iter().position(|n| n == "x").unwrap();
                let py = names.iter().position(|n| n == "y").unwrap();
                assert!(px < py, "x must precede y inside SubgraphDef");
            }
            other => panic!("expected SubgraphDef, got {other:?}"),
        }
    }
}
