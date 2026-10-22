//! Source provenance independent of editor metadata and canonical semantic text.
use crate::errors::{KirError, Result};
use crate::syntax::ast::{Kind, Origin, Program, Stmt};
use crate::util::json::Json;

/// Portable structured provenance; optional properties are explicit nulls.
pub fn origin_json(origin: &Origin) -> Json {
    Json::Object(vec![
        ("module".into(), Json::str(&origin.module)),
        ("node_id".into(), Json::str(&origin.node_id)),
        ("line".into(), origin.line.as_ref().map_or(Json::Null, |n| Json::Int(n.clone()))),
        ("definition".into(), Json::opt_str(origin.definition.as_deref())),
        ("calls".into(), Json::Array(origin.calls.iter().map(origin_json).collect())),
        ("generated".into(), Json::opt_str(origin.generated.as_deref())),
    ])
}

/// Decode graph provenance independently of the editor metadata switch.
pub fn origin_from_json(value: Option<&Json>) -> Result<Option<Origin>> {
    let Some(value) = value.filter(|v| !v.is_null()) else { return Ok(None) };
    let error = |s: &str| KirError::Graph(s.to_string());
    let module = value.get("module").and_then(Json::as_str);
    let node_id = value.get("node_id").and_then(Json::as_str);
    let (Some(module), Some(node_id)) = (module, node_id) else {
        return Err(error("origin requires string module and node_id"));
    };
    let line = match value.get("line") {
        None | Some(Json::Null) => None,
        Some(Json::Int(n)) => Some(n.clone()),
        _ => return Err(error("origin line must be an integer or null")),
    };
    let string = |key: &str| -> Result<Option<String>> {
        match value.get(key) {
            None | Some(Json::Null) => Ok(None),
            Some(Json::Str(s)) => Ok(Some(s.clone())),
            _ => Err(error(&format!("origin {key} must be a string or null"))),
        }
    };
    let calls = match value.get("calls") {
        None => vec![],
        Some(Json::Array(calls)) => calls
            .iter()
            .map(|c| origin_from_json(Some(c))?.ok_or_else(|| error("origin calls must be a sequence of origins")))
            .collect::<Result<Vec<_>>>()?,
        _ => return Err(error("origin calls must be a sequence of origins")),
    };
    Ok(Some(Origin {
        module: module.into(),
        node_id: node_id.into(),
        line,
        definition: string("definition")?,
        calls,
        generated: string("generated")?,
    }))
}

/// Stamp unstamped statements on a copy. Fallback IDs are traversal paths and
/// stable under formatting, not arbitrary source edits.
pub fn stamp_origins(program: &Program, module: &str) -> Program {
    fn stamp(stmts: &mut [Stmt], path: &str, module: &str, definition: Option<&str>) {
        for (index, stmt) in stmts.iter_mut().enumerate() {
            let node_path = format!("{path}/{index}");
            let context = match &stmt.kind {
                Kind::Def(d) => Some(d.name.clone()),
                _ => definition.map(str::to_string),
            };
            if stmt.origin.is_none() {
                stmt.origin = Some(Origin {
                    module: module.to_string(),
                    node_id: stmt
                        .meta
                        .get("node_id")
                        .filter(|v| !matches!(v, crate::syntax::value::Value::None))
                        .map_or_else(|| node_path.clone(), |v| v.py_str()),
                    line: stmt.line.map(Into::into),
                    definition: context.clone(),
                    calls: vec![],
                    generated: None,
                });
            }
            for (child_index, body) in stmt.children_mut().into_iter().enumerate() {
                let field = if child_index == 0 { "body" } else { "handler" };
                stamp(body, &format!("{node_path}/{field}"), module, context.as_deref());
            }
        }
    }
    let mut result = program.clone();
    stamp(&mut result.body, "body", module, None);
    result
}

/// Preserve a source location while appending ancestry and/or a generated role.
/// Missing origins stay missing for passes applied directly to unstamped trees.
pub fn derive_origin(origin: Option<&Origin>, generated: Option<&str>, calls: &[Origin]) -> Option<Origin> {
    origin.map(|o| {
        let mut result = o.clone();
        result.calls.extend_from_slice(calls);
        // Flat outermost-first locations retain all ancestry without recursively
        // duplicating it (which would make serialization exponential in depth).
        for call in &mut result.calls {
            call.calls.clear();
        }
        if let Some(role) = generated {
            result.generated = Some(role.to_string());
        }
        result
    })
}
