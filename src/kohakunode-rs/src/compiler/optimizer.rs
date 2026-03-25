//! L4 compiler optimizer: ParallelPathDetector, BranchSimplifier,
//! DeadNamespaceEliminator, CommonSubexprEliminator.
//!
//! Mirror of `kohakunode/compiler/optimizer.py`.

use std::collections::{HashMap, HashSet};

use crate::ast::{
    Assignment, Expression, FuncCall, Identifier, Jump, Namespace, OutputTarget, Parallel,
    Program, Statement, SubgraphDef, TryExcept, Value,
};

use crate::compiler::dead_code::dead_code;

// ---------------------------------------------------------------------------
// Known sub-pass names
// Pass ordering: branch_simplify → dead_code → cse → parallel_detect (LAST)
// ---------------------------------------------------------------------------

pub const ALL_PASSES: &[&str] = &["branch_simplify", "dead_code", "cse", "parallel_detect"];

// ---------------------------------------------------------------------------
// Optimizer entry point
// ---------------------------------------------------------------------------

/// Apply a sequence of L4 optimization sub-passes to *program*.
///
/// # Parameters
/// - `passes`: ordered list of sub-pass names to run. `None` means all four in
///   the canonical order: branch_simplify → dead_code → cse → parallel_detect.
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

/// Group statements into logical blocks.
///
/// A Branch/Switch/Parallel and its immediately following sibling Namespaces
/// (whose names match that node's owned labels) form ONE block.
/// A Jump and its immediately following sibling Namespace (whose name matches
/// the jump target) form ONE block.
/// Everything else is its own single-statement block.
fn group_into_blocks(stmts: &[Statement]) -> Vec<Vec<Statement>> {
    let mut blocks: Vec<Vec<Statement>> = Vec::new();
    let mut i = 0;
    while i < stmts.len() {
        let stmt = &stmts[i];
        match stmt {
            Statement::Branch(b) => {
                let owned: HashSet<String> =
                    [b.true_label.clone(), b.false_label.clone()].into_iter().collect();
                let mut block = vec![stmt.clone()];
                let mut j = i + 1;
                while j < stmts.len() {
                    if let Statement::Namespace(ns) = &stmts[j] {
                        if owned.contains(&ns.name) {
                            block.push(stmts[j].clone());
                            j += 1;
                            continue;
                        }
                    }
                    break;
                }
                blocks.push(block);
                i = j;
            }
            Statement::Switch(s) => {
                let mut owned: HashSet<String> =
                    s.cases.iter().map(|(_, lbl)| lbl.clone()).collect();
                if let Some(ref dl) = s.default_label {
                    owned.insert(dl.clone());
                }
                let mut block = vec![stmt.clone()];
                let mut j = i + 1;
                while j < stmts.len() {
                    if let Statement::Namespace(ns) = &stmts[j] {
                        if owned.contains(&ns.name) {
                            block.push(stmts[j].clone());
                            j += 1;
                            continue;
                        }
                    }
                    break;
                }
                blocks.push(block);
                i = j;
            }
            Statement::Parallel(p) => {
                let owned: HashSet<String> = p.labels.iter().cloned().collect();
                let mut block = vec![stmt.clone()];
                let mut j = i + 1;
                while j < stmts.len() {
                    if let Statement::Namespace(ns) = &stmts[j] {
                        if owned.contains(&ns.name) {
                            block.push(stmts[j].clone());
                            j += 1;
                            continue;
                        }
                    }
                    break;
                }
                blocks.push(block);
                i = j;
            }
            Statement::Jump(jmp) => {
                // Jump + its target Namespace form ONE block
                let mut block = vec![stmt.clone()];
                let mut j = i + 1;
                while j < stmts.len() {
                    if let Statement::Namespace(ns) = &stmts[j] {
                        if ns.name == jmp.target {
                            block.push(stmts[j].clone());
                            j += 1;
                            continue;
                        }
                    }
                    break;
                }
                blocks.push(block);
                i = j;
            }
            _ => {
                blocks.push(vec![stmt.clone()]);
                i += 1;
            }
        }
    }
    blocks
}

/// All variable names *produced* by any statement in a block (including
/// inner namespace bodies).
fn block_outputs(block: &[Statement]) -> HashSet<String> {
    let mut result = HashSet::new();
    for s in block {
        result.extend(stmt_outputs(s));
        if let Statement::Namespace(ns) = s {
            for inner in &ns.body {
                result.extend(stmt_outputs(inner));
            }
        }
    }
    result
}

/// All variable names *consumed* by any statement in a block (including
/// inner namespace bodies).
fn block_inputs(block: &[Statement]) -> HashSet<String> {
    let mut result = HashSet::new();
    for s in block {
        result.extend(stmt_inputs(s));
        if let Statement::Namespace(ns) = s {
            for inner in &ns.body {
                result.extend(stmt_inputs(inner));
            }
        }
    }
    result
}

/// Detect independent statement groups and wrap them in Namespace + Parallel.
///
/// Groups consecutive statements into logical blocks first (a Branch/Switch and
/// its sibling Namespaces form ONE block; a Jump and its target Namespace form
/// ONE block). Only top-level blocks are considered. The pass does NOT recurse
/// into nested scopes.
pub fn parallel_detect(program: &Program) -> Program {
    let blocks = group_into_blocks(&program.body);
    if blocks.len() < 2 {
        return program.clone();
    }

    let outputs_per: Vec<HashSet<String>> = blocks.iter().map(|b| block_outputs(b)).collect();
    let inputs_per: Vec<HashSet<String>> = blocks.iter().map(|b| block_inputs(b)).collect();

    // Union-Find
    let mut parent: Vec<usize> = (0..blocks.len()).collect();

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

    for i in 0..blocks.len() {
        for j in (i + 1)..blocks.len() {
            if !outputs_per[i].is_disjoint(&inputs_per[j])
                || !outputs_per[j].is_disjoint(&inputs_per[i])
            {
                union(&mut parent, i, j);
            }
        }
    }

    // Group by root
    let mut groups: HashMap<usize, Vec<usize>> = HashMap::new();
    for i in 0..blocks.len() {
        let root = find(&mut parent, i);
        groups.entry(root).or_default().push(i);
    }

    // Need at least 2 independent groups to parallelise
    let independent_groups: Vec<Vec<usize>> = groups.into_values().collect();
    if independent_groups.len() < 2 {
        return program.clone();
    }

    // Check: at least 2 groups with non-empty blocks
    let multi_groups: Vec<&Vec<usize>> = independent_groups
        .iter()
        .filter(|idxs| idxs.iter().any(|&i| !blocks[i].is_empty()))
        .collect();
    if multi_groups.len() < 2 {
        return program.clone();
    }

    // Build namespace wrappers + parallel node
    let mut new_body: Vec<Statement> = Vec::new();
    let mut labels: Vec<String> = Vec::new();

    // Sort groups by their smallest block index so output order is deterministic
    let mut sorted_groups = independent_groups;
    sorted_groups.sort_by_key(|g| *g.iter().min().unwrap_or(&0));

    for (g_idx, idxs) in sorted_groups.iter().enumerate() {
        let mut sorted_idxs = idxs.clone();
        sorted_idxs.sort_unstable();
        // Flatten block statements back
        let mut body: Vec<Statement> = Vec::new();
        for i in sorted_idxs {
            body.extend(blocks[i].iter().cloned());
        }
        if body.is_empty() {
            continue;
        }
        let label = format!("__par_{g_idx}");
        labels.push(label.clone());
        new_body.push(Statement::Namespace(Namespace {
            name: label,
            body,
            line: None,
        }));
    }

    if labels.len() < 2 {
        return program.clone();
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

/// Count how many times each label is referenced across all statements.
fn collect_all_label_refs(stmts: &[Statement]) -> HashMap<String, usize> {
    let mut counts: HashMap<String, usize> = HashMap::new();

    fn walk(body: &[Statement], counts: &mut HashMap<String, usize>) {
        for stmt in body {
            match stmt {
                Statement::Jump(j) => {
                    *counts.entry(j.target.clone()).or_insert(0) += 1;
                }
                Statement::Branch(b) => {
                    *counts.entry(b.true_label.clone()).or_insert(0) += 1;
                    *counts.entry(b.false_label.clone()).or_insert(0) += 1;
                }
                Statement::Switch(s) => {
                    for (_, lbl) in &s.cases {
                        *counts.entry(lbl.clone()).or_insert(0) += 1;
                    }
                    if let Some(ref dl) = s.default_label {
                        *counts.entry(dl.clone()).or_insert(0) += 1;
                    }
                }
                Statement::Parallel(p) => {
                    for lbl in &p.labels {
                        *counts.entry(lbl.clone()).or_insert(0) += 1;
                    }
                }
                Statement::Namespace(ns) => walk(&ns.body, counts),
                Statement::TryExcept(t) => {
                    walk(&t.try_body, counts);
                    walk(&t.except_body, counts);
                }
                Statement::SubgraphDef(sg) => walk(&sg.body, counts),
                _ => {}
            }
        }
    }

    walk(stmts, &mut counts);
    counts
}

/// Inline trivial jump→namespace pairs.
///
/// `()jump(label)` immediately followed by `label: body`, AND no other
/// statement references that label → replace both with the inlined body.
fn inline_trivial_jumps(stmts: Vec<Statement>) -> Vec<Statement> {
    let ref_counts = collect_all_label_refs(&stmts);

    let mut result: Vec<Statement> = Vec::new();
    let mut i = 0;
    while i < stmts.len() {
        let stmt = &stmts[i];
        if let Statement::Jump(jmp) = stmt {
            if i + 1 < stmts.len() {
                if let Statement::Namespace(ns) = &stmts[i + 1] {
                    if ns.name == jmp.target
                        && ref_counts.get(&jmp.target).copied().unwrap_or(0) == 1
                    {
                        // Safe to inline: replace jump + namespace with just the body
                        result.extend(ns.body.iter().cloned());
                        i += 2;
                        continue;
                    }
                }
            }
        }
        result.push(stmts[i].clone());
        i += 1;
    }
    result
}

/// Try to resolve a condition to a `bool`. Returns `None` if not resolvable.
fn resolve_bool_condition(cond: &Expression, constants: &HashMap<String, Value>) -> Option<bool> {
    match cond {
        Expression::Literal(lit) if lit.literal_type == "bool" => {
            if let Value::Bool(b) = lit.value {
                return Some(b);
            }
            None
        }
        Expression::Identifier(id) => {
            if let Some(Value::Bool(b)) = constants.get(&id.name) {
                return Some(*b);
            }
            None
        }
        _ => None,
    }
}

fn simplify_body(stmts: &[Statement], constants: &mut HashMap<String, Value>) -> Vec<Statement> {
    // First pass: collect constant assignments (name = Literal)
    for stmt in stmts {
        if let Statement::Assignment(a) = stmt {
            if let Expression::Literal(lit) = &a.value {
                constants.insert(a.target.clone(), lit.value.clone());
            }
        }
    }
    // Second pass: simplify
    stmts.iter().map(|s| simplify_stmt(s, constants)).collect()
}

fn simplify_stmt(stmt: &Statement, constants: &HashMap<String, Value>) -> Statement {
    match stmt {
        Statement::Branch(b) => {
            if let Some(resolved) = resolve_bool_condition(&b.condition, constants) {
                if resolved {
                    return Statement::Jump(Jump {
                        target: b.true_label.clone(),
                        metadata: None,
                        line: b.line,
                    });
                } else {
                    return Statement::Jump(Jump {
                        target: b.false_label.clone(),
                        metadata: None,
                        line: b.line,
                    });
                }
            }
            stmt.clone()
        }
        Statement::Namespace(ns) => {
            let mut inner_constants = constants.clone();
            Statement::Namespace(Namespace {
                name: ns.name.clone(),
                body: simplify_body(&ns.body, &mut inner_constants),
                line: ns.line,
            })
        }
        Statement::SubgraphDef(sg) => {
            let mut inner_constants = constants.clone();
            Statement::SubgraphDef(SubgraphDef {
                name: sg.name.clone(),
                params: sg.params.clone(),
                outputs: sg.outputs.clone(),
                body: simplify_body(&sg.body, &mut inner_constants),
                line: sg.line,
            })
        }
        Statement::TryExcept(t) => Statement::TryExcept(TryExcept {
            try_body: simplify_body(&t.try_body, &mut HashMap::new()),
            except_body: simplify_body(&t.except_body, &mut HashMap::new()),
            metadata: t.metadata.clone(),
            line: t.line,
        }),
        other => other.clone(),
    }
}

/// Replace Branch nodes whose condition is a literal or constant bool with
/// unconditional Jump nodes, then inline trivial jump→namespace pairs.
pub fn branch_simplify(program: &Program) -> Program {
    let mut constants: HashMap<String, Value> = HashMap::new();
    let simplified = simplify_body(&program.body, &mut constants);
    // Inline trivial jump→namespace pairs
    let new_body = inline_trivial_jumps(simplified);
    Program {
        body: new_body,
        mode: program.mode.clone(),
        typehints: program.typehints.clone(),
        line: program.line,
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
        Assignment, Branch, Expression, FuncCall, Identifier, Literal, OutputTarget, Switch, Value,
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

    // ------------------------------------------------------------------
    // BranchSimplifier — constant propagation
    // ------------------------------------------------------------------

    #[test]
    fn constant_propagation_resolves_branch() {
        // x = True
        // (x)branch(yes, no)  →  should become jump(yes)
        let prog = make_prog(vec![
            assign("x", bool_lit(true)),
            branch_stmt(id_expr("x"), "yes", "no"),
        ]);
        let result = branch_simplify(&prog);
        // The branch should have been replaced by a Jump to "yes"
        let jump_targets: Vec<&str> = result
            .body
            .iter()
            .filter_map(|s| match s {
                Statement::Jump(j) => Some(j.target.as_str()),
                _ => None,
            })
            .collect();
        assert!(
            jump_targets.contains(&"yes"),
            "constant propagation should resolve (x)branch(yes, no) to jump(yes); got {:?}",
            result.body
        );
        // No Branch node should remain
        assert!(
            !result.body.iter().any(|s| matches!(s, Statement::Branch(_))),
            "Branch should have been eliminated by constant propagation"
        );
    }

    #[test]
    fn constant_propagation_false_resolves_to_false_arm() {
        // x = False
        // (x)branch(yes, no)  →  jump(no)
        let prog = make_prog(vec![
            assign("x", bool_lit(false)),
            branch_stmt(id_expr("x"), "yes", "no"),
        ]);
        let result = branch_simplify(&prog);
        let jump_targets: Vec<&str> = result
            .body
            .iter()
            .filter_map(|s| match s {
                Statement::Jump(j) => Some(j.target.as_str()),
                _ => None,
            })
            .collect();
        assert!(
            jump_targets.contains(&"no"),
            "constant propagation should resolve to jump(no); got {:?}",
            result.body
        );
    }

    #[test]
    fn non_bool_constant_does_not_resolve_branch() {
        // x = 42  (int, not bool)
        // (x)branch(yes, no)  →  branch unchanged
        let prog = make_prog(vec![
            assign("x", int_lit(42)),
            branch_stmt(id_expr("x"), "yes", "no"),
        ]);
        let result = branch_simplify(&prog);
        assert!(
            result.body.iter().any(|s| matches!(s, Statement::Branch(_))),
            "int constant should NOT resolve a Branch"
        );
    }

    // ------------------------------------------------------------------
    // BranchSimplifier — trivial jump inlining
    // ------------------------------------------------------------------

    #[test]
    fn trivial_jump_inlined() {
        // ()jump(body_ns)
        // body_ns:
        //   x = 1
        // → x = 1  (jump + namespace replaced by body)
        let prog = make_prog(vec![
            Statement::Jump(Jump {
                target: "body_ns".into(),
                metadata: None,
                line: None,
            }),
            Statement::Namespace(Namespace {
                name: "body_ns".into(),
                body: vec![assign("x", int_lit(1))],
                line: None,
            }),
        ]);
        let result = branch_simplify(&prog);
        // Should have inlined the namespace body (x = 1) directly
        assert_eq!(
            result.body.len(),
            1,
            "jump + namespace should be inlined to 1 statement; got {:?}",
            result.body
        );
        assert!(
            matches!(&result.body[0], Statement::Assignment(a) if a.target == "x"),
            "inlined body should be x = 1"
        );
    }

    #[test]
    fn jump_not_inlined_when_label_referenced_twice() {
        // ()jump(ns)
        // ns: body
        // ()jump(ns)    ← second reference — should NOT inline
        let prog = make_prog(vec![
            Statement::Jump(Jump {
                target: "ns".into(),
                metadata: None,
                line: None,
            }),
            Statement::Namespace(Namespace {
                name: "ns".into(),
                body: vec![assign("x", int_lit(1))],
                line: None,
            }),
            Statement::Jump(Jump {
                target: "ns".into(),
                metadata: None,
                line: None,
            }),
        ]);
        let result = branch_simplify(&prog);
        // "ns" is referenced twice so the jump→namespace pair must NOT be inlined
        assert!(
            result.body.iter().any(|s| matches!(s, Statement::Namespace(ns) if ns.name == "ns")),
            "namespace with 2+ refs should NOT be inlined"
        );
    }

    // ------------------------------------------------------------------
    // ParallelPathDetector — block grouping
    // ------------------------------------------------------------------

    #[test]
    fn branch_and_sibling_namespaces_form_one_block() {
        // branch(cond, yes, no)
        // yes: ...
        // no:  ...
        // These three should form ONE block (not split into parallel paths).
        let prog = make_prog(vec![
            branch_stmt(id_expr("cond"), "yes", "no"),
            Statement::Namespace(Namespace {
                name: "yes".into(),
                body: vec![assign("a", int_lit(1))],
                line: None,
            }),
            Statement::Namespace(Namespace {
                name: "no".into(),
                body: vec![assign("b", int_lit(2))],
                line: None,
            }),
        ]);
        let result = parallel_detect(&prog);
        // The branch + both namespaces are ONE block so there's only one block total
        // → no Parallel node should be emitted
        assert!(
            !result.body.iter().any(|s| matches!(s, Statement::Parallel(_))),
            "branch + sibling namespaces should be one block, no Parallel emitted"
        );
    }

    #[test]
    fn branch_block_and_independent_assign_are_parallelised() {
        // branch(cond, yes, no)
        // yes: { a = 1 }
        // no:  { b = 2 }
        // x = 99   ← independent of the branch
        let prog = make_prog(vec![
            branch_stmt(id_expr("cond"), "yes", "no"),
            Statement::Namespace(Namespace {
                name: "yes".into(),
                body: vec![assign("a", int_lit(1))],
                line: None,
            }),
            Statement::Namespace(Namespace {
                name: "no".into(),
                body: vec![assign("b", int_lit(2))],
                line: None,
            }),
            assign("x", int_lit(99)),
        ]);
        let result = parallel_detect(&prog);
        // Two blocks: [branch, yes, no] and [x = 99] → should be parallelised
        assert!(
            result.body.iter().any(|s| matches!(s, Statement::Parallel(_))),
            "branch block + independent assign should produce a Parallel node"
        );
    }

    #[test]
    fn jump_and_sibling_namespace_form_one_block() {
        // jump(body)
        // body: { x = 1 }
        // y = 2   ← independent
        let prog = make_prog(vec![
            Statement::Jump(Jump {
                target: "body".into(),
                metadata: None,
                line: None,
            }),
            Statement::Namespace(Namespace {
                name: "body".into(),
                body: vec![assign("x", int_lit(1))],
                line: None,
            }),
            assign("y", int_lit(2)),
        ]);
        // Before parallel_detect we need the jump to NOT be inlined (it has 1 ref)
        // We test parallel_detect directly (not branch_simplify) to avoid inlining.
        // Actually: the jump has ref-count 1 only for inline_trivial_jumps.
        // parallel_detect does its own grouping independent of inlining.
        let result = parallel_detect(&prog);
        // [jump, body_ns] form one block; [y=2] is another → two independent groups
        assert!(
            result.body.iter().any(|s| matches!(s, Statement::Parallel(_))),
            "jump + sibling namespace form one block; y=2 is independent → Parallel expected"
        );
    }

    #[test]
    fn switch_and_sibling_namespaces_form_one_block() {
        // switch(val): case 1 → arm1; default → arm2
        // arm1: { a = 1 }
        // arm2: { b = 2 }
        // x = 99  ← independent
        let case_lit = Expression::Literal(Literal {
            value: Value::Int(1),
            literal_type: "int".into(),
            line: None,
        });
        let prog = make_prog(vec![
            Statement::Switch(Switch {
                value: id_expr("val"),
                cases: vec![(case_lit, "arm1".into())],
                default_label: Some("arm2".into()),
                metadata: None,
                line: None,
            }),
            Statement::Namespace(Namespace {
                name: "arm1".into(),
                body: vec![assign("a", int_lit(1))],
                line: None,
            }),
            Statement::Namespace(Namespace {
                name: "arm2".into(),
                body: vec![assign("b", int_lit(2))],
                line: None,
            }),
            assign("x", int_lit(99)),
        ]);
        let result = parallel_detect(&prog);
        // [switch, arm1, arm2] is one block; [x=99] is another → Parallel
        assert!(
            result.body.iter().any(|s| matches!(s, Statement::Parallel(_))),
            "switch block + independent assign should produce a Parallel node"
        );
    }

    #[test]
    fn parallel_namespace_label_prefix_is_par() {
        // Two independent assigns → wrapping namespace labels should be __par_0 and __par_1
        let prog = make_prog(vec![assign("x", int_lit(1)), assign("y", int_lit(2))]);
        let result = parallel_detect(&prog);
        let ns_names: Vec<&str> = result
            .body
            .iter()
            .filter_map(|s| match s {
                Statement::Namespace(ns) => Some(ns.name.as_str()),
                _ => None,
            })
            .collect();
        assert!(
            ns_names.iter().any(|n| n.starts_with("__par_")),
            "wrapper namespaces should be named __par_N, got {:?}",
            ns_names
        );
    }
}
