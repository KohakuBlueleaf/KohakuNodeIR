//! Literal values with Python semantics: `1 == 1.0 == True` as dict keys,
//! unhashable lists and dicts, `repr`/`str`, and the `json` encoding.

use num_bigint::BigInt;
use num_traits::FromPrimitive;

use crate::util::json::{float_text, Json};
use crate::util::pyfmt::{float_repr, str_repr};

#[derive(Clone, Debug)]
pub enum Value {
    None,
    Bool(bool),
    Int(BigInt),
    Float(f64),
    Str(String),
    List(Vec<Value>),
    Tuple(Vec<Value>),
    /// Insertion-ordered pairs with distinct keys.
    Dict(Vec<(Value, Value)>),
}

enum Num<'a> {
    Int(std::borrow::Cow<'a, BigInt>),
    Float(f64),
}

impl Value {
    pub fn str(s: impl Into<String>) -> Value {
        Value::Str(s.into())
    }

    pub fn int(n: i64) -> Value {
        Value::Int(BigInt::from(n))
    }

    /// Python's `type(v).__name__`.
    pub fn type_name(&self) -> &'static str {
        match self {
            Value::None => "NoneType",
            Value::Bool(_) => "bool",
            Value::Int(_) => "int",
            Value::Float(_) => "float",
            Value::Str(_) => "str",
            Value::List(_) => "list",
            Value::Tuple(_) => "tuple",
            Value::Dict(_) => "dict",
        }
    }

    /// The name of the first unhashable type inside, if any.
    pub fn unhashable(&self) -> Option<&'static str> {
        match self {
            Value::List(_) | Value::Dict(_) => Some(self.type_name()),
            Value::Tuple(items) => items.iter().find_map(Value::unhashable),
            _ => None,
        }
    }

    fn num(&self) -> Option<Num<'_>> {
        match self {
            Value::Bool(b) => Some(Num::Int(std::borrow::Cow::Owned(BigInt::from(*b as u8)))),
            Value::Int(n) => Some(Num::Int(std::borrow::Cow::Borrowed(n))),
            Value::Float(f) => Some(Num::Float(*f)),
            _ => None,
        }
    }

    /// Python `==`.
    pub fn py_eq(&self, other: &Value) -> bool {
        if let (Some(a), Some(b)) = (self.num(), other.num()) {
            return match (a, b) {
                (Num::Int(a), Num::Int(b)) => a == b,
                (Num::Float(a), Num::Float(b)) => a == b,
                (Num::Int(i), Num::Float(f)) | (Num::Float(f), Num::Int(i)) => {
                    f.is_finite() && f.fract() == 0.0 && BigInt::from_f64(f).as_ref() == Some(&*i)
                }
            };
        }
        match (self, other) {
            (Value::None, Value::None) => true,
            (Value::Str(a), Value::Str(b)) => a == b,
            (Value::List(a), Value::List(b)) | (Value::Tuple(a), Value::Tuple(b)) => {
                a.len() == b.len() && a.iter().zip(b).all(|(x, y)| x.py_eq(y))
            }
            (Value::Dict(a), Value::Dict(b)) => {
                a.len() == b.len() && a.iter().all(|(k, v)| b.iter().any(|(k2, v2)| k.py_eq(k2) && v.py_eq(v2)))
            }
            _ => false,
        }
    }

    /// `d[key] = value` on a Python dict.
    pub fn dict_set(pairs: &mut Vec<(Value, Value)>, key: Value, value: Value) -> Result<(), String> {
        if let Some(t) = key.unhashable() {
            return Err(format!("unhashable type: '{t}'"));
        }
        match pairs.iter_mut().find(|(k, _)| k.py_eq(&key)) {
            Some(slot) => slot.1 = value,
            None => pairs.push((key, value)),
        }
        Ok(())
    }

    /// Python `repr`.
    pub fn repr(&self) -> String {
        match self {
            Value::None => "None".to_string(),
            Value::Bool(true) => "True".to_string(),
            Value::Bool(false) => "False".to_string(),
            Value::Int(n) => n.to_string(),
            Value::Float(f) => float_repr(*f),
            Value::Str(s) => str_repr(s),
            Value::List(items) => format!("[{}]", join_repr(items)),
            Value::Tuple(items) if items.len() == 1 => format!("({},)", items[0].repr()),
            Value::Tuple(items) => format!("({})", join_repr(items)),
            Value::Dict(pairs) => {
                let parts: Vec<String> = pairs.iter().map(|(k, v)| format!("{}: {}", k.repr(), v.repr())).collect();
                format!("{{{}}}", parts.join(", "))
            }
        }
    }

    /// Python `str`.
    pub fn py_str(&self) -> String {
        match self {
            Value::Str(s) => s.clone(),
            v => v.repr(),
        }
    }

    /// The JSON `json.dumps` writes for this value (tuples as arrays, dict keys as strings).
    pub fn to_json(&self) -> Result<Json, String> {
        Ok(match self {
            Value::None => Json::Null,
            Value::Bool(b) => Json::Bool(*b),
            Value::Int(n) => Json::Int(n.clone()),
            Value::Float(f) => Json::Float(*f),
            Value::Str(s) => Json::Str(s.clone()),
            Value::List(items) | Value::Tuple(items) => {
                Json::Array(items.iter().map(Value::to_json).collect::<Result<_, _>>()?)
            }
            Value::Dict(pairs) => {
                let mut out = Vec::with_capacity(pairs.len());
                for (k, v) in pairs {
                    let key = match k {
                        Value::Str(s) => s.clone(),
                        Value::Float(f) => float_text(*f),
                        Value::Bool(true) => "true".to_string(),
                        Value::Bool(false) => "false".to_string(),
                        Value::None => "null".to_string(),
                        Value::Int(n) => n.to_string(),
                        other => {
                            return Err(format!(
                                "keys must be str, int, float, bool or None, not {}",
                                other.type_name()
                            ))
                        }
                    };
                    out.push((key, v.to_json()?));
                }
                Json::Object(out)
            }
        })
    }

    /// The Python object `json.loads` gives for this JSON.
    pub fn from_json(j: &Json) -> Value {
        match j {
            Json::Null => Value::None,
            Json::Bool(b) => Value::Bool(*b),
            Json::Int(n) => Value::Int(n.clone()),
            Json::Float(f) => Value::Float(*f),
            Json::Str(s) => Value::Str(s.clone()),
            Json::Array(items) => Value::List(items.iter().map(Value::from_json).collect()),
            Json::Object(pairs) => {
                Value::Dict(pairs.iter().map(|(k, v)| (Value::Str(k.clone()), Value::from_json(v))).collect())
            }
        }
    }
}

fn join_repr(items: &[Value]) -> String {
    items.iter().map(Value::repr).collect::<Vec<_>>().join(", ")
}
