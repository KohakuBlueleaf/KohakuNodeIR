//! Indentation preprocessor for KIR source text.
//!
//! KIR uses significant indentation (like Python).  The pest grammar cannot
//! handle indentation natively, so this module transforms the raw source text
//! into a flat stream where indent/dedent changes are marked by the literal
//! strings `INDENT\n` and `DEDENT\n`.  Those marker strings are what the
//! grammar's `INDENT` and `DEDENT` rules match.
//!
//! Rules (matches the Lark Indenter behaviour from `indenter.py`):
//!
//! * Leading horizontal whitespace on a non-blank, non-comment-only line
//!   determines the indent level.
//! * When the new level is greater than the current top of the indent stack,
//!   one `INDENT\n` marker is emitted before the line.
//! * When the new level is less than the current top, one or more `DEDENT\n`
//!   markers are emitted (one per level popped) before the line.
//! * Blank lines and lines consisting only of whitespace + a comment are
//!   passed through unchanged and do **not** trigger indent/dedent.
//! * Content inside open parentheses `(` / `[` / `{` is treated as a
//!   continuation: newlines there are not treated as statement terminators
//!   and do not trigger indent/dedent changes.
//! * A final `DEDENT\n` is appended for every remaining non-zero indent level
//!   at EOF so the grammar can always close open blocks.

/// Preprocess `source` text, inserting `INDENT\n` / `DEDENT\n` markers.
///
/// Returns the transformed string ready to be fed to the pest parser.
pub fn preprocess(source: &str) -> String {
    let mut out = String::with_capacity(source.len() + 64);
    let mut indent_stack: Vec<usize> = vec![0];
    let mut paren_depth: i32 = 0;

    for raw_line in source.lines() {
        // Count leading spaces/tabs (tabs count as 1 for simplicity;
        // the Lark indenter uses tab_len=4, but KIR files in practice
        // use 4-space indentation throughout).
        let indent_chars: usize = raw_line
            .chars()
            .take_while(|c| *c == ' ' || *c == '\t')
            .count();
        let stripped = &raw_line[indent_chars..];

        // Detect blank / comment-only lines: pass through without
        // triggering indent/dedent logic.
        let is_blank = stripped.is_empty() || stripped.starts_with('#');

        if is_blank || paren_depth > 0 {
            // Pass the line through verbatim; blank lines inside parens are
            // also passed through unchanged.
            out.push_str(raw_line);
            out.push('\n');
            // Still track paren depth changes even on otherwise-blank lines
            // (unlikely in practice but be safe).
            for ch in raw_line.chars() {
                match ch {
                    '(' | '[' | '{' => paren_depth += 1,
                    ')' | ']' | '}' => paren_depth -= 1,
                    _ => {}
                }
            }
            continue;
        }

        let current = *indent_stack.last().unwrap();

        if indent_chars > current {
            // Indent increased.
            indent_stack.push(indent_chars);
            out.push_str("INDENT\n");
        } else if indent_chars < current {
            // Indent decreased — may close multiple levels.
            while indent_stack.len() > 1 {
                let top = *indent_stack.last().unwrap();
                if top <= indent_chars {
                    break;
                }
                indent_stack.pop();
                out.push_str("DEDENT\n");
            }
            // If the new level does not exactly match anything in the stack,
            // we've recovered as best we can (the parser will error later).
        }
        // Same level: no markers needed.

        // Emit the original line (with its leading whitespace stripped,
        // since pest's grammar doesn't expect leading spaces).
        out.push_str(stripped);
        out.push('\n');

        // Track open-paren depth for continuation-line suppression.
        for ch in stripped.chars() {
            match ch {
                '(' | '[' | '{' => paren_depth += 1,
                ')' | ']' | '}' => {
                    if paren_depth > 0 {
                        paren_depth -= 1;
                    }
                }
                '#' => break, // rest of line is comment
                _ => {}
            }
        }
    }

    // Close any remaining open indent levels.
    while indent_stack.len() > 1 {
        indent_stack.pop();
        out.push_str("DEDENT\n");
    }

    out
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_flat_program_unchanged() {
        let src = "x = 42\n(x)print()\n";
        let result = preprocess(src);
        assert_eq!(result, "x = 42\n(x)print()\n");
    }

    #[test]
    fn test_single_indent_dedent() {
        let src = "loop:\n    ()jump(`loop`)\n";
        let result = preprocess(src);
        assert_eq!(result, "loop:\nINDENT\n()jump(`loop`)\nDEDENT\n");
    }

    #[test]
    fn test_nested_indent() {
        let src = "a:\n    b:\n        x = 1\n";
        let result = preprocess(src);
        assert_eq!(result, "a:\nINDENT\nb:\nINDENT\nx = 1\nDEDENT\nDEDENT\n");
    }

    #[test]
    fn test_blank_lines_preserved() {
        let src = "x = 1\n\ny = 2\n";
        let result = preprocess(src);
        assert_eq!(result, "x = 1\n\ny = 2\n");
    }

    #[test]
    fn test_comment_lines_preserved() {
        let src = "# header\nx = 1\n";
        let result = preprocess(src);
        assert_eq!(result, "# header\nx = 1\n");
    }

    #[test]
    fn test_eof_dedent() {
        // Body ends at EOF without a trailing blank line.
        let src = "ns:\n    x = 1";
        let result = preprocess(src);
        assert_eq!(result, "ns:\nINDENT\nx = 1\nDEDENT\n");
    }

    #[test]
    fn test_multiple_dedents() {
        let src = "a:\n    b:\n        x = 1\ny = 2\n";
        let result = preprocess(src);
        assert_eq!(
            result,
            "a:\nINDENT\nb:\nINDENT\nx = 1\nDEDENT\nDEDENT\ny = 2\n"
        );
    }
}
