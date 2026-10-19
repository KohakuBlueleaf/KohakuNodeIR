//! The indentation pass before the grammar (the Python reference's
//! `lark.indenter.Indenter` post-lexer).
//!
//! A newline token is `(\r?\n[\t ]*|#[^\r\n]*)+`, so comment-only lines belong
//! to it and their indentation never counts; inside `( [ {` it is plain
//! whitespace. Outside brackets the pass inserts an `NL` marker before it, then
//! `INDENT` when its last line is deeper than the current level, or one `DEDENT`
//! per level it closes (a tab counts 4 columns). Markers are private-use
//! characters, so line numbers of the marked text equal the source's.
//!
//! A failure here (unterminated string, unbalanced bracket, inconsistent
//! dedent) ends the marked text at that point and is kept in `stop`: the
//! reference raises it only once the parser asks for that token, so a grammar
//! error earlier in the text wins.

use std::collections::HashMap;

use crate::errors::KirError;
use crate::syntax::strlit;

pub const NL: char = '\u{E000}';
pub const INDENT: char = '\u{E001}';
pub const DEDENT: char = '\u{E002}';
const MARKER_LEN: usize = 3;

/// Marked text plus the positions needed to map it back to the source.
pub struct Marked {
    pub text: String,
    /// The failure that ends `text`, if any.
    pub stop: Option<KirError>,
    /// Byte offsets (in `text`) of the inserted markers, ascending.
    inserts: Vec<usize>,
    /// `INDENT` / `DEDENT` marker offset -> source offset of their newline token
    /// (the reference's tokens borrow its position).
    anchors: HashMap<usize, usize>,
    /// Byte offsets (in the source) where each line starts.
    line_starts: Vec<usize>,
    source: String,
}

impl Marked {
    fn source_offset(&self, marked: usize) -> usize {
        if let Some(&a) = self.anchors.get(&marked) {
            return a;
        }
        marked - MARKER_LEN * self.inserts.partition_point(|&p| p < marked)
    }

    fn source_line_col(&self, off: usize) -> (usize, usize) {
        let off = off.min(self.source.len());
        let line = self.line_starts.partition_point(|&s| s <= off);
        let start = self.line_starts[line - 1];
        let col = self.source.get(start..off).map_or(off - start, |s| s.chars().count()) + 1;
        (line, col)
    }

    /// The source text under a span of the marked text that holds no marker.
    pub fn source_text(&self, start: usize, end: usize) -> &str {
        let s = self.source_offset(start);
        &self.source[s..s + (end - start)]
    }

    /// 1-based line and column (in characters) of a byte offset of the marked text.
    pub fn line_col(&self, marked: usize) -> (usize, usize) {
        self.source_line_col(self.source_offset(marked))
    }

    /// Where the reference reports a grammar failure the grammar met at byte
    /// `at` of the marked text; None when the input ran out first and the
    /// indentation pass stopped it (`stop` applies).
    ///
    /// The reference stops at the first token it cannot take, and the grammar
    /// tried that token at `at`, except: inside `=>` (the reference took `=`
    /// and fails at `>`); after `probe`, a word-boundary check just past a word
    /// (the word itself fails, or the `e` of an exponent the reference lexes as
    /// a name); and before an earlier token no terminal matches (the grammar
    /// read on inside a longer token attempt). At the end of input the
    /// reference reports its last token, whose position is line 1, column 1
    /// for a `DEDENT` (lark borrows only from a non-empty token).
    pub fn grammar_error(&self, at: usize, probe: bool) -> Option<(usize, usize)> {
        let tokens = token_spans(&self.text);
        let holding = |p: usize| tokens.iter().position(|t| t.start <= p && p < t.end);
        let text_of = |k: usize| &self.text[tokens[k].start..tokens[k].end];
        let mut pos = None;
        let mut k = if probe && at > 0 { holding(at - 1) } else { None };
        if let Some(i) = k.filter(|&i| i > 0 && matches!(text_of(i), "+" | "-")) {
            if matches!(text_of(i - 1), "e" | "E") && tokens[i - 1].end == tokens[i].start {
                k = Some(i - 1);
            }
        }
        if k.is_none() {
            k = holding(at).or_else(|| tokens.iter().position(|t| t.start >= at));
            if let Some(i) = k {
                if tokens[i].start < at && self.text[tokens[i].start..].starts_with("=>") {
                    pos = Some(at);
                }
            }
        }
        let start = |k: Option<usize>| pos.or(k.map(|k| tokens[k].start));
        if let Some(bad) = tokens.iter().position(|t| !t.valid) {
            if start(k).is_none_or(|p| tokens[bad].start < p) {
                return Some(self.line_col(tokens[bad].start));
            }
        }
        match k {
            Some(_) if pos.is_some() => Some(self.line_col(at)),
            Some(k) => Some(self.line_col(tokens[k].start)),
            None if self.stop.is_some() => None,
            None => Some(match tokens.last() {
                Some(t) if self.text[t.start..].starts_with(DEDENT) => (1, 1),
                Some(t) => self.line_col(t.start),
                None => (1, 1),
            }),
        }
    }
}

/// A token of marked text: its byte span, and whether a terminal matches it.
struct Tok {
    start: usize,
    end: usize,
    valid: bool,
}

fn is_marker(c: char) -> bool {
    matches!(c, NL | INDENT | DEDENT)
}

/// The tokens of marked text, in order: markers, strings, labels, numbers,
/// names, directives and punctuation (whitespace and comments are skipped).
fn token_spans(text: &str) -> Vec<Tok> {
    const DIRECTIVES: [&str; 9] = ["use", "def", "meta", "hint", "mode", "dataflow", "try", "except", "typehint"];
    let b = text.as_bytes();
    let ident = |c: u8| c.is_ascii_alphanumeric() || c == b'_';
    let word_end = |mut j: usize| {
        while j < b.len() && ident(b[j]) {
            j += 1;
        }
        j
    };
    let digits = |mut i: usize| {
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        i
    };
    let mut out = Vec::new();
    let mut i = 0;
    while i < b.len() {
        let c = b[i];
        let (end, valid) = match c {
            b' ' | b'\t' | b'\n' => {
                i += 1;
                continue;
            }
            b'\r' if b.get(i + 1) == Some(&b'\n') => {
                i += 2;
                continue;
            }
            b'#' => {
                let rest = &text[i..];
                i += rest.find(['\r', '\n', NL, INDENT, DEDENT]).unwrap_or(rest.len());
                continue;
            }
            b'"' | b'\'' => match strlit::token_len(&text[i..]) {
                Some(n) => (i + n, true),
                None => (i + 1, false),
            },
            b'`' => {
                let close = word_end(i + 1);
                if close > i + 1 && b.get(close) == Some(&b'`') && !b[i + 1].is_ascii_digit() {
                    (close + 1, true)
                } else {
                    (i + 1, false)
                }
            }
            b'@' => {
                let j = word_end(i + 1);
                (j, DIRECTIVES.contains(&&text[i + 1..j]))
            }
            _ if c.is_ascii_alphabetic() || c == b'_' => (word_end(i), true),
            b'0'..=b'9' | b'+' | b'-' | b'.' => {
                let s = if matches!(c, b'+' | b'-') { i + 1 } else { i };
                let radix = match (b.get(s), b.get(s + 1).map(u8::to_ascii_lowercase)) {
                    (Some(b'0'), Some(b'x')) => Some(16),
                    (Some(b'0'), Some(b'o')) => Some(8),
                    (Some(b'0'), Some(b'b')) => Some(2),
                    _ => None,
                };
                let prefixed = radix.map_or(s, |r| {
                    let mut j = s + 2;
                    while j < b.len() && (b[j] as char).is_digit(r) {
                        j += 1;
                    }
                    j
                });
                if prefixed > s + 2 {
                    (prefixed, true)
                } else {
                    let int_end = digits(s);
                    let frac_end = if b.get(int_end) == Some(&b'.') { digits(int_end + 1) } else { int_end };
                    let mantissa = frac_end > s && !(int_end == s && frac_end == int_end + 1);
                    if !mantissa {
                        // A lone `.` is a terminal; a lone sign is not.
                        (i + 1, c == b'.')
                    } else {
                        let mut e = frac_end;
                        if matches!(b.get(e), Some(b'e' | b'E')) {
                            let mut k = e + 1;
                            if matches!(b.get(k), Some(b'+' | b'-')) {
                                k += 1;
                            }
                            if digits(k) > k {
                                e = digits(k);
                            }
                        }
                        (e, true)
                    }
                }
            }
            b'=' if b.get(i + 1) == Some(&b'>') => (i + 2, true),
            _ => {
                let ch = text[i..].chars().next().expect("in bounds");
                (i + ch.len_utf8(), is_marker(ch) || "()[]{},:=|?".contains(ch))
            }
        };
        out.push(Tok { start: i, end, valid });
        i = end;
    }
    out
}

/// The length of the newline token `(\r?\n[\t ]*|#[^\r\n]*)+` at the start of `b`.
fn newline_len(b: &[u8]) -> usize {
    let mut i = 0;
    loop {
        if b.get(i) == Some(&b'#') {
            while !matches!(b.get(i), None | Some(b'\r' | b'\n')) {
                i += 1;
            }
            continue;
        }
        let start = i;
        if b.get(i) == Some(&b'\r') {
            i += 1;
        }
        if b.get(i) != Some(&b'\n') {
            return start;
        }
        i += 1;
        while matches!(b.get(i), Some(b' ' | b'\t')) {
            i += 1;
        }
    }
}

pub fn mark(source: &str) -> Marked {
    let b = source.as_bytes();
    let mut line_starts = vec![0];
    line_starts.extend(source.match_indices('\n').map(|(i, _)| i + 1));
    let mut m = Marked {
        text: String::with_capacity(source.len() + source.len() / 8),
        stop: None,
        inserts: Vec::new(),
        anchors: HashMap::new(),
        line_starts,
        source: source.to_string(),
    };
    let stop = |m: &mut Marked, src_at: usize, message: String| {
        let (line, col) = m.source_line_col(src_at);
        m.stop = Some(KirError::syntax(message, Some(line), Some(col)));
    };
    let mut paren: usize = 0;
    let mut levels: Vec<usize> = vec![0];
    let mut last_newline = 0;
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'"' | b'\'' => match strlit::token_len(&source[i..]) {
                Some(n) => {
                    // The grammar sees `"xx..x"` of the same byte length; the
                    // literal is decoded from the source.
                    m.text.push('"');
                    m.text.push_str(&"x".repeat(n - 2));
                    m.text.push('"');
                    i += n;
                }
                None => {
                    stop(&mut m, i, "unexpected input: unterminated string".into());
                    return m;
                }
            },
            b'#' | b'\r' | b'\n' if newline_len(&b[i..]) > 0 => {
                let n = newline_len(&b[i..]);
                let token = &source[i..i + n];
                last_newline = i;
                if paren == 0 {
                    m.inserts.push(m.text.len());
                    m.text.push(NL);
                }
                // Marker characters inside comments must not read as markers.
                for c in token.chars() {
                    if is_marker(c) {
                        m.text.push_str(&"#".repeat(MARKER_LEN));
                    } else {
                        m.text.push(c);
                    }
                }
                if paren == 0 {
                    let last = token.rsplit('\n').next().unwrap_or("");
                    let indent = last.matches(' ').count() + 4 * last.matches('\t').count();
                    let marker = |m: &mut Marked, c: char| {
                        m.anchors.insert(m.text.len(), i);
                        m.inserts.push(m.text.len());
                        m.text.push(c);
                    };
                    if indent > *levels.last().expect("base level") {
                        levels.push(indent);
                        marker(&mut m, INDENT);
                    } else {
                        while indent < *levels.last().expect("base level") {
                            levels.pop();
                            marker(&mut m, DEDENT);
                        }
                        let expected = *levels.last().expect("base level");
                        if indent != expected {
                            // At the line's first non-blank character, tabs
                            // expanded to stops of 4 (Python's `expandtabs`).
                            let width = last.chars().fold(0, |w, c| if c == '\t' { w / 4 * 4 + 4 } else { w + 1 });
                            let line = m.source_line_col(i + n).0;
                            m.stop = Some(KirError::syntax(
                                "unindent does not match any outer indentation level",
                                Some(line),
                                Some(width + 1),
                            ));
                            return m;
                        }
                    }
                }
                i += n;
            }
            c @ (b'(' | b'[' | b'{' | b')' | b']' | b'}') => {
                if matches!(c, b')' | b']' | b'}') {
                    if paren == 0 {
                        stop(&mut m, i, "unexpected input: unbalanced closing bracket".into());
                        return m;
                    }
                    paren -= 1;
                } else {
                    paren += 1;
                }
                m.text.push(c as char);
                i += 1;
            }
            _ => {
                let c = source[i..].chars().next().expect("in bounds");
                if is_marker(c) {
                    stop(&mut m, i, "unexpected input".into());
                    return m;
                }
                m.text.push(c);
                i += c.len_utf8();
            }
        }
    }
    // Left open inside a bracket: the reference's end-of-input DEDENTs are
    // placed at its last token, the newline the bracket swallowed.
    while levels.len() > 1 {
        levels.pop();
        m.anchors.insert(m.text.len(), last_newline);
        m.inserts.push(m.text.len());
        m.text.push(DEDENT);
    }
    m
}
