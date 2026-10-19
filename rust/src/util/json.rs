//! JSON with Python's `json` semantics: arbitrary-precision integers,
//! `NaN`/`Infinity`, objects as ordered pairs (a repeated key keeps its first
//! position and takes the last value), and `json.dumps(..., ensure_ascii=False)`
//! output, compact or indented.

use num_bigint::BigInt;

use crate::util::pyfmt::{float_repr, json_str};

#[derive(Clone, Debug, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    Int(BigInt),
    Float(f64),
    Str(String),
    Array(Vec<Json>),
    Object(Vec<(String, Json)>),
}

impl Json {
    pub fn str(s: impl Into<String>) -> Json {
        Json::Str(s.into())
    }

    pub fn int(n: i64) -> Json {
        Json::Int(BigInt::from(n))
    }

    pub fn strs<S: AsRef<str>>(items: &[S]) -> Json {
        Json::Array(items.iter().map(|s| Json::str(s.as_ref())).collect())
    }

    pub fn opt_str(s: Option<&str>) -> Json {
        s.map_or(Json::Null, Json::str)
    }

    /// The value under `key` of an object.
    pub fn get(&self, key: &str) -> Option<&Json> {
        match self {
            Json::Object(pairs) => pairs.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn get_mut(&mut self, key: &str) -> Option<&mut Json> {
        match self {
            Json::Object(pairs) => pairs.iter_mut().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn contains_key(&self, key: &str) -> bool {
        self.get(key).is_some()
    }

    /// Set `key` on an object: replace in place, or append.
    pub fn insert(&mut self, key: &str, value: Json) {
        if let Json::Object(pairs) = self {
            match pairs.iter_mut().find(|(k, _)| k == key) {
                Some((_, v)) => *v = value,
                None => pairs.push((key.to_string(), value)),
            }
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_array(&self) -> Option<&Vec<Json>> {
        match self {
            Json::Array(a) => Some(a),
            _ => None,
        }
    }

    pub fn as_object(&self) -> Option<&Vec<(String, Json)>> {
        match self {
            Json::Object(o) => Some(o),
            _ => None,
        }
    }

    pub fn is_null(&self) -> bool {
        matches!(self, Json::Null)
    }

    /// Python truthiness of the decoded value.
    pub fn truthy(&self) -> bool {
        match self {
            Json::Null => false,
            Json::Bool(b) => *b,
            Json::Int(n) => n != &BigInt::from(0),
            Json::Float(f) => *f != 0.0,
            Json::Str(s) => !s.is_empty(),
            Json::Array(a) => !a.is_empty(),
            Json::Object(o) => !o.is_empty(),
        }
    }

    /// `json.dumps(self, ensure_ascii=False)`.
    pub fn dumps(&self) -> String {
        let mut out = String::new();
        write_value(self, None, 0, &mut out);
        out
    }

    /// `json.dumps(self, indent=indent, ensure_ascii=False)`.
    pub fn dumps_indent(&self, indent: usize) -> String {
        let mut out = String::new();
        write_value(self, Some(indent), 0, &mut out);
        out
    }
}

fn write_value(v: &Json, indent: Option<usize>, depth: usize, out: &mut String) {
    match v {
        Json::Null => out.push_str("null"),
        Json::Bool(true) => out.push_str("true"),
        Json::Bool(false) => out.push_str("false"),
        Json::Int(n) => out.push_str(&n.to_string()),
        Json::Float(f) => out.push_str(&float_text(*f)),
        Json::Str(s) => out.push_str(&json_str(s)),
        Json::Array(items) => {
            if items.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                separator(i, indent, depth + 1, out);
                write_value(item, indent, depth + 1, out);
            }
            close(indent, depth, out);
            out.push(']');
        }
        Json::Object(pairs) => {
            if pairs.is_empty() {
                out.push_str("{}");
                return;
            }
            out.push('{');
            for (i, (k, item)) in pairs.iter().enumerate() {
                separator(i, indent, depth + 1, out);
                out.push_str(&json_str(k));
                out.push_str(": ");
                write_value(item, indent, depth + 1, out);
            }
            close(indent, depth, out);
            out.push('}');
        }
    }
}

fn separator(i: usize, indent: Option<usize>, depth: usize, out: &mut String) {
    match indent {
        Some(n) => {
            if i > 0 {
                out.push(',');
            }
            out.push('\n');
            out.push_str(&" ".repeat(n * depth));
        }
        None => {
            if i > 0 {
                out.push_str(", ");
            }
        }
    }
}

fn close(indent: Option<usize>, depth: usize, out: &mut String) {
    if let Some(n) = indent {
        out.push('\n');
        out.push_str(&" ".repeat(n * depth));
    }
}

/// A float as `json.dumps` writes it.
pub fn float_text(f: f64) -> String {
    if f.is_nan() {
        "NaN".to_string()
    } else if f.is_infinite() {
        if f > 0.0 { "Infinity" } else { "-Infinity" }.to_string()
    } else {
        float_repr(f)
    }
}

/// `json.loads(text)`.
pub fn loads(text: &str) -> Result<Json, String> {
    let mut p = Reader { s: text.as_bytes(), text, i: 0 };
    p.ws();
    let v = p.value()?;
    p.ws();
    if p.i != p.s.len() {
        return Err(p.err("Extra data"));
    }
    Ok(v)
}

struct Reader<'a> {
    s: &'a [u8],
    text: &'a str,
    i: usize,
}

impl Reader<'_> {
    fn err(&self, what: &str) -> String {
        self.err_at(what, self.i)
    }

    /// `json.JSONDecodeError` text: `msg: line L column C (char N)`.
    fn err_at(&self, what: &str, pos: usize) -> String {
        let before = &self.text[..pos];
        let line = before.matches('\n').count() + 1;
        let col = before.rsplit('\n').next().unwrap_or("").chars().count() + 1;
        format!("{what}: line {line} column {col} (char {})", before.chars().count())
    }

    fn ws(&mut self) {
        while self.i < self.s.len() && matches!(self.s[self.i], b' ' | b'\t' | b'\n' | b'\r') {
            self.i += 1;
        }
    }

    fn eat(&mut self, lit: &str) -> bool {
        if self.s[self.i..].starts_with(lit.as_bytes()) {
            self.i += lit.len();
            true
        } else {
            false
        }
    }

    fn value(&mut self) -> Result<Json, String> {
        let Some(&c) = self.s.get(self.i) else {
            return Err(self.err("Expecting value"));
        };
        match c {
            b'{' => self.object(),
            b'[' => self.array(),
            b'"' => Ok(Json::Str(self.string()?)),
            b'n' if self.eat("null") => Ok(Json::Null),
            b't' if self.eat("true") => Ok(Json::Bool(true)),
            b'f' if self.eat("false") => Ok(Json::Bool(false)),
            b'N' if self.eat("NaN") => Ok(Json::Float(f64::NAN)),
            b'I' if self.eat("Infinity") => Ok(Json::Float(f64::INFINITY)),
            b'-' if self.eat("-Infinity") => Ok(Json::Float(f64::NEG_INFINITY)),
            b'-' | b'0'..=b'9' => self.number(),
            _ => Err(self.err("Expecting value")),
        }
    }

    fn number(&mut self) -> Result<Json, String> {
        let start = self.i;
        let digits = |r: &mut Self| {
            let s = r.i;
            while r.i < r.s.len() && r.s[r.i].is_ascii_digit() {
                r.i += 1;
            }
            r.i - s
        };
        self.eat("-");
        if !self.eat("0") && digits(self) == 0 {
            self.i = start;
            return Err(self.err("Expecting value"));
        }
        let mut is_float = false;
        if self.s.get(self.i) == Some(&b'.') {
            let save = self.i;
            self.i += 1;
            if digits(self) == 0 {
                self.i = save;
            } else {
                is_float = true;
            }
        }
        if matches!(self.s.get(self.i), Some(b'e' | b'E')) {
            let save = self.i;
            self.i += 1;
            if matches!(self.s.get(self.i), Some(b'+' | b'-')) {
                self.i += 1;
            }
            if digits(self) == 0 {
                self.i = save;
            } else {
                is_float = true;
            }
        }
        let text = &self.text[start..self.i];
        if is_float {
            Ok(Json::Float(text.parse().map_err(|_| self.err("Bad number"))?))
        } else {
            Ok(Json::Int(text.parse().map_err(|_| self.err("Bad number"))?))
        }
    }

    fn string(&mut self) -> Result<String, String> {
        let start = self.i;
        self.i += 1;
        let mut out = String::new();
        loop {
            let Some(&c) = self.s.get(self.i) else {
                return Err(self.err_at("Unterminated string starting at", start));
            };
            match c {
                b'"' => {
                    self.i += 1;
                    return Ok(out);
                }
                b'\\' => {
                    self.i += 1;
                    let Some(&e) = self.s.get(self.i) else {
                        return Err(self.err_at("Unterminated string starting at", start));
                    };
                    self.i += 1;
                    match e {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{08}'),
                        b'f' => out.push('\u{0c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let hi = self.hex4()?;
                            let code = if (0xd800..0xdc00).contains(&hi) && self.s[self.i..].starts_with(b"\\u") {
                                let save = self.i;
                                self.i += 2;
                                let lo = self.hex4()?;
                                if (0xdc00..0xe000).contains(&lo) {
                                    0x10000 + ((hi - 0xd800) << 10) + (lo - 0xdc00)
                                } else {
                                    self.i = save;
                                    hi
                                }
                            } else {
                                hi
                            };
                            out.push(
                                char::from_u32(code)
                                    .ok_or_else(|| self.err("Lone surrogate escape (not representable)"))?,
                            );
                        }
                        _ => return Err(self.err("Invalid \\escape")),
                    }
                }
                c if c < 0x20 => return Err(self.err("Invalid control character at")),
                _ => {
                    let ch = self.text[self.i..].chars().next().expect("in bounds");
                    out.push(ch);
                    self.i += ch.len_utf8();
                }
            }
        }
    }

    fn hex4(&mut self) -> Result<u32, String> {
        let h = self
            .text
            .get(self.i..self.i + 4)
            .filter(|h| h.bytes().all(|b| b.is_ascii_hexdigit()))
            .ok_or_else(|| self.err("Invalid \\uXXXX escape"))?;
        self.i += 4;
        Ok(u32::from_str_radix(h, 16).expect("checked hex"))
    }

    fn array(&mut self) -> Result<Json, String> {
        self.i += 1;
        let mut items = Vec::new();
        self.ws();
        if self.eat("]") {
            return Ok(Json::Array(items));
        }
        loop {
            self.ws();
            items.push(self.value()?);
            self.ws();
            if self.eat("]") {
                return Ok(Json::Array(items));
            }
            let comma = self.i;
            if !self.eat(",") {
                return Err(self.err("Expecting ',' delimiter"));
            }
            self.ws();
            if self.s.get(self.i) == Some(&b']') {
                return Err(self.err_at("Illegal trailing comma before end of array", comma));
            }
        }
    }

    fn object(&mut self) -> Result<Json, String> {
        self.i += 1;
        let mut obj = Json::Object(Vec::new());
        self.ws();
        if self.eat("}") {
            return Ok(obj);
        }
        loop {
            self.ws();
            if self.s.get(self.i) != Some(&b'"') {
                return Err(self.err("Expecting property name enclosed in double quotes"));
            }
            let key = self.string()?;
            self.ws();
            if !self.eat(":") {
                return Err(self.err("Expecting ':' delimiter"));
            }
            self.ws();
            let v = self.value()?;
            obj.insert(&key, v);
            self.ws();
            if self.eat("}") {
                return Ok(obj);
            }
            let comma = self.i;
            if !self.eat(",") {
                return Err(self.err("Expecting ',' delimiter"));
            }
            self.ws();
            if self.s.get(self.i) == Some(&b'}') {
                return Err(self.err_at("Illegal trailing comma before end of object", comma));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_python_layout() {
        let text = r#"{"a": [1, 2.5, {"b": null}], "c": {}, "d": [], "e": "é\n", "a": true}"#;
        let v = loads(text).unwrap();
        assert_eq!(v.dumps(), "{\"a\": true, \"c\": {}, \"d\": [], \"e\": \"é\\n\"}");
        assert_eq!(loads("[1, [2]]").unwrap().dumps_indent(2), "[\n  1,\n  [\n    2\n  ]\n]");
        assert_eq!(loads("1e5").unwrap(), Json::Float(100000.0));
        assert_eq!(loads("123456789012345678901234567890").unwrap().dumps(), "123456789012345678901234567890");
    }
}
