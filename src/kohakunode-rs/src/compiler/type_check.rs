//! Type checking pass — validate variable types against @typehint declarations.
//!
//! Mirror of `kohakunode/compiler/type_check.py`.

use std::collections::HashMap;

use crate::ast::{
    Assignment, Expression, FuncCall, OutputTarget, Program, Statement, TypeExpr, TypeHintBlock,
    TypeHintEntry,
};

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Run the type-checking pass on *program*.
///
/// Returns `Ok(program.clone())` on success, or `Err(Vec<String>)` containing
/// all error messages collected before giving up.
pub fn type_check(program: &Program) -> Result<Program, Vec<String>> {
    let mut type_env: HashMap<String, TypeHintEntry> = HashMap::new();
    collect_typehints(program, &mut type_env);

    let mut var_types: HashMap<String, TypeExpr> = HashMap::new();
    let mut errors: Vec<String> = Vec::new();

    check_body(&program.body, &mut type_env, &mut var_types, &mut errors);

    if errors.is_empty() {
        Ok(program.clone())
    } else {
        Err(errors)
    }
}

// ---------------------------------------------------------------------------
// Type compatibility
// ---------------------------------------------------------------------------

fn types_compatible(actual: &TypeExpr, expected: &TypeExpr) -> bool {
    // Expected is a union — check BEFORE the Any-name shortcut so union_of
    // takes priority over the name field.
    if let Some(ref members) = expected.union_of {
        return members.iter().any(|m| types_compatible(actual, m));
    }

    // Any matches everything (only when expected has no union_of)
    if expected.name == "Any" || actual.name == "Any" {
        return true;
    }

    // Expected is optional (A?) — matches A or none
    if expected.is_optional {
        let inner = TypeExpr {
            name: expected.name.clone(),
            is_optional: false,
            union_of: None,
            line: None,
        };
        return types_compatible(actual, &inner)
            || actual.name == "none";
    }

    // Actual is a union — all members must satisfy expected
    if let Some(ref members) = actual.union_of {
        return members.iter().all(|m| types_compatible(m, expected));
    }

    // Actual is optional — compatible if expected accepts A or none
    if actual.is_optional {
        let inner = TypeExpr {
            name: actual.name.clone(),
            is_optional: false,
            union_of: None,
            line: None,
        };
        let none_t = TypeExpr {
            name: "none".to_string(),
            is_optional: false,
            union_of: None,
            line: None,
        };
        return types_compatible(&inner, expected) || types_compatible(&none_t, expected);
    }

    // Plain name match
    actual.name == expected.name
}

fn type_str(t: &TypeExpr) -> String {
    if let Some(ref members) = t.union_of {
        return members
            .iter()
            .map(type_str)
            .collect::<Vec<_>>()
            .join(" | ");
    }
    if t.is_optional {
        return format!("{}?", t.name);
    }
    t.name.clone()
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn collect_typehints(program: &Program, type_env: &mut HashMap<String, TypeHintEntry>) {
    if let Some(ref hints) = program.typehints {
        for entry in hints {
            type_env.insert(entry.func_name.clone(), entry.clone());
        }
    }
    for stmt in &program.body {
        if let Statement::TypeHintBlock(block) = stmt {
            collect_from_block(block, type_env);
        }
    }
}

fn collect_from_block(block: &TypeHintBlock, type_env: &mut HashMap<String, TypeHintEntry>) {
    for entry in &block.entries {
        type_env.insert(entry.func_name.clone(), entry.clone());
    }
}

fn infer_expr_type(
    expr: &Expression,
    var_types: &HashMap<String, TypeExpr>,
) -> Option<TypeExpr> {
    match expr {
        Expression::Identifier(id) => var_types.get(&id.name).cloned(),
        Expression::Literal(lit) => Some(TypeExpr {
            name: if lit.literal_type.is_empty() {
                "Any".to_string()
            } else {
                lit.literal_type.clone()
            },
            is_optional: false,
            union_of: None,
            line: None,
        }),
        Expression::KeywordArg(kw) => infer_expr_type(&kw.value, var_types),
        _ => None,
    }
}

fn check_body(
    stmts: &[Statement],
    type_env: &mut HashMap<String, TypeHintEntry>,
    var_types: &mut HashMap<String, TypeExpr>,
    errors: &mut Vec<String>,
) {
    for stmt in stmts {
        check_stmt(stmt, type_env, var_types, errors);
    }
}

fn check_stmt(
    stmt: &Statement,
    type_env: &mut HashMap<String, TypeHintEntry>,
    var_types: &mut HashMap<String, TypeExpr>,
    errors: &mut Vec<String>,
) {
    match stmt {
        Statement::Assignment(a) => {
            check_assignment(a, var_types);
        }
        Statement::FuncCall(f) => {
            check_func_call(f, type_env, var_types, errors);
        }
        Statement::Namespace(ns) => {
            check_body(&ns.body, type_env, var_types, errors);
        }
        Statement::SubgraphDef(sg) => {
            let mut inner_vars = var_types.clone();
            check_body(&sg.body, type_env, &mut inner_vars, errors);
        }
        Statement::TryExcept(t) => {
            check_body(&t.try_body, type_env, var_types, errors);
            check_body(&t.except_body, type_env, var_types, errors);
        }
        Statement::TypeHintBlock(block) => {
            collect_from_block(block, type_env);
        }
        _ => {}
    }
}

fn check_assignment(a: &Assignment, var_types: &mut HashMap<String, TypeExpr>) {
    if let Some(ref annotation) = a.type_annotation {
        var_types.insert(a.target.clone(), annotation.clone());
    } else if !var_types.contains_key(&a.target) {
        if let Some(inferred) = infer_expr_type(&a.value, var_types) {
            var_types.insert(a.target.clone(), inferred);
        }
    }
}

fn check_func_call(
    f: &FuncCall,
    type_env: &HashMap<String, TypeHintEntry>,
    var_types: &mut HashMap<String, TypeExpr>,
    errors: &mut Vec<String>,
) {
    if let Some(hint) = type_env.get(&f.func_name) {
        let line_info = f
            .line
            .map(|l| format!(" (line {l})"))
            .unwrap_or_default();

        if !hint.input_types.is_empty() {
            if f.inputs.len() != hint.input_types.len() {
                errors.push(format!(
                    "'{}'{}: expected {} input(s), got {}",
                    f.func_name,
                    line_info,
                    hint.input_types.len(),
                    f.inputs.len()
                ));
            } else {
                for (i, (inp, expected)) in
                    f.inputs.iter().zip(hint.input_types.iter()).enumerate()
                {
                    if let Some(actual) = infer_expr_type(inp, var_types) {
                        if !types_compatible(&actual, expected) {
                            errors.push(format!(
                                "'{}'{}: input {} expected type '{}', got '{}'",
                                f.func_name,
                                line_info,
                                i,
                                type_str(expected),
                                type_str(&actual)
                            ));
                        }
                    }
                }
            }
        }

        // Record output types
        let concrete: Vec<&String> = f
            .outputs
            .iter()
            .filter_map(|o| match o {
                OutputTarget::Name(n) => Some(n),
                OutputTarget::Wildcard => None,
            })
            .collect();

        for (i, out_name) in concrete.iter().enumerate() {
            if i < hint.output_types.len() {
                var_types.insert((*out_name).clone(), hint.output_types[i].clone());
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ast::{Expression, Identifier, Literal, OutputTarget, TypeHintEntry, Value};

    fn int_type() -> TypeExpr {
        TypeExpr {
            name: "int".to_string(),
            is_optional: false,
            union_of: None,
            line: None,
        }
    }

    fn float_type() -> TypeExpr {
        TypeExpr {
            name: "float".to_string(),
            is_optional: false,
            union_of: None,
            line: None,
        }
    }

    fn any_type() -> TypeExpr {
        TypeExpr {
            name: "Any".to_string(),
            is_optional: false,
            union_of: None,
            line: None,
        }
    }

    fn id_expr(name: &str) -> Expression {
        Expression::Identifier(Identifier {
            name: name.into(),
            line: None,
        })
    }

    fn int_lit_expr() -> Expression {
        Expression::Literal(Literal {
            value: Value::Int(1),
            literal_type: "int".into(),
            line: None,
        })
    }

    fn make_typehint(
        func_name: &str,
        inputs: Vec<TypeExpr>,
        outputs: Vec<TypeExpr>,
    ) -> TypeHintEntry {
        TypeHintEntry {
            func_name: func_name.to_string(),
            input_types: inputs,
            output_types: outputs,
            line: None,
        }
    }

    // ------------------------------------------------------------------
    // Compatibility rules
    // ------------------------------------------------------------------

    #[test]
    fn any_matches_everything() {
        assert!(types_compatible(&int_type(), &any_type()));
        assert!(types_compatible(&any_type(), &int_type()));
    }

    #[test]
    fn same_type_matches() {
        assert!(types_compatible(&int_type(), &int_type()));
    }

    #[test]
    fn different_types_dont_match() {
        assert!(!types_compatible(&int_type(), &float_type()));
    }

    #[test]
    fn union_expected_matches_member() {
        let union_t = TypeExpr {
            name: String::new(),
            is_optional: false,
            union_of: Some(vec![int_type(), float_type()]),
            line: None,
        };
        assert!(types_compatible(&int_type(), &union_t));
        assert!(types_compatible(&float_type(), &union_t));
    }

    #[test]
    fn optional_matches_base_and_none() {
        let optional_int = TypeExpr {
            name: "int".to_string(),
            is_optional: true,
            union_of: None,
            line: None,
        };
        assert!(types_compatible(&int_type(), &optional_int));
        let none_t = TypeExpr {
            name: "none".to_string(),
            is_optional: false,
            union_of: None,
            line: None,
        };
        assert!(types_compatible(&none_t, &optional_int));
    }

    // ------------------------------------------------------------------
    // Valid program — no errors
    // ------------------------------------------------------------------

    #[test]
    fn valid_program_no_error() {
        // add(int, int) -> int, called with two int literals
        let hint = make_typehint("add", vec![int_type(), int_type()], vec![int_type()]);
        let prog = Program {
            body: vec![Statement::FuncCall(FuncCall {
                inputs: vec![int_lit_expr(), int_lit_expr()],
                func_name: "add".into(),
                outputs: vec![OutputTarget::Name("result".into())],
                metadata: None,
                line: Some(1),
            })],
            mode: None,
            typehints: Some(vec![hint]),
            line: None,
        };
        assert!(type_check(&prog).is_ok());
    }

    // ------------------------------------------------------------------
    // Type mismatch — should error with line number
    // ------------------------------------------------------------------

    #[test]
    fn type_mismatch_returns_error_with_line() {
        // add expects (int, int) but we pass a float literal for arg 0
        let hint = make_typehint("add", vec![int_type(), int_type()], vec![int_type()]);

        let float_lit = Expression::Literal(Literal {
            value: Value::Float(1.0),
            literal_type: "float".into(),
            line: None,
        });

        let prog = Program {
            body: vec![Statement::FuncCall(FuncCall {
                inputs: vec![float_lit, int_lit_expr()],
                func_name: "add".into(),
                outputs: vec![OutputTarget::Name("result".into())],
                metadata: None,
                line: Some(5),
            })],
            mode: None,
            typehints: Some(vec![hint]),
            line: None,
        };

        let result = type_check(&prog);
        assert!(result.is_err());
        let errs = result.unwrap_err();
        assert_eq!(errs.len(), 1);
        assert!(errs[0].contains("line 5"), "error should include line number");
        assert!(errs[0].contains("int"), "error should mention expected type");
        assert!(errs[0].contains("float"), "error should mention actual type");
    }

    // ------------------------------------------------------------------
    // Wrong input count
    // ------------------------------------------------------------------

    #[test]
    fn wrong_input_count_errors() {
        let hint = make_typehint("add", vec![int_type(), int_type()], vec![int_type()]);
        let prog = Program {
            body: vec![Statement::FuncCall(FuncCall {
                inputs: vec![int_lit_expr()], // only 1 instead of 2
                func_name: "add".into(),
                outputs: vec![OutputTarget::Name("r".into())],
                metadata: None,
                line: Some(3),
            })],
            mode: None,
            typehints: Some(vec![hint]),
            line: None,
        };
        let result = type_check(&prog);
        assert!(result.is_err());
        let errs = result.unwrap_err();
        assert!(errs[0].contains("expected 2"));
        assert!(errs[0].contains("got 1"));
    }
}
