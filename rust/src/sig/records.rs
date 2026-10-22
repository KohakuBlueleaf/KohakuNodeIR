//! Immutable portable record schemas. Operations are ordinary derived signatures.
use std::collections::{BTreeMap, BTreeSet, HashSet};

use crate::errors::{KirError, Result};
use crate::sig::model::{Port, Signature};
use crate::syntax::ast::TypeExpr;
use crate::syntax::value::Value;
use crate::util::pyfmt::str_repr;

fn invalid(message: impl Into<String>) -> KirError {
    KirError::Value(message.into())
}

pub fn check_name(name: &str, what: &str) -> Result<()> {
    let mut chars = name.chars();
    let valid = chars.next().is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
        && !matches!(name, "_" | "True" | "False" | "None");
    if valid {
        Ok(())
    } else {
        Err(invalid(format!("invalid record {what}: {}", str_repr(name))))
    }
}

fn builtin(name: &str) -> bool {
    matches!(name, "bool" | "int" | "float" | "str" | "None" | "list" | "dict")
}

fn type_repr(ty: &TypeExpr) -> String {
    let (kind, name, args): (&str, &str, Vec<&TypeExpr>) = match ty {
        TypeExpr::Any => ("any", "", vec![]),
        TypeExpr::Name(name) => ("name", name, vec![]),
        TypeExpr::Optional(inner) => ("optional", "", vec![inner]),
        TypeExpr::Union(parts) => ("union", "", parts.iter().collect()),
        TypeExpr::Generic(name, parts) => ("generic", name, parts.iter().collect()),
    };
    let contents = args.iter().map(|t| type_repr(t)).collect::<Vec<_>>().join(", ");
    let comma = if args.len() == 1 { "," } else { "" };
    format!("TypeExpr(kind={}, name={}, args=({contents}{comma}))", str_repr(kind), str_repr(name))
}

pub fn validate_type(ty: &TypeExpr) -> Result<()> {
    match ty {
        TypeExpr::Any => {}
        TypeExpr::Name(name) => {
            if !builtin(name) {
                for part in name.split('.') {
                    check_name(part, "type name")?;
                }
            }
        }
        TypeExpr::Optional(inner) => validate_type(inner)?,
        TypeExpr::Union(parts) if parts.len() >= 2 => {
            for part in parts {
                validate_type(part)?;
            }
        }
        TypeExpr::Generic(name, parts)
            if (name == "list" && parts.len() == 1)
                || (name == "dict" && parts.len() == 2 && parts[0] == TypeExpr::name("str")) =>
        {
            for part in parts {
                validate_type(part)?;
            }
        }
        _ => return Err(invalid(format!("unsupported record field type {}", type_repr(ty)))),
    }
    Ok(())
}

/// Normalize programmatically constructed types to lossless signature text.
pub fn normalize_type(ty: &TypeExpr) -> TypeExpr {
    match ty {
        TypeExpr::Optional(inner) => {
            let inner = normalize_type(inner);
            match inner {
                TypeExpr::Any | TypeExpr::Optional(_) => inner,
                TypeExpr::Name(ref name) if name == "None" => inner,
                TypeExpr::Union(mut parts) => {
                    parts.push(TypeExpr::name("None"));
                    normalize_type(&TypeExpr::Union(parts))
                }
                _ => TypeExpr::Optional(Box::new(inner)),
            }
        }
        TypeExpr::Union(parts) => {
            let mut result = Vec::new();
            for part in parts {
                let part = normalize_type(part);
                let flat = match part {
                    TypeExpr::Union(parts) => parts,
                    other => vec![other],
                };
                for part in flat {
                    if !result.contains(&part) {
                        result.push(part);
                    }
                }
            }
            if result.len() == 1 {
                result.pop().unwrap()
            } else {
                TypeExpr::Union(result)
            }
        }
        TypeExpr::Generic(name, parts) => TypeExpr::Generic(name.clone(), parts.iter().map(normalize_type).collect()),
        _ => ty.clone(),
    }
}

/// Validate an owned JSON default. Rust values cannot contain reference cycles;
/// tuples remain distinct from arrays and cannot silently change identity.
pub fn validate_default(value: &Value) -> Result<()> {
    match value {
        Value::Float(f) if !f.is_finite() => {
            return Err(invalid("record defaults must contain only finite JSON numbers"))
        }
        Value::Tuple(_) => return Err(invalid("record defaults must be JSON; nested record defaults are unsupported")),
        Value::List(items) => {
            for item in items {
                validate_default(item)?;
            }
        }
        Value::Dict(pairs) => {
            if pairs.iter().any(|(k, _)| !matches!(k, Value::Str(_))) {
                return Err(invalid("record default object keys must be strings"));
            }
            let mut keys = HashSet::new();
            for (key, value) in pairs {
                let Value::Str(key) = key else { unreachable!("validated string keys") };
                if !keys.insert(key) {
                    return Err(invalid("record default object keys must be distinct"));
                }
                validate_default(value)?;
            }
        }
        _ => {}
    }
    Ok(())
}

/// Portable default identity is type-sensitive, including signed floating zero.
pub(crate) fn default_equal(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::None, Value::None) => true,
        (Value::Bool(a), Value::Bool(b)) => a == b,
        (Value::Int(a), Value::Int(b)) => a == b,
        (Value::Float(a), Value::Float(b)) => a.is_finite() && b.is_finite() && a.to_bits() == b.to_bits(),
        (Value::Str(a), Value::Str(b)) => a == b,
        (Value::List(a), Value::List(b)) => a.len() == b.len() && a.iter().zip(b).all(|(a, b)| default_equal(a, b)),
        (Value::Dict(a), Value::Dict(b)) => {
            let valid_keys = |pairs: &[(Value, Value)]| {
                let mut seen = HashSet::new();
                pairs.iter().all(|(key, _)| match key {
                    Value::Str(key) => seen.insert(key),
                    _ => false,
                })
            };
            valid_keys(a)
                && valid_keys(b)
                && a.len() == b.len()
                && a.iter().all(|(ka, va)| b.iter().any(|(kb, vb)| default_equal(ka, kb) && default_equal(va, vb)))
        }
        _ => false,
    }
}

pub fn default_fits(value: &Value, ty: &TypeExpr) -> bool {
    match ty {
        TypeExpr::Any => true,
        TypeExpr::Optional(inner) => matches!(value, Value::None) || default_fits(value, inner),
        TypeExpr::Union(parts) => parts.iter().any(|part| default_fits(value, part)),
        TypeExpr::Generic(name, parts) if name == "list" && parts.len() == 1 => {
            matches!(value, Value::List(items) if items.iter().all(|v| default_fits(v, &parts[0])))
        }
        TypeExpr::Generic(name, parts) if name == "dict" && parts.len() == 2 => {
            matches!(value, Value::Dict(pairs) if pairs.iter().all(|(k,v)| default_fits(k, &parts[0]) && default_fits(v, &parts[1])))
        }
        TypeExpr::Name(name) => matches!(
            (name.as_str(), value),
            ("bool", Value::Bool(_))
                | ("int", Value::Int(_))
                | ("float", Value::Int(_) | Value::Float(_))
                | ("str", Value::Str(_))
                | ("None", Value::None)
                | ("list", Value::List(_))
                | ("dict", Value::Dict(_))
        ),
        _ => false,
    }
}

/// An immutable field. `None` means missing; `Some(Value::None)` is a null default.
#[derive(Clone, Debug)]
pub struct RecordField {
    name: String,
    ty: TypeExpr,
    default: Option<Value>,
}

impl RecordField {
    pub fn new(name: impl Into<String>, ty: TypeExpr, default: Option<Value>) -> Result<Self> {
        let name = name.into();
        check_name(&name, "field name")?;
        validate_type(&ty)?;
        let ty = normalize_type(&ty);
        if let Some(value) = &default {
            validate_default(value)?;
            if !default_fits(value, &ty) {
                return Err(invalid(format!("default of record field {} does not match its type", str_repr(&name))));
            }
        }
        Ok(Self { name, ty, default })
    }
    pub fn name(&self) -> &str {
        &self.name
    }
    pub fn ty(&self) -> &TypeExpr {
        &self.ty
    }
    pub fn has_default(&self) -> bool {
        self.default.is_some()
    }
    pub fn default(&self) -> Option<&Value> {
        self.default.as_ref()
    }
}

#[derive(Clone, Debug)]
pub struct RecordSchema {
    name: String,
    fields: Vec<RecordField>,
    schema_id: String,
}

impl RecordSchema {
    pub fn new(name: impl Into<String>, fields: Vec<RecordField>) -> Result<Self> {
        let name = name.into();
        check_name(&name, "schema name")?;
        if builtin(&name) {
            return Err(invalid(format!("record name {} conflicts with a built-in type", str_repr(&name))));
        }
        let mut names = HashSet::new();
        if fields.iter().any(|field| !names.insert(field.name())) {
            return Err(invalid(format!("duplicate fields in record {}", str_repr(&name))));
        }
        Ok(Self { name, fields, schema_id: String::new() })
    }
    pub fn name(&self) -> &str {
        &self.name
    }
    pub fn fields(&self) -> &[RecordField] {
        &self.fields
    }
    pub fn schema_id(&self) -> &str {
        &self.schema_id
    }
    pub fn field(&self, name: &str) -> Option<&RecordField> {
        self.fields.iter().find(|f| f.name == name)
    }

    /// Match the reference's immutable schema equality, including field order.
    pub fn same_schema(&self, other: &Self) -> bool {
        self.name == other.name
            && self.schema_id == other.schema_id
            && self.fields.len() == other.fields.len()
            && self.fields.iter().zip(&other.fields).all(|(a, b)| {
                a.name == b.name
                    && a.ty == b.ty
                    && match (&a.default, &b.default) {
                        (None, None) => true,
                        (Some(a), Some(b)) => default_equal(a, b),
                        _ => false,
                    }
            })
    }

    pub fn qualify(&self, library: &str) -> Result<Self> {
        if library.is_empty() {
            return Err(invalid("record library must have a nonempty nominal name"));
        }
        for part in library.split('.') {
            check_name(part, "library name")?;
        }
        let canonical = format!("{library}.{}", self.name);
        if !self.schema_id.is_empty() && self.schema_id != canonical {
            return Err(invalid(format!("record schema identity must be {}", str_repr(&canonical))));
        }
        let fields = self
            .fields
            .iter()
            .map(|f| RecordField::new(&f.name, qualify_type(&f.ty, library), f.default.clone()))
            .collect::<Result<_>>()?;
        Ok(Self { name: self.name.clone(), fields, schema_id: canonical })
    }
}

pub fn qualify_type(ty: &TypeExpr, library: &str) -> TypeExpr {
    match ty {
        TypeExpr::Name(name) if !builtin(name) && !name.contains('.') => TypeExpr::name(&format!("{library}.{name}")),
        TypeExpr::Optional(inner) => TypeExpr::Optional(Box::new(qualify_type(inner, library))),
        TypeExpr::Union(parts) => TypeExpr::Union(parts.iter().map(|t| qualify_type(t, library)).collect()),
        TypeExpr::Generic(name, parts) => {
            TypeExpr::Generic(name.clone(), parts.iter().map(|t| qualify_type(t, library)).collect())
        }
        _ => ty.clone(),
    }
}

pub fn nominal_references(ty: &TypeExpr) -> BTreeSet<String> {
    match ty {
        TypeExpr::Name(name) if !builtin(name) => BTreeSet::from([name.clone()]),
        TypeExpr::Optional(inner) => nominal_references(inner),
        TypeExpr::Generic(_, parts) | TypeExpr::Union(parts) => parts.iter().flat_map(nominal_references).collect(),
        _ => BTreeSet::new(),
    }
}

/// Validate cycles across every supplied schema, including optional/container links.
pub fn validate_record_cycles<'a>(records: impl IntoIterator<Item = &'a RecordSchema>) -> Result<()> {
    let records: Vec<_> = records.into_iter().collect();
    let by_id: BTreeMap<_, _> = records.iter().map(|schema| (schema.schema_id(), *schema)).collect();
    fn visit(
        id: &str,
        by_id: &BTreeMap<&str, &RecordSchema>,
        active: &mut HashSet<String>,
        done: &mut HashSet<String>,
    ) -> Result<()> {
        if active.contains(id) {
            return Err(invalid(format!("recursive record schema {}", str_repr(id))));
        }
        if done.contains(id) {
            return Ok(());
        }
        let Some(schema) = by_id.get(id) else { return Ok(()) };
        active.insert(id.into());
        for field in schema.fields() {
            for reference in nominal_references(field.ty()) {
                visit(&reference, by_id, active, done)?;
            }
        }
        active.remove(id);
        done.insert(id.into());
        Ok(())
    }
    let (mut active, mut done) = (HashSet::new(), HashSet::new());
    for schema in records {
        visit(schema.schema_id(), &by_id, &mut active, &mut done)?;
    }
    Ok(())
}

pub fn generated_names(schema: &RecordSchema) -> Vec<String> {
    let mut names = vec![format!("{}.make", schema.name)];
    for field in &schema.fields {
        for kind in ["get", "with"] {
            names.push(format!("{}.{kind}.{}", schema.name, field.name));
        }
    }
    names
}

pub fn record_signatures(schema: &RecordSchema) -> Vec<Signature> {
    let nominal = TypeExpr::name(&schema.schema_id);
    let mut signatures = vec![Signature::new(
        format!("{}.make", schema.name),
        schema
            .fields
            .iter()
            .map(|field| Port { name: field.name.clone(), ty: field.ty.clone(), default: field.default.clone() })
            .collect(),
        vec![Port::new("record", nominal.clone())],
    )];
    for field in &schema.fields {
        signatures.push(Signature::new(
            format!("{}.get.{}", schema.name, field.name),
            vec![Port::new("record", nominal.clone())],
            vec![Port::new("value", field.ty.clone())],
        ));
        signatures.push(Signature::new(
            format!("{}.with.{}", schema.name, field.name),
            vec![Port::new("record", nominal.clone()), Port::new("value", field.ty.clone())],
            vec![Port::new("record", nominal.clone())],
        ));
    }
    signatures
}
