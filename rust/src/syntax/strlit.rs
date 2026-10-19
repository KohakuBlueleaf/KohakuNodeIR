//! Decoding of STRING tokens with `ast.literal_eval` semantics: newline
//! translation of the source (`\r\n` and `\r` become `\n`), backslash-newline
//! continuation, and Python's escape sequences.

#[cfg(feature = "unicode-names")]
use crate::syntax::unicode_names::{ALIASES, NAMED};

/// The value of a quoted STRING token.
pub fn decode(token: &str) -> Result<String, String> {
    if token.contains('\0') {
        return Err("source code string cannot contain null bytes".into());
    }
    let text = token.replace("\r\n", "\n").replace('\r', "\n");
    let triple = text.starts_with("\"\"\"") || text.starts_with("'''");
    let q = if triple { 3 } else { 1 };
    let body: Vec<char> = text[q..text.len() - q].chars().collect();
    // Python's tokenizer reads the literal again: its escapes may hide the
    // closing quote the lexer saw, and a newline ends a one-line string.
    let mut i = 0;
    while i < body.len() {
        match body[i] {
            '\\' => i += 2,
            '\n' if !triple => {
                return Err("unterminated string literal (detected at line 1) (<unknown>, line 1)".into());
            }
            _ => i += 1,
        }
    }
    if i > body.len() {
        let line = text.matches('\n').count() + 1;
        let kind = if triple { "triple-quoted string literal" } else { "string literal" };
        return Err(format!("unterminated {kind} (detected at line {line}) (<unknown>, line 1)"));
    }
    // Positions in the bytes the reference's escape decoder sees: it writes
    // every non-ASCII character as a 10-byte escape, and a backslash before
    // one as a 6-byte escape.
    let mut offsets = Vec::with_capacity(body.len() + 1);
    let mut off = 0;
    for (k, &c) in body.iter().enumerate() {
        offsets.push(off);
        off += match c {
            '\\' if body.get(k + 1).is_some_and(|n| !n.is_ascii()) => 6,
            c if c.is_ascii() => 1,
            _ => 10,
        };
    }
    offsets.push(off);
    let unicode_error = |start: usize, end: usize, reason: &str| {
        format!(
            "(unicode error) 'unicodeescape' codec can't decode bytes in position {}-{}: {reason} (<unknown>, line 1)",
            offsets[start],
            offsets[end] - 1
        )
    };
    let mut out = String::with_capacity(body.len());
    let mut chars = body.iter().copied().enumerate().peekable();
    while let Some((at, c)) = chars.next() {
        if c == '\n' && !triple {
            return Err("unterminated string literal (detected at line 1) (<unknown>, line 1)".into());
        }
        if c != '\\' {
            out.push(c);
            continue;
        }
        let Some((_, e)) = chars.next() else {
            return Err("unterminated string literal (detected at line 1) (<unknown>, line 1)".into());
        };
        match e {
            '\n' => {}
            '\\' => out.push('\\'),
            '\'' => out.push('\''),
            '"' => out.push('"'),
            'a' => out.push('\u{07}'),
            'b' => out.push('\u{08}'),
            'f' => out.push('\u{0c}'),
            'n' => out.push('\n'),
            'r' => out.push('\r'),
            't' => out.push('\t'),
            'v' => out.push('\u{0b}'),
            '0'..='7' => {
                let mut n = e.to_digit(8).expect("octal digit");
                for _ in 0..2 {
                    match chars.peek().and_then(|(_, c)| c.to_digit(8)) {
                        Some(d) => {
                            n = n * 8 + d;
                            chars.next();
                        }
                        None => break,
                    }
                }
                out.push(char::from_u32(n).expect("octal escapes stay below 0o777"));
            }
            'x' | 'u' | 'U' => {
                let width = match e {
                    'x' => 2,
                    'u' => 4,
                    _ => 8,
                };
                let mut n: u32 = 0;
                let mut last = at + 1;
                for _ in 0..width {
                    match chars.peek().and_then(|&(k, c)| c.to_digit(16).map(|d| (k, d))) {
                        Some((k, d)) => {
                            n = n * 16 + d;
                            last = k;
                            chars.next();
                        }
                        None => {
                            let reason = format!("truncated \\{e}{} escape", "X".repeat(width));
                            return Err(unicode_error(at, last + 1, &reason));
                        }
                    }
                }
                match char::from_u32(n) {
                    Some(ch) => out.push(ch),
                    None if (0xd800..0xe000).contains(&n) => {
                        return Err(format!("lone surrogate \\{e}{n:x} is not representable"))
                    }
                    None => return Err(unicode_error(at, last + 1, "illegal Unicode character")),
                }
            }
            'N' => {
                let malformed = |end: usize| unicode_error(at, end, "malformed \\N character escape");
                match chars.peek() {
                    Some(&(_, '{')) => {
                        chars.next();
                    }
                    Some(&(k, _)) => return Err(malformed(k)),
                    None => return Err(malformed(body.len())),
                }
                let mut name = String::new();
                loop {
                    match chars.next() {
                        Some((k, '}')) if name.is_empty() => return Err(malformed(k)),
                        Some((k, '}')) => match named_char(&name) {
                            Some(c) => break out.push(c),
                            None => return Err(unicode_error(at, k + 1, "unknown Unicode character name")),
                        },
                        Some((_, c)) => name.push(c),
                        None => return Err(malformed(body.len())),
                    }
                }
            }
            other => {
                out.push('\\');
                out.push(other);
            }
        }
    }
    Ok(out)
}

/// Python's `\N{name}` lookup: an exact name or alias of its Unicode version,
/// ASCII case-insensitive. The name table's own lookup is loose (it ignores
/// spaces, `_` and medial `-`), so a match counts only when spelled exactly.
#[cfg(feature = "unicode-names")]
fn named_char(name: &str) -> Option<char> {
    let upper = name.to_ascii_uppercase();
    if let Ok(k) = ALIASES.binary_search_by(|(alias, _)| alias.cmp(&upper.as_str())) {
        return char::from_u32(ALIASES[k].1);
    }
    let c = unicode_names2::character(&upper)?;
    let named = NAMED.binary_search_by(|&(lo, hi)| {
        if hi < c as u32 {
            std::cmp::Ordering::Less
        } else if lo > c as u32 {
            std::cmp::Ordering::Greater
        } else {
            std::cmp::Ordering::Equal
        }
    });
    (named.is_ok() && unicode_names2::name(c)?.to_string() == upper).then_some(c)
}

#[cfg(not(feature = "unicode-names"))]
fn named_char(_name: &str) -> Option<char> {
    None
}

/// The byte length of the STRING token at the start of `s`, trying the
/// lexer's four forms in order: `"""`, `'''`, `"`, `'`.
pub fn token_len(s: &str) -> Option<usize> {
    triple_double(s).or_else(|| triple_single(s)).or_else(|| single(s, b'"')).or_else(|| single(s, b'\''))
}

/// `"""(\\[\s\S]|[^"]|"(?!""))*"""` with backtracking, as the reference's
/// lexer compiles it: a backslash may also stand alone, so the match is the
/// first one a greedy left-to-right search finds.
fn triple_double(s: &str) -> Option<usize> {
    let b = s.as_bytes();
    if !b.starts_with(b"\"\"\"") {
        return None;
    }
    let fence = |i: usize| b[i..].starts_with(b"\"\"\"");
    // end[i]: where a match continuing at byte i ends.
    let mut end: Vec<Option<usize>> = vec![None; b.len() + 2];
    for i in (3..=b.len()).rev() {
        if i == b.len() || !s.is_char_boundary(i) {
            continue;
        }
        let next = i + char_len(&s[i..]);
        let mut found = None;
        if b[i] == b'\\' && next < b.len() {
            found = end[next + char_len(&s[next..])];
        }
        if found.is_none() && b[i] != b'"' {
            found = end[next];
        }
        if found.is_none() && b[i] == b'"' && !b[i + 1..].starts_with(b"\"\"") {
            found = end[next];
        }
        if found.is_none() && fence(i) {
            found = Some(i + 3);
        }
        end[i] = found;
    }
    end[3]
}

/// `'''(\\[\s\S]|[^\\']|'(?!''))*'''`: a backslash always escapes.
fn triple_single(s: &str) -> Option<usize> {
    let b = s.as_bytes();
    if !b.starts_with(b"'''") {
        return None;
    }
    let mut i = 3;
    loop {
        match b.get(i) {
            None => return None,
            Some(b'\\') if i + 1 < b.len() => i += 1 + char_len(&s[i + 1..]),
            Some(b'\\') => return None,
            Some(b'\'') => {
                if b[i..].starts_with(b"'''") {
                    return Some(i + 3);
                }
                i += 1;
            }
            Some(_) => i += char_len(&s[i..]),
        }
    }
}

fn single(s: &str, q: u8) -> Option<usize> {
    let b = s.as_bytes();
    if b.first() != Some(&q) {
        return None;
    }
    let mut i = 1;
    loop {
        match b.get(i) {
            None | Some(b'\n') => return None,
            Some(b'\\') => match b.get(i + 1) {
                None | Some(b'\n') => return None,
                Some(_) => i += 1 + char_len(&s[i + 1..]),
            },
            Some(&c) if c == q => return Some(i + 1),
            Some(_) => i += char_len(&s[i..]),
        }
    }
}

fn char_len(s: &str) -> usize {
    s.chars().next().map_or(1, char::len_utf8)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn escapes() {
        assert_eq!(decode(r#""a\nb""#).unwrap(), "a\nb");
        assert_eq!(decode(r#"'\d'"#).unwrap(), "\\d");
        assert_eq!(decode(r#""\x41\101é\U0001F600""#).unwrap(), "AA\u{e9}\u{1F600}");
        assert_eq!(decode("'''a\r\nb'''").unwrap(), "a\nb");
        assert!(decode(r#""\x4""#).is_err());
        assert!(decode("'a\rb'").is_err());
    }

    #[cfg(feature = "unicode-names")]
    #[test]
    fn named_escapes() {
        assert_eq!(
            decode(r#""\N{bullet}\N{BYTE ORDER MARK}\N{HANGUL SYLLABLE GA}""#).unwrap(),
            "\u{2022}\u{feff}\u{ac00}"
        );
        assert!(decode(r#""\N{NO BREAK SPACE}""#).is_err());
        assert!(decode(r#""\N{SPACE }""#).is_err());
    }

    #[test]
    fn token_forms() {
        assert_eq!(token_len(r#""""a""""#), Some(7));
        assert_eq!(token_len(r#""""abc"#), Some(2));
        assert_eq!(token_len("'a\\'b' rest"), Some(6));
        assert_eq!(token_len("'abc\n'"), None);
    }
}
