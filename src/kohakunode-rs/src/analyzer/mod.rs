//! Scope analyzer and validator for KohakuNodeIR programs.
//!
//! Ports `kohakunode/analyzer/scope.py` and `kohakunode/analyzer/validator.py`.
//!
//! Entry point: [`validate`] — walks the full AST and returns all errors found.
//! Never stops at the first error; the full list is always collected.

use std::collections::{HashMap, HashSet};

use crate::ast::{Expression, OutputTarget, Program, Statement, SubgraphDef};

// ---------------------------------------------------------------------------
// Public error type
// ---------------------------------------------------------------------------

/// An analysis error (or warning) produced by the scope / variable analyzer.
#[derive(Clone, Debug, PartialEq)]
pub struct AnalysisError {
    pub message: String,
    pub line: Option<usize>,
    /// Whether this is a warning rather than a hard error (e.g. unreachable
    /// namespace).
    pub is_warning: bool,
}

impl AnalysisError {
    fn error(message: impl Into<String>, line: Option<usize>) -> Self {
        Self {
            message: message.into(),
            line,
            is_warning: false,
        }
    }

    fn warning(message: impl Into<String>, line: Option<usize>) -> Self {
        Self {
            message: message.into(),
            line,
            is_warning: true,
        }
    }
}

impl std::fmt::Display for AnalysisError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let kind = if self.is_warning { "warning" } else { "error" };
        match self.line {
            Some(l) => write!(f, "{kind} (line {l}): {}", self.message),
            None => write!(f, "{kind}: {}", self.message),
        }
    }
}

impl std::error::Error for AnalysisError {}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Validate a [`Program`] and return all errors and warnings found.
///
/// Returns `Ok(())` when there are no hard errors (warnings are discarded).
/// Returns `Err(errors)` containing only hard errors when any exist.
///
/// Warnings (unreachable namespaces) are not included in the `Err` list; use
/// [`validate_all`] to retrieve them separately.
pub fn validate(program: &Program) -> Result<(), Vec<AnalysisError>> {
    let issues = analyze(program);
    let errors: Vec<AnalysisError> = issues.into_iter().filter(|e| !e.is_warning).collect();
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors)
    }
}

/// Run all analyzers and return every issue (errors + warnings).
pub fn analyze(program: &Program) -> Vec<AnalysisError> {
    let mut errors = Vec::new();
    ScopeAnalyzer::new().analyze(program, &mut errors);
    VariableAnalyzer::new().analyze(program, &mut errors);
    errors
}

// ---------------------------------------------------------------------------
// Scope analyzer  (ports scope.py)
// ---------------------------------------------------------------------------

struct ScopeAnalyzer;

impl ScopeAnalyzer {
    fn new() -> Self {
        Self
    }

    fn analyze(&self, program: &Program, errors: &mut Vec<AnalysisError>) {
        self.check_duplicate_subgraphs(&program.body, errors);
        self.analyze_scope(&program.body, errors, &HashSet::new());
    }

    // --- Duplicate @def subgraph names (program-wide, top-level only) -------

    fn check_duplicate_subgraphs(&self, stmts: &[Statement], errors: &mut Vec<AnalysisError>) {
        let mut seen: HashMap<&str, Option<usize>> = HashMap::new();
        for stmt in stmts {
            if let Statement::SubgraphDef(def) = stmt {
                if let Some(&first_line) = seen.get(def.name.as_str()) {
                    let msg = match (first_line, def.line) {
                        (Some(fl), Some(dl)) => format!(
                            "Duplicate subgraph definition '{}' (first at line {fl}, redefined at line {dl})",
                            def.name
                        ),
                        _ => format!("Duplicate subgraph definition '{}'", def.name),
                    };
                    errors.push(AnalysisError::error(msg, def.line));
                } else {
                    seen.insert(&def.name, def.line);
                }
            }
        }
    }

    // --- Recursive scope analysis -------------------------------------------

    fn analyze_scope(
        &self,
        stmts: &[Statement],
        errors: &mut Vec<AnalysisError>,
        ancestor_namespaces: &HashSet<String>,
    ) {
        // Collect namespace definitions at this scope level.
        let mut namespace_defs: HashMap<String, Option<usize>> = HashMap::new();
        for stmt in stmts {
            if let Statement::Namespace(ns) = stmt {
                if let Some(&first_line) = namespace_defs.get(ns.name.as_str()) {
                    let msg = match (first_line, ns.line) {
                        (Some(fl), Some(dl)) => format!(
                            "Duplicate namespace label '{}' (first at line {fl}, redefined at line {dl})",
                            ns.name
                        ),
                        _ => format!("Duplicate namespace label '{}'", ns.name),
                    };
                    errors.push(AnalysisError::error(msg, ns.line));
                } else {
                    namespace_defs.insert(ns.name.clone(), ns.line);
                }
            }
        }

        // Collect all label references at this scope level.
        let mut referenced_labels: HashMap<String, String> = HashMap::new();
        let mut jump_labels: HashMap<String, String> = HashMap::new();
        for stmt in stmts {
            let refs = self.collect_label_refs(stmt);
            for (label, context) in refs {
                let is_jump = matches!(stmt, Statement::Jump(_));
                referenced_labels.insert(label.clone(), context.clone());
                if is_jump {
                    jump_labels.insert(label, context);
                }
            }
        }

        // Check for undefined label references.
        for (label, context) in &referenced_labels {
            if namespace_defs.contains_key(label.as_str()) {
                continue;
            }
            // Jump can target ancestor-scope namespaces.
            if jump_labels.contains_key(label.as_str()) && ancestor_namespaces.contains(label) {
                continue;
            }
            errors.push(AnalysisError::error(
                format!("Undefined namespace label '{label}' referenced from {context}"),
                None,
            ));
        }

        // Warn about unreachable namespaces.
        for (ns_name, ns_line) in &namespace_defs {
            if !referenced_labels.contains_key(ns_name.as_str()) {
                errors.push(AnalysisError::warning(
                    format!(
                        "Unreachable namespace '{ns_name}' \u{2014} \
                         no branch, switch, jump, or parallel targets it"
                    ),
                    *ns_line,
                ));
            }
        }

        // Recurse into child scopes.
        let child_ancestors: HashSet<String> = ancestor_namespaces
            .iter()
            .cloned()
            .chain(namespace_defs.keys().cloned())
            .collect();

        for stmt in stmts {
            match stmt {
                Statement::Namespace(ns) => {
                    self.analyze_scope(&ns.body, errors, &child_ancestors);
                }
                Statement::SubgraphDef(def) => {
                    // Subgraph bodies are isolated: no ancestor namespaces
                    // bleed in.
                    self.analyze_scope(&def.body, errors, &HashSet::new());
                }
                Statement::DataflowBlock(blk) => {
                    self.analyze_scope(&blk.body, errors, &child_ancestors);
                }
                _ => {}
            }
        }
    }

    // --- Label reference collection ----------------------------------------

    fn collect_label_refs(&self, stmt: &Statement) -> Vec<(String, String)> {
        let mut refs = Vec::new();

        match stmt {
            Statement::Branch(b) => {
                let ctx = match b.line {
                    Some(l) => format!("branch (line {l})"),
                    None => "branch".to_string(),
                };
                if !b.true_label.is_empty() {
                    refs.push((b.true_label.clone(), ctx.clone()));
                }
                if !b.false_label.is_empty() {
                    refs.push((b.false_label.clone(), ctx));
                }
            }
            Statement::Switch(s) => {
                let ctx = match s.line {
                    Some(l) => format!("switch (line {l})"),
                    None => "switch".to_string(),
                };
                for (_expr, case_label) in &s.cases {
                    if !case_label.is_empty() {
                        refs.push((case_label.clone(), ctx.clone()));
                    }
                }
                if let Some(default_label) = &s.default_label {
                    if !default_label.is_empty() {
                        refs.push((default_label.clone(), ctx));
                    }
                }
            }
            Statement::Jump(j) => {
                let ctx = match j.line {
                    Some(l) => format!("jump (line {l})"),
                    None => "jump".to_string(),
                };
                if !j.target.is_empty() {
                    refs.push((j.target.clone(), ctx));
                }
            }
            Statement::Parallel(p) => {
                let ctx = match p.line {
                    Some(l) => format!("parallel (line {l})"),
                    None => "parallel".to_string(),
                };
                for label in &p.labels {
                    if !label.is_empty() {
                        refs.push((label.clone(), ctx.clone()));
                    }
                }
            }
            _ => {}
        }

        refs
    }
}

// ---------------------------------------------------------------------------
// Variable analyzer  (ports variables.py)
// ---------------------------------------------------------------------------

struct VariableAnalyzer;

impl VariableAnalyzer {
    fn new() -> Self {
        Self
    }

    fn analyze(&self, program: &Program, errors: &mut Vec<AnalysisError>) {
        let mut defined: HashSet<String> = HashSet::new();
        self.walk_body(&program.body, &mut defined, errors, true);
    }

    fn walk_body(
        &self,
        body: &[Statement],
        defined: &mut HashSet<String>,
        errors: &mut Vec<AnalysisError>,
        _top_level: bool,
    ) {
        for stmt in body {
            self.check_statement(stmt, defined, errors);
        }
    }

    fn check_statement(
        &self,
        stmt: &Statement,
        defined: &mut HashSet<String>,
        errors: &mut Vec<AnalysisError>,
    ) {
        match stmt {
            Statement::Assignment(a) => {
                // Check RHS first, then record LHS as defined.
                self.check_expression_input(&a.value, defined, errors, a.line);
                if !a.target.is_empty() && a.target != "_" {
                    defined.insert(a.target.clone());
                }
            }
            Statement::FuncCall(fc) => {
                // Check all inputs before recording outputs.
                for inp in &fc.inputs {
                    if matches!(inp, Expression::Wildcard(_)) {
                        errors.push(AnalysisError::error(
                            "Wildcard '_' can only be used in output position",
                            fc.line,
                        ));
                    } else {
                        self.check_expression_input(inp, defined, errors, fc.line);
                    }
                }
                // Record non-wildcard outputs as defined.
                for out in &fc.outputs {
                    if let OutputTarget::Name(name) = out {
                        if !name.is_empty() && name != "_" {
                            defined.insert(name.clone());
                        }
                    }
                }
            }
            Statement::Namespace(ns) => {
                // Recurse with a copy: outer defs are visible, inner defs
                // don't escape to the enclosing defined set.
                let mut inner_defined = defined.clone();
                self.walk_body(&ns.body, &mut inner_defined, errors, false);
            }
            Statement::DataflowBlock(blk) => {
                // Walk body; definitions inside are visible after the block.
                self.walk_body(&blk.body, defined, errors, false);
            }
            Statement::SubgraphDef(def) => {
                self.check_subgraphdef(def, defined, errors);
            }
            Statement::Branch(b) => {
                self.check_expression_input(&b.condition, defined, errors, b.line);
            }
            Statement::Switch(s) => {
                self.check_expression_input(&s.value, defined, errors, s.line);
            }
            // Jump, Parallel, ModeDecl, TypeHintBlock, and TryExcept have no variable
            // inputs (TryExcept bodies are not analysed individually here).
            Statement::Jump(_)
            | Statement::Parallel(_)
            | Statement::ModeDecl(_)
            | Statement::TypeHintBlock(_)
            | Statement::TryExcept(_) => {}
        }
    }

    fn check_subgraphdef(
        &self,
        def: &SubgraphDef,
        defined: &HashSet<String>,
        errors: &mut Vec<AnalysisError>,
    ) {
        // Validate parameter names don't shadow each other within the same
        // signature.
        let mut seen_params: HashSet<String> = HashSet::new();
        for param in &def.params {
            if seen_params.contains(&param.name) {
                errors.push(AnalysisError::error(
                    format!("@def {}: duplicate parameter '{}'", def.name, param.name),
                    param.line,
                ));
            } else {
                seen_params.insert(param.name.clone());
            }
        }

        // Analyze body with outer defs + param names pre-seeded.
        let mut inner_defined: HashSet<String> = defined
            .iter()
            .cloned()
            .chain(seen_params.iter().cloned())
            .collect();
        self.walk_body(&def.body, &mut inner_defined, errors, false);
    }

    fn check_expression_input(
        &self,
        expr: &Expression,
        defined: &HashSet<String>,
        errors: &mut Vec<AnalysisError>,
        line: Option<usize>,
    ) {
        match expr {
            Expression::Wildcard(_) => {
                errors.push(AnalysisError::error(
                    "Wildcard '_' can only be used in output position",
                    line,
                ));
            }
            Expression::Identifier(id) => {
                if id.name == "_" {
                    errors.push(AnalysisError::error(
                        "Wildcard '_' can only be used in output position",
                        line,
                    ));
                } else if !id.name.is_empty() && !defined.contains(&id.name) {
                    errors.push(AnalysisError::error(
                        format!("Undefined variable '{}'", id.name),
                        line,
                    ));
                }
            }
            Expression::KeywordArg(kw) => {
                // Recurse into the value side of a keyword argument.
                self.check_expression_input(&kw.value, defined, errors, line);
            }
            // Literals and label references are always valid inputs.
            Expression::Literal(_) | Expression::LabelRef(_) => {}
        }
    }
}

// ---------------------------------------------------------------------------
// PyO3 stub
// ---------------------------------------------------------------------------

#[cfg(feature = "pyo3")]
pub mod pyo3;

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ast::*;

    // -----------------------------------------------------------------------
    // Helper builders
    // -----------------------------------------------------------------------

    fn ns(name: &str, body: Vec<Statement>, line: Option<usize>) -> Statement {
        Statement::Namespace(Namespace {
            name: name.into(),
            body,
            line,
        })
    }

    fn jump(target: &str, line: Option<usize>) -> Statement {
        Statement::Jump(Jump {
            target: target.into(),
            metadata: None,
            line,
        })
    }

    fn branch(cond: &str, t: &str, f: &str, line: Option<usize>) -> Statement {
        Statement::Branch(Branch {
            condition: Expression::Identifier(Identifier {
                name: cond.into(),
                line: None,
            }),
            true_label: t.into(),
            false_label: f.into(),
            metadata: None,
            line,
        })
    }

    fn assignment(target: &str, value: &str, line: Option<usize>) -> Statement {
        Statement::Assignment(Assignment {
            target: target.into(),
            value: Expression::Identifier(Identifier {
                name: value.into(),
                line: None,
            }),
            type_annotation: None,
            metadata: None,
            line,
        })
    }

    fn assignment_lit(target: &str, val: i64, line: Option<usize>) -> Statement {
        Statement::Assignment(Assignment {
            target: target.into(),
            value: Expression::Literal(Literal {
                value: Value::Int(val),
                literal_type: "int".into(),
                line: None,
            }),
            type_annotation: None,
            metadata: None,
            line,
        })
    }

    fn program(body: Vec<Statement>) -> Program {
        Program {
            body,
            mode: None,
            typehints: None,
            line: None,
        }
    }

    // -----------------------------------------------------------------------
    // Valid programs
    // -----------------------------------------------------------------------

    #[test]
    fn valid_program_no_errors() {
        // x = 1; branch on x -> ns_a | ns_b; two namespaces defined.
        let prog = program(vec![
            assignment_lit("x", 1, Some(1)),
            branch("x", "ns_a", "ns_b", Some(2)),
            ns("ns_a", vec![], Some(3)),
            ns("ns_b", vec![], Some(4)),
        ]);
        assert_eq!(validate(&prog), Ok(()));
    }

    #[test]
    fn valid_jump_to_sibling() {
        let prog = program(vec![
            ns("start", vec![jump("end", Some(2))], Some(1)),
            ns("end", vec![], Some(3)),
        ]);
        // "start" is unreachable (warning only), "end" is targeted by jump.
        let issues = analyze(&prog);
        let errors: Vec<_> = issues.iter().filter(|e| !e.is_warning).collect();
        assert!(errors.is_empty(), "unexpected errors: {errors:?}");
    }

    // -----------------------------------------------------------------------
    // Undefined variable
    // -----------------------------------------------------------------------

    #[test]
    fn undefined_variable_reported_with_line() {
        let prog = program(vec![
            // Use "y" before defining it.
            assignment("x", "y", Some(5)),
        ]);
        let errs = validate(&prog).unwrap_err();
        assert!(!errs.is_empty());
        let err = &errs[0];
        assert!(
            err.message.contains("Undefined variable 'y'"),
            "got: {}",
            err.message
        );
        assert_eq!(err.line, Some(5));
    }

    #[test]
    fn defined_variable_no_error() {
        let prog = program(vec![
            assignment_lit("y", 42, Some(1)),
            assignment("x", "y", Some(2)),
        ]);
        assert_eq!(validate(&prog), Ok(()));
    }

    // -----------------------------------------------------------------------
    // Duplicate namespace label
    // -----------------------------------------------------------------------

    #[test]
    fn duplicate_namespace_label_reported() {
        let prog = program(vec![
            ns("loop", vec![], Some(1)),
            ns("loop", vec![], Some(5)),
        ]);
        let errs = validate(&prog).unwrap_err();
        assert!(!errs.is_empty());
        let err = &errs[0];
        assert!(
            err.message.contains("Duplicate namespace label 'loop'"),
            "got: {}",
            err.message
        );
        assert_eq!(err.line, Some(5));
    }

    // -----------------------------------------------------------------------
    // Undefined label reference
    // -----------------------------------------------------------------------

    #[test]
    fn undefined_label_in_branch() {
        let prog = program(vec![
            assignment_lit("cond", 1, Some(1)),
            branch("cond", "yes", "no", Some(2)),
            // "yes" exists but "no" does not.
            ns("yes", vec![], Some(3)),
        ]);
        let errs = validate(&prog).unwrap_err();
        let has_no_err = errs.iter().any(|e| e.message.contains("'no'"));
        assert!(has_no_err, "expected error about 'no', got: {errs:?}");
    }

    // -----------------------------------------------------------------------
    // Duplicate @def subgraph
    // -----------------------------------------------------------------------

    #[test]
    fn duplicate_subgraph_def_reported() {
        let def1 = Statement::SubgraphDef(SubgraphDef {
            name: "my_graph".into(),
            params: vec![],
            outputs: vec![],
            body: vec![],
            line: Some(1),
        });
        let def2 = Statement::SubgraphDef(SubgraphDef {
            name: "my_graph".into(),
            params: vec![],
            outputs: vec![],
            body: vec![],
            line: Some(10),
        });
        let prog = program(vec![def1, def2]);
        let errs = validate(&prog).unwrap_err();
        assert!(!errs.is_empty());
        assert!(
            errs[0]
                .message
                .contains("Duplicate subgraph definition 'my_graph'"),
            "got: {}",
            errs[0].message
        );
    }

    // -----------------------------------------------------------------------
    // Unreachable namespace is a warning, not an error
    // -----------------------------------------------------------------------

    #[test]
    fn unreachable_namespace_is_warning_not_error() {
        // A lone namespace with no one jumping to it.
        let prog = program(vec![ns("orphan", vec![], Some(1))]);
        // validate() should succeed (no hard errors).
        assert_eq!(validate(&prog), Ok(()));
        // But analyze() should return a warning.
        let issues = analyze(&prog);
        let warnings: Vec<_> = issues.iter().filter(|e| e.is_warning).collect();
        assert!(!warnings.is_empty());
        assert!(
            warnings[0].message.contains("orphan"),
            "got: {}",
            warnings[0].message
        );
    }

    // -----------------------------------------------------------------------
    // Jump can target ancestor-scope namespace
    // -----------------------------------------------------------------------

    #[test]
    fn jump_to_ancestor_namespace_is_valid() {
        // Sibling namespace "outer" is targeted by a jump from the nested
        // namespace "inner".  The jump target ("outer") lives in the ancestor
        // scope of "inner", which is allowed.
        let prog = program(vec![
            assignment_lit("x", 1, Some(1)),
            branch("x", "outer", "end", Some(2)),
            ns(
                "outer",
                vec![
                    assignment_lit("x", 1, Some(4)),
                    branch("x", "inner", "done", Some(5)),
                    ns("inner", vec![jump("outer", Some(7))], Some(6)),
                    ns("done", vec![], Some(8)),
                ],
                Some(3),
            ),
            ns("end", vec![], Some(9)),
        ]);
        // The jump from "inner" to "outer" is to an ancestor, which is allowed.
        let issues = analyze(&prog);
        let errors: Vec<_> = issues.iter().filter(|e| !e.is_warning).collect();
        assert!(errors.is_empty(), "unexpected errors: {errors:?}");
    }

    // -----------------------------------------------------------------------
    // Wildcard in input position
    // -----------------------------------------------------------------------

    #[test]
    fn wildcard_in_input_position_reported() {
        let prog = program(vec![Statement::FuncCall(FuncCall {
            inputs: vec![Expression::Wildcard(Wildcard { line: Some(1) })],
            func_name: "foo".into(),
            outputs: vec![],
            metadata: None,
            line: Some(1),
        })]);
        let errs = validate(&prog).unwrap_err();
        assert!(!errs.is_empty());
        assert!(
            errs[0]
                .message
                .contains("Wildcard '_' can only be used in output position"),
            "got: {}",
            errs[0].message
        );
    }
}
