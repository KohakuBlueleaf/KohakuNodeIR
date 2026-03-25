/*
 * External scanner for KohakuNodeIR (.kir) indentation.
 *
 * Emits three tokens:
 *   NEWLINE  — a logical end-of-line (after stripping blank lines / comments)
 *   INDENT   — indentation increased
 *   DEDENT   — indentation decreased (one per level, possibly multiple in a row)
 *
 * Design follows tree-sitter-python's scanner closely:
 *   - An indent stack (array of uint32_t) tracks the current column depth.
 *   - Newlines trigger column measurement of the *next* non-blank, non-comment
 *     line to decide whether to emit INDENT, DEDENT, or NEWLINE.
 *   - Open-bracket depth (paren / square / brace) suppresses NEWLINE/INDENT/
 *     DEDENT inside multi-line expressions.
 *
 * Token indices (must match the order in grammar.js `externals`):
 *   0 → INDENT   (_indent)
 *   1 → DEDENT   (_dedent)
 *   2 → NEWLINE  (_newline)
 */

#include "tree_sitter/parser.h"
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* ── Token index constants ── */
#define TOKEN_INDENT  0
#define TOKEN_DEDENT  1
#define TOKEN_NEWLINE 2

/* ── Indent stack ── */
#define INDENT_STACK_MAX 256

typedef struct {
    uint32_t indent_stack[INDENT_STACK_MAX];
    uint32_t stack_top;   /* index of the current (innermost) level */
    uint32_t paren_depth; /* open ( [ { depth — suppresses NL tokens */
    /* When we measure the next line we may need to emit multiple DEDENTs
       before we can continue.  We store the pending column and a flag. */
    bool     has_pending;
    uint32_t pending_col;
} Scanner;

/* ── Serialise / deserialise (for incremental re-parse) ── */

unsigned tree_sitter_kir_external_scanner_serialize(void *payload, char *buffer)
{
    Scanner *sc = (Scanner *)payload;
    /* Format: stack_top (4 bytes) + paren_depth (4 bytes) +
               stack values (4 bytes each) + has_pending (1) + pending_col (4) */
    uint32_t stack_len = sc->stack_top + 1; /* number of entries */
    unsigned offset = 0;

    memcpy(buffer + offset, &stack_len, 4);    offset += 4;
    memcpy(buffer + offset, &sc->paren_depth, 4); offset += 4;
    memcpy(buffer + offset, sc->indent_stack, 4 * stack_len); offset += 4 * stack_len;
    buffer[offset++] = sc->has_pending ? 1 : 0;
    memcpy(buffer + offset, &sc->pending_col, 4); offset += 4;
    return offset;
}

void tree_sitter_kir_external_scanner_deserialize(void *payload,
                                                   const char *buffer,
                                                   unsigned length)
{
    Scanner *sc = (Scanner *)payload;
    if (length == 0) return;
    unsigned offset = 0;

    uint32_t stack_len = 0;
    memcpy(&stack_len, buffer + offset, 4); offset += 4;
    memcpy(&sc->paren_depth, buffer + offset, 4); offset += 4;
    if (stack_len > INDENT_STACK_MAX) stack_len = INDENT_STACK_MAX;
    memcpy(sc->indent_stack, buffer + offset, 4 * stack_len); offset += 4 * stack_len;
    sc->stack_top = stack_len > 0 ? stack_len - 1 : 0;
    sc->has_pending = buffer[offset++] != 0;
    memcpy(&sc->pending_col, buffer + offset, 4);
}

/* ── Allocation ── */

void *tree_sitter_kir_external_scanner_create(void)
{
    Scanner *sc = (Scanner *)calloc(1, sizeof(Scanner));
    sc->indent_stack[0] = 0;
    sc->stack_top = 0;
    sc->paren_depth = 0;
    sc->has_pending = false;
    sc->pending_col = 0;
    return sc;
}

void tree_sitter_kir_external_scanner_destroy(void *payload)
{
    free(payload);
}

/* ── Helpers ── */

static inline uint32_t current_indent(Scanner *sc)
{
    return sc->indent_stack[sc->stack_top];
}

/* Skip a character as whitespace (it contributes to lookahead but not token). */
static void skip(TSLexer *lexer)
{
    lexer->advance(lexer, true);
}

/* Peek at the next character without consuming it. */
static inline int32_t peek(TSLexer *lexer)
{
    return lexer->lookahead;
}

/* ── Main scan function ── */

bool tree_sitter_kir_external_scanner_scan(void *payload, TSLexer *lexer,
                                            const bool *valid_symbols)
{
    Scanner *sc = (Scanner *)payload;

    /* ── Fast path: if we have a pending dedent, emit it now ── */
    if (sc->has_pending && valid_symbols[TOKEN_DEDENT]) {
        uint32_t col = sc->pending_col;
        if (sc->stack_top > 0 && col < current_indent(sc)) {
            sc->stack_top--;
            /* Keep has_pending set if we still need more DEDENTs. */
            if (sc->stack_top == 0 || col >= current_indent(sc)) {
                sc->has_pending = false;
            }
            lexer->result_symbol = TOKEN_DEDENT;
            return true;
        }
        sc->has_pending = false;
    }

    /* ── Skip horizontal whitespace at the start of the token ── */
    while (peek(lexer) == ' ' || peek(lexer) == '\t') {
        skip(lexer);
    }

    /* ── Handle newlines ── */
    if (peek(lexer) == '\r' || peek(lexer) == '\n') {
        /* Inside brackets: consume the newline(s) silently. */
        if (sc->paren_depth > 0) {
            while (peek(lexer) == '\r' || peek(lexer) == '\n' ||
                   peek(lexer) == ' '  || peek(lexer) == '\t') {
                skip(lexer);
            }
            return false; /* Let the main grammar handle the next token. */
        }

        /* Outside brackets: consume all consecutive newlines + blank lines,
           then measure the column of the next non-blank, non-comment line. */
        if (valid_symbols[TOKEN_NEWLINE] || valid_symbols[TOKEN_INDENT] ||
            valid_symbols[TOKEN_DEDENT]) {

            /* Consume the actual newline character(s). */
            while (peek(lexer) == '\r') skip(lexer);
            if (peek(lexer) == '\n') skip(lexer);

            /* Now skip blank/comment lines and measure indent of the next
               real line. */
            for (;;) {
                /* Skip horizontal whitespace. */
                uint32_t col = 0;
                while (peek(lexer) == ' ' || peek(lexer) == '\t') {
                    col += (peek(lexer) == '\t') ? 4 : 1;
                    skip(lexer);
                }
                /* Blank line or comment line — skip and keep going. */
                if (peek(lexer) == '\r' || peek(lexer) == '\n') {
                    while (peek(lexer) == '\r') skip(lexer);
                    if (peek(lexer) == '\n') skip(lexer);
                    col = 0;
                    continue;
                }
                if (peek(lexer) == '#') {
                    /* Skip comment to end of line. */
                    while (peek(lexer) != '\n' && peek(lexer) != '\r' &&
                           peek(lexer) != 0) {
                        skip(lexer);
                    }
                    while (peek(lexer) == '\r') skip(lexer);
                    if (peek(lexer) == '\n') skip(lexer);
                    col = 0;
                    continue;
                }
                /* Non-blank, non-comment line found.  col is its indent. */
                if (peek(lexer) == 0 /* EOF */) {
                    /* Emit remaining DEDENTs on EOF. */
                    if (sc->stack_top > 0 && valid_symbols[TOKEN_DEDENT]) {
                        sc->stack_top--;
                        lexer->result_symbol = TOKEN_DEDENT;
                        return true;
                    }
                    if (valid_symbols[TOKEN_NEWLINE]) {
                        lexer->result_symbol = TOKEN_NEWLINE;
                        return true;
                    }
                    return false;
                }

                /* Compare col to current indent. */
                if (col > current_indent(sc)) {
                    if (valid_symbols[TOKEN_INDENT]) {
                        /* Push new indent level. */
                        if (sc->stack_top + 1 < INDENT_STACK_MAX) {
                            sc->stack_top++;
                            sc->indent_stack[sc->stack_top] = col;
                        }
                        lexer->result_symbol = TOKEN_INDENT;
                        return true;
                    }
                    /* INDENT not expected here — fall through to NEWLINE. */
                }

                if (col < current_indent(sc)) {
                    if (valid_symbols[TOKEN_DEDENT]) {
                        sc->stack_top--;
                        /* Schedule additional DEDENTs if needed. */
                        if (sc->stack_top > 0 && col < current_indent(sc)) {
                            sc->has_pending = true;
                            sc->pending_col  = col;
                        }
                        lexer->result_symbol = TOKEN_DEDENT;
                        return true;
                    }
                    /* DEDENT not expected — fall through. */
                }

                /* col == current_indent(sc): same level — emit NEWLINE. */
                if (valid_symbols[TOKEN_NEWLINE]) {
                    lexer->result_symbol = TOKEN_NEWLINE;
                    return true;
                }
                return false;
            }
        }
        return false;
    }

    /* ── Track bracket depth ── */
    if (peek(lexer) == '(' || peek(lexer) == '[' || peek(lexer) == '{') {
        sc->paren_depth++;
        /* Let the grammar consume the bracket itself. */
        return false;
    }
    if ((peek(lexer) == ')' || peek(lexer) == ']' || peek(lexer) == '}') &&
        sc->paren_depth > 0) {
        sc->paren_depth--;
        return false;
    }

    /* ── EOF: flush remaining dedents ── */
    if (peek(lexer) == 0) {
        if (sc->stack_top > 0 && valid_symbols[TOKEN_DEDENT]) {
            sc->stack_top--;
            lexer->result_symbol = TOKEN_DEDENT;
            return true;
        }
        if (valid_symbols[TOKEN_NEWLINE]) {
            lexer->result_symbol = TOKEN_NEWLINE;
            return true;
        }
    }

    return false;
}
