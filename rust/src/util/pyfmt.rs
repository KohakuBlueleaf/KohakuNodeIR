//! Python-compatible text forms: `repr(float)`, `repr(str)` and the string
//! escaping of `json.dumps(s, ensure_ascii=False)`.

use std::fmt::Write;

/// `repr(x)` of a Python float: the shortest round-trip digits, positional
/// for decimal exponents in `[-4, 16)`, scientific (`1e-05`, `1.5e+16`) otherwise.
pub fn float_repr(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf" } else { "-inf" }.to_string();
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0" } else { "0.0" }.to_string();
    }
    let sci = format!("{:e}", x.abs());
    let (mantissa, exp) = sci.split_once('e').expect("LowerExp always has an exponent");
    let exp: i32 = exp.parse().expect("LowerExp exponent is an integer");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let decpt = exp + 1;
    let mut out = String::new();
    if x < 0.0 {
        out.push('-');
    }
    if -4 < decpt && decpt <= 16 {
        if decpt <= 0 {
            out.push_str("0.");
            out.push_str(&"0".repeat((-decpt) as usize));
            out.push_str(&digits);
        } else {
            let d = decpt as usize;
            if d >= digits.len() {
                out.push_str(&digits);
                out.push_str(&"0".repeat(d - digits.len()));
                out.push_str(".0");
            } else {
                out.push_str(&digits[..d]);
                out.push('.');
                out.push_str(&digits[d..]);
            }
        }
    } else {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        let _ = write!(out, "e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs());
    }
    out
}

/// `repr(s)` of a Python string.
pub fn str_repr(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if is_printable(c) => out.push(c),
            c => {
                let n = c as u32;
                if n < 0x100 {
                    let _ = write!(out, "\\x{n:02x}");
                } else if n < 0x10000 {
                    let _ = write!(out, "\\u{n:04x}");
                } else {
                    let _ = write!(out, "\\U{n:08x}");
                }
            }
        }
    }
    out.push(quote);
    out
}

/// `str.isprintable()` for one character: false for control, format,
/// private-use, line/paragraph separators and non-ASCII spaces.
pub fn is_printable(c: char) -> bool {
    let n = c as u32;
    if n < 0x20 || (0x7f..0xa0).contains(&n) {
        return false;
    }
    if n < 0x7f {
        return true;
    }
    const NOT_PRINTABLE: &[(u32, u32)] = &[
        (0x00a0, 0x00a0),
        (0x00ad, 0x00ad),
        (0x0600, 0x0605),
        (0x061c, 0x061c),
        (0x06dd, 0x06dd),
        (0x070f, 0x070f),
        (0x0890, 0x0891),
        (0x08e2, 0x08e2),
        (0x1680, 0x1680),
        (0x180e, 0x180e),
        (0x2000, 0x200f),
        (0x2028, 0x202f),
        (0x205f, 0x2064),
        (0x2066, 0x206f),
        (0x3000, 0x3000),
        (0xd800, 0xf8ff),
        (0xfeff, 0xfeff),
        (0xfff9, 0xfffb),
        (0x110bd, 0x110bd),
        (0x110cd, 0x110cd),
        (0x13430, 0x1343f),
        (0x1bca0, 0x1bca3),
        (0x1d173, 0x1d17a),
        (0xe0001, 0xe0001),
        (0xe0020, 0xe007f),
        (0xf0000, 0x10ffff),
    ];
    !NOT_PRINTABLE.iter().any(|&(lo, hi)| lo <= n && n <= hi)
}

/// `json.dumps(s, ensure_ascii=False)` of a string, quotes included.
pub fn json_str(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

/// `str(pathlib.Path(p))`: separators normalized for the platform, empty and
/// `.` parts dropped, no trailing separator, `.` for an empty path.
pub fn path_str(p: &str) -> String {
    let (sep, text) = if cfg!(windows) { ('\\', p.replace('/', "\\")) } else { ('/', p.to_string()) };
    let mut head = String::new();
    let mut rest = text.as_str();
    if cfg!(windows) && rest.len() >= 2 && rest.as_bytes()[1] == b':' && rest.as_bytes()[0].is_ascii_alphabetic() {
        head.push_str(&rest[..2]);
        rest = &rest[2..];
    }
    let unc = rest.starts_with(&format!("{sep}{sep}")) && !rest.starts_with(&format!("{sep}{sep}{sep}"));
    if unc && (cfg!(windows) || head.is_empty()) {
        head.push(sep);
        head.push(sep);
    } else if rest.starts_with(sep) {
        head.push(sep);
    }
    let parts: Vec<&str> = rest.split(sep).filter(|s| !s.is_empty() && *s != ".").collect();
    let out = head + &parts.join(&sep.to_string());
    if out.is_empty() {
        ".".to_string()
    } else {
        out
    }
}

/// Python list repr of strings: `['a', 'b']`.
pub fn str_list_repr<S: AsRef<str>>(items: &[S]) -> String {
    let parts: Vec<String> = items.iter().map(|s| str_repr(s.as_ref())).collect();
    format!("[{}]", parts.join(", "))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn floats_like_python() {
        let cases = [
            (1e-5, "1e-05"),
            (0.1, "0.1"),
            (1.0, "1.0"),
            (1e16, "1e+16"),
            (1e15, "1000000000000000.0"),
            (0.0001, "0.0001"),
            (1.5e-7, "1.5e-07"),
            (-2.5, "-2.5"),
            (123456789.125, "123456789.125"),
            (1e100, "1e+100"),
            (5e-324, "5e-324"),
            (1.7976931348623157e308, "1.7976931348623157e+308"),
            (-0.0, "-0.0"),
        ];
        for (x, want) in cases {
            assert_eq!(float_repr(x), want);
        }
    }

    #[test]
    fn strings_like_python() {
        assert_eq!(str_repr("a"), "'a'");
        assert_eq!(str_repr("it's"), "\"it's\"");
        assert_eq!(str_repr("a'\""), "'a\\'\"'");
        assert_eq!(str_repr("\u{7}\u{a0}é"), "'\\x07\\xa0é'");
        assert_eq!(json_str("a\"\\\n\u{1}é"), "\"a\\\"\\\\\\n\\u0001é\"");
    }

    #[cfg(windows)]
    #[test]
    fn paths_like_pathlib() {
        let cases = [
            ("a/./b/", "a\\b"),
            ("C:/x//y/", "C:\\x\\y"),
            ("/x", "\\x"),
            ("//srv/share/a", "\\\\srv\\share\\a"),
            ("C:", "C:"),
            ("", "."),
            ("a/../b", "a\\..\\b"),
            ("x/.", "x"),
            ("./a", "a"),
        ];
        for (p, want) in cases {
            assert_eq!(path_str(p), want);
        }
    }
}
