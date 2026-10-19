//! Text-in, text-out entry points shared by the Python and wasm bindings.

use std::path::PathBuf;
use std::sync::Arc;

use crate::check::Diagnostic;
use crate::compiler::{compile_program, env_for, Compiled};
use crate::errors::{KirError, Result};
use crate::graph::to_graph::json_literal;
use crate::sig::env::build_env;
use crate::sig::files::{library_from_text, library_to_json};
use crate::sig::model::Library;
use crate::sig::std::std_library;
use crate::syntax::ast::{Directives, Expr, Kind, Program, Stmt};
use crate::syntax::writer::write_type;
use crate::util::json::{self, Json};
use crate::{check, graph, syntax};

/// Where a program's node signatures come from: signature-file texts given as
/// unaliased libraries, plus `@use` resolution (signatures.md, "Resolution")
/// against `base` (the program's directory, for relative `.kirsig.json` paths)
/// and `sig_path` (directories searched for `<library>.kirsig.json`, then
/// `KIR_SIG_PATH`).
#[derive(Clone, Copy, Default)]
pub struct Signatures<'a> {
    pub texts: &'a [String],
    pub base: Option<&'a str>,
    pub sig_path: &'a [String],
}

impl<'a> Signatures<'a> {
    pub fn texts(texts: &'a [String]) -> Self {
        Signatures { texts, ..Signatures::default() }
    }

    pub fn libraries(&self) -> Result<Vec<Arc<Library>>> {
        libraries(self.texts)
    }

    fn base(&self) -> Option<PathBuf> {
        self.base.map(PathBuf::from)
    }

    fn search(&self) -> Vec<PathBuf> {
        self.sig_path.iter().map(PathBuf::from).collect()
    }
}

/// Libraries from signature-file texts.
pub fn libraries(sigs: &[String]) -> Result<Vec<Arc<Library>>> {
    sigs.iter()
        .map(|s| {
            library_from_text(s).map(Arc::new).map_err(|e| match e {
                KirError::Value(m) => KirError::Signature(m),
                other => other,
            })
        })
        .collect()
}

/// Canonical text (`write(parse(source))`).
pub fn format(source: &str) -> Result<String> {
    syntax::write(&syntax::parse(source)?)
}

/// Every diagnostic as a JSON list of `{code, message, line, severity}`, in source
/// order; a signature that cannot be resolved or loaded is diagnostic `E002`.
pub fn check(source: &str, sigs: Signatures) -> Result<String> {
    let program = syntax::parse(source)?;
    let diags = match env_for(&program, &sigs.libraries()?, sigs.base().as_deref(), &sigs.search()) {
        Ok(env) => check::check(&program, &env),
        Err(KirError::Check(d)) => d,
        Err(e) => return Err(e),
    };
    Ok(diagnostics_json(&diags).dumps())
}

pub fn diagnostics_json(diags: &[Diagnostic]) -> Json {
    Json::Array(
        diags
            .iter()
            .map(|d| {
                Json::Object(vec![
                    ("code".into(), Json::str(&d.code)),
                    ("message".into(), Json::str(&d.message)),
                    ("line".into(), d.line.map_or(Json::Null, |l| Json::int(l as i64))),
                    ("severity".into(), Json::str(d.severity())),
                ])
            })
            .collect(),
    )
}

fn compile(source: &str, sigs: Signatures, passes: Option<&[String]>) -> Result<Compiled> {
    let names: Option<Vec<&str>> = passes.map(|p| p.iter().map(String::as_str).collect());
    let libs = sigs.libraries()?;
    compile_program(syntax::parse(source)?, &libs, sigs.base().as_deref(), &sigs.search(), names.as_deref())
}

/// The canonical text of a checked program after the named passes (default: all);
/// fails with the diagnostics (`E002` for signatures) like `compile_program`.
pub fn lower(source: &str, sigs: Signatures, passes: Option<&[String]>) -> Result<String> {
    syntax::write(&compile(source, sigs, passes)?.lowered)
}

/// `{"semantic": ..., "full": ...}` of the program after the passes, as `hashes.json` holds it.
pub fn hashes(source: &str, sigs: Signatures, passes: Option<&[String]>) -> Result<String> {
    let compiled = compile(source, sigs, passes)?;
    let j = Json::Object(vec![
        ("semantic".into(), Json::str(compiled.semantic_hash)),
        ("full".into(), Json::str(compiled.full_hash)),
    ]);
    Ok(j.dumps_indent(2) + "\n")
}

/// The `.kirgraph` text of a program (`json.dumps(graph, indent=2, ensure_ascii=False) + "\n"`);
/// a signature failure is `KirError::Signature`, as `build_env` raises it. `data` is a
/// data style name (`"wires"` or `"variables"`), checked after the program and its env.
pub fn to_graph(source: &str, sigs: Signatures, data: &str) -> Result<String> {
    let program = syntax::parse(source)?;
    let env = build_env(&program, &sigs.libraries()?, sigs.base().as_deref(), &sigs.search(), false)?;
    Ok(graph::to_graph(&program, Some(&env), graph::DataStyle::parse(data)?)?.dumps_indent(2) + "\n")
}

/// The canonical text of a `.kirgraph` document.
pub fn from_graph(graph_json: &str, with_meta: bool) -> Result<String> {
    let g = json::loads(graph_json).map_err(KirError::Graph)?;
    syntax::write(&graph::from_graph(&g, with_meta)?)
}

/// The `kir.std` signature file text.
pub fn std_signatures() -> Result<String> {
    Ok(library_to_json(std_library())?.dumps_indent(2) + "\n")
}

// ---------------------------------------------------------------- AST JSON

/// The AST as JSON: `{uses, mode, body}`; each statement has `kind`, `line`,
/// `meta`, `hint` and its fields; expressions are `{"name": n}` or
/// `{"literal": v}` (graph literal encoding); types are canonical type text.
pub fn parse_to_json(source: &str) -> Result<String> {
    Ok(program_json(&syntax::parse(source)?).dumps())
}

pub fn program_json(p: &Program) -> Json {
    let uses = p
        .uses
        .iter()
        .map(|u| {
            Json::Object(vec![
                ("library".into(), Json::str(&u.library)),
                ("alias".into(), Json::opt_str(u.alias.as_deref())),
            ])
        })
        .collect();
    Json::Object(vec![
        ("uses".into(), Json::Array(uses)),
        ("mode".into(), Json::opt_str(p.mode.as_deref())),
        ("body".into(), stmts_json(&p.body)),
    ])
}

fn stmts_json(stmts: &[Stmt]) -> Json {
    Json::Array(stmts.iter().map(stmt_json).collect())
}

fn expr_json(e: &Expr) -> Json {
    match e {
        Expr::Name(n) => Json::Object(vec![("name".into(), Json::str(n))]),
        Expr::Literal(v) => Json::Object(vec![("literal".into(), json_literal(v))]),
    }
}

fn directives_json(d: &Directives) -> Json {
    Json::Object(d.iter().map(|(k, v)| (k.clone(), json_literal(v))).collect())
}

fn stmt_json(s: &Stmt) -> Json {
    let opt = |o: &Option<String>| Json::opt_str(o.as_deref());
    let (kind, fields): (&str, Vec<(&str, Json)>) = match &s.kind {
        Kind::Assign { target, value, ty } => (
            "assign",
            vec![
                ("target", Json::str(target)),
                ("value", expr_json(value)),
                ("type", ty.as_ref().map_or(Json::Null, |t| Json::str(write_type(t)))),
            ],
        ),
        Kind::Call { name, args, outs } => (
            "call",
            vec![
                ("name", Json::str(name)),
                (
                    "args",
                    Json::Array(
                        args.iter()
                            .map(|a| {
                                Json::Object(vec![("key".into(), opt(&a.key)), ("value".into(), expr_json(&a.value))])
                            })
                            .collect(),
                    ),
                ),
                ("outs", Json::Array(outs.iter().map(opt).collect())),
            ],
        ),
        Kind::Branch { cond, true_label, false_label } => (
            "branch",
            vec![
                ("cond", expr_json(cond)),
                ("true_label", Json::str(true_label)),
                ("false_label", Json::str(false_label)),
            ],
        ),
        Kind::Switch { value, cases, default } => (
            "switch",
            vec![
                ("value", expr_json(value)),
                (
                    "cases",
                    Json::Array(cases.iter().map(|(v, l)| Json::Array(vec![json_literal(v), Json::str(l)])).collect()),
                ),
                ("default", opt(default)),
            ],
        ),
        Kind::Jump { label } => ("jump", vec![("label", Json::str(label))]),
        Kind::Parallel { labels } => ("parallel", vec![("labels", Json::strs(labels))]),
        Kind::Each { items, item, index, label, has_index } => (
            "each",
            vec![
                ("items", expr_json(items)),
                ("item", opt(item)),
                ("index", opt(index)),
                ("label", Json::str(label)),
                ("has_index", Json::Bool(*has_index)),
            ],
        ),
        Kind::Namespace { label, body } => ("namespace", vec![("label", Json::str(label)), ("body", stmts_json(body))]),
        Kind::Dataflow { body } => ("dataflow", vec![("body", stmts_json(body))]),
        Kind::Try { body, handler, error_name } => {
            ("try", vec![("body", stmts_json(body)), ("handler", stmts_json(handler)), ("error_name", opt(error_name))])
        }
        Kind::Def(d) => {
            let ty =
                |t: &Option<crate::syntax::ast::TypeExpr>| t.as_ref().map_or(Json::Null, |t| Json::str(write_type(t)));
            let params = d
                .params
                .iter()
                .map(|p| {
                    Json::Object(vec![
                        ("name".into(), Json::str(&p.name)),
                        ("type".into(), ty(&p.ty)),
                        ("default".into(), p.default.as_ref().map_or(Json::Null, expr_json)),
                    ])
                })
                .collect();
            let outputs = d
                .outputs
                .iter()
                .map(|o| Json::Object(vec![("name".into(), Json::str(&o.name)), ("type".into(), ty(&o.ty))]))
                .collect();
            (
                "def",
                vec![
                    ("name", Json::str(&d.name)),
                    ("params", Json::Array(params)),
                    ("outputs", Json::Array(outputs)),
                    ("body", stmts_json(&d.body)),
                ],
            )
        }
        Kind::TypeHints { entries } => (
            "typehints",
            vec![(
                "entries",
                Json::Array(
                    entries
                        .iter()
                        .map(|e| {
                            Json::Object(vec![
                                ("name".into(), Json::str(&e.name)),
                                (
                                    "inputs".into(),
                                    Json::Array(e.inputs.iter().map(|t| Json::str(write_type(t))).collect()),
                                ),
                                (
                                    "outputs".into(),
                                    Json::Array(e.outputs.iter().map(|t| Json::str(write_type(t))).collect()),
                                ),
                            ])
                        })
                        .collect(),
                ),
            )],
        ),
    };
    let mut o = vec![
        ("kind".to_string(), Json::str(kind)),
        ("line".to_string(), s.line.map_or(Json::Null, |l| Json::int(l as i64))),
        ("meta".to_string(), directives_json(&s.meta)),
        ("hint".to_string(), directives_json(&s.hint)),
    ];
    o.extend(fields.into_iter().map(|(k, v)| (k.to_string(), v)));
    Json::Object(o)
}
