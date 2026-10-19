//! Type expressions: parsing from text, literal types, and compatibility.

use crate::syntax::ast::TypeExpr;
use crate::syntax::value::Value;
use crate::syntax::writer::write_type;

/// Parse the type syntax of language.md (`Image`, `Node?`, `list[Box]`, `A | B`, `_`).
pub fn parse_type(text: &str) -> Result<TypeExpr, String> {
    let tokens = tokenize(text)?;
    let (t, pos) = union(&tokens, 0, text)?;
    if pos != tokens.len() {
        return Err(format!("bad type {}", crate::util::pyfmt::str_repr(text)));
    }
    Ok(t)
}

fn tokenize(text: &str) -> Result<Vec<String>, String> {
    let (mut out, mut word) = (Vec::new(), String::new());
    for ch in text.chars() {
        if ch.is_alphanumeric() || ch == '_' || ch == '.' {
            word.push(ch);
            continue;
        }
        if !word.is_empty() {
            out.push(std::mem::take(&mut word));
        }
        if "[],|?".contains(ch) {
            out.push(ch.to_string());
        } else if !ch.is_whitespace() {
            return Err(format!(
                "bad character {} in type {}",
                crate::util::pyfmt::str_repr(&ch.to_string()),
                crate::util::pyfmt::str_repr(text)
            ));
        }
    }
    if !word.is_empty() {
        out.push(word);
    }
    Ok(out)
}

fn token<'a>(tokens: &'a [String], pos: usize, text: &str) -> Result<&'a str, String> {
    tokens.get(pos).map(String::as_str).ok_or_else(|| format!("bad type {}", crate::util::pyfmt::str_repr(text)))
}

fn union(tokens: &[String], pos: usize, text: &str) -> Result<(TypeExpr, usize), String> {
    let (t, mut pos) = atom(tokens, pos, text)?;
    let mut parts = vec![t];
    while tokens.get(pos).is_some_and(|t| t == "|") {
        let (t, p) = atom(tokens, pos + 1, text)?;
        parts.push(t);
        pos = p;
    }
    let t = if parts.len() == 1 { parts.pop().expect("one part") } else { TypeExpr::Union(parts) };
    Ok((t, pos))
}

fn atom(tokens: &[String], pos: usize, text: &str) -> Result<(TypeExpr, usize), String> {
    let name = token(tokens, pos, text)?.to_string();
    let mut pos = pos + 1;
    if name == "_" {
        return Ok((TypeExpr::Any, pos));
    }
    let mut t = TypeExpr::Name(name.clone());
    if tokens.get(pos).is_some_and(|t| t == "[") {
        let mut args = Vec::new();
        pos += 1;
        loop {
            let (a, p) = union(tokens, pos, text)?;
            args.push(a);
            pos = p;
            match token(tokens, pos, text)? {
                "," => pos += 1,
                "]" => {
                    pos += 1;
                    break;
                }
                _ => return Err("bad generic type".into()),
            }
        }
        t = TypeExpr::Generic(name, args);
    }
    if tokens.get(pos).is_some_and(|t| t == "?") {
        t = TypeExpr::Optional(Box::new(t));
        pos += 1;
    }
    Ok((t, pos))
}

/// The type of a literal value; `_` for tuples.
pub fn literal_type(value: &Value) -> TypeExpr {
    let name = match value {
        Value::Bool(_) => "bool",
        Value::Int(_) => "int",
        Value::Float(_) => "float",
        Value::Str(_) => "str",
        Value::None => "None",
        Value::List(_) => "list",
        Value::Dict(_) => "dict",
        Value::Tuple(_) => return TypeExpr::Any,
    };
    TypeExpr::name(name)
}

fn alternatives(t: &TypeExpr) -> Vec<TypeExpr> {
    match t {
        TypeExpr::Union(parts) => parts.iter().flat_map(alternatives).collect(),
        TypeExpr::Optional(inner) => {
            let mut out = alternatives(inner);
            out.push(TypeExpr::name("None"));
            out
        }
        t => vec![t.clone()],
    }
}

/// Whether a value of type `value` may flow into a port of type `port`.
pub fn fits(value: Option<&TypeExpr>, port: Option<&TypeExpr>) -> bool {
    let (Some(value), Some(port)) = (value, port) else { return true };
    if value.is_any() || port.is_any() {
        return true;
    }
    let targets = alternatives(port);
    alternatives(value).iter().all(|v| targets.iter().any(|t| fits_one(v, t)))
}

fn fits_one(v: &TypeExpr, t: &TypeExpr) -> bool {
    match (v, t) {
        (TypeExpr::Any, _) | (_, TypeExpr::Any) => true,
        (TypeExpr::Name(a), TypeExpr::Name(b)) => a == b || (a == "int" && b == "float"),
        (TypeExpr::Generic(a, _), TypeExpr::Name(b)) | (TypeExpr::Name(a), TypeExpr::Generic(b, _)) => a == b,
        (TypeExpr::Generic(a, xs), TypeExpr::Generic(b, ys)) => {
            a == b && xs.len() == ys.len() && xs.iter().zip(ys).all(|(x, y)| fits(Some(x), Some(y)))
        }
        _ => false,
    }
}

pub fn type_text(t: Option<&TypeExpr>) -> String {
    t.map_or("_".to_string(), write_type)
}
