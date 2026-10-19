/*
 * External scanner for KIR: INDENT, DEDENT, NEWLINE and the @-directives.
 *
 * INDENT, DEDENT and NEWLINE are zero-width (mark_end is called before any
 * lookahead), so the line break itself is consumed afterwards as an extra.
 * The scanner only looks ahead to measure the indentation of the next code
 * line; blank lines and comment-only lines are skipped, so a comment's
 * indentation never counts. Inside ( [ { the grammar never expects these
 * tokens, so line breaks there are ordinary whitespace.
 *
 * Directives are scanned here so that they end at a word boundary: `@metax`
 * is consumed whole and returned as the never-valid sentinel, a parse error.
 *
 * A tab counts as 4 columns, like the reference parser (tab_len = 4).
 */

#include "tree_sitter/parser.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum TokenType {
    INDENT,
    DEDENT,
    NEWLINE,
    USE,
    DEF,
    META,
    HINT,
    MODE,
    DATAFLOW,
    TRY,
    EXCEPT,
    TYPEHINT,
    ERROR_SENTINEL,
};

static const char *const DIRECTIVES[] = {
    [USE] = "use",      [DEF] = "def",           [META] = "meta",
    [HINT] = "hint",    [MODE] = "mode",         [DATAFLOW] = "dataflow",
    [TRY] = "try",      [EXCEPT] = "except",     [TYPEHINT] = "typehint",
};

#define TAB_WIDTH 4
#define MAX_DEPTH (TREE_SITTER_SERIALIZATION_BUFFER_SIZE / sizeof(uint16_t))
#define MAX_WORD 16

typedef struct {
    uint16_t indents[MAX_DEPTH + 1]; /* indents[0] is the top level, always 0 */
    uint32_t depth;
} Scanner;

static inline void skip(TSLexer *lexer) { lexer->advance(lexer, true); }

static inline bool is_word_char(int32_t c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
}

void *tree_sitter_kir_external_scanner_create(void) { return calloc(1, sizeof(Scanner)); }

void tree_sitter_kir_external_scanner_destroy(void *payload) { free(payload); }

unsigned tree_sitter_kir_external_scanner_serialize(void *payload, char *buffer) {
    Scanner *s = (Scanner *)payload;
    unsigned size = s->depth * sizeof(uint16_t);
    memcpy(buffer, &s->indents[1], size);
    return size;
}

void tree_sitter_kir_external_scanner_deserialize(void *payload, const char *buffer, unsigned length) {
    Scanner *s = (Scanner *)payload;
    s->indents[0] = 0;
    s->depth = length / sizeof(uint16_t);
    if (s->depth > MAX_DEPTH) s->depth = MAX_DEPTH;
    memcpy(&s->indents[1], buffer, s->depth * sizeof(uint16_t));
}

/* Consumes `@word`; returns the directive token if it is one and valid here. */
static bool scan_directive(TSLexer *lexer, const bool *valid_symbols) {
    char word[MAX_WORD + 1];
    unsigned len = 0;
    lexer->advance(lexer, false);
    while (is_word_char(lexer->lookahead)) {
        if (len < MAX_WORD) word[len] = (char)lexer->lookahead;
        len++;
        lexer->advance(lexer, false);
    }
    lexer->mark_end(lexer);
    word[len < MAX_WORD ? len : MAX_WORD] = '\0';
    lexer->result_symbol = ERROR_SENTINEL;
    if (len > MAX_WORD) return true;
    for (int t = USE; t <= TYPEHINT; t++) {
        if (valid_symbols[t] && strcmp(word, DIRECTIVES[t]) == 0) {
            lexer->result_symbol = t;
            break;
        }
    }
    return true;
}

bool tree_sitter_kir_external_scanner_scan(void *payload, TSLexer *lexer, const bool *valid_symbols) {
    Scanner *s = (Scanner *)payload;

    /* Every external is valid only during error recovery: emit nothing. */
    if (valid_symbols[ERROR_SENTINEL]) return false;

    bool directive_valid = false;
    for (int t = USE; t <= TYPEHINT; t++) directive_valid |= valid_symbols[t];
    /* `@def` is valid exactly where a statement may start. */
    bool statement_start = valid_symbols[DEF] && !valid_symbols[INDENT] && !valid_symbols[NEWLINE];

    lexer->mark_end(lexer);

    /* The first line of the file is measured like any other line. */
    bool found_eol = statement_start && lexer->lookahead != '\n' && lexer->lookahead != '\r' &&
                     lexer->get_column(lexer) == 0;
    int32_t comment_indent = -1;
    uint32_t indent = 0;

    for (;;) {
        int32_t c = lexer->lookahead;
        if (lexer->eof(lexer)) {
            found_eol = true;
            indent = 0;
            break;
        }
        if (c == '\n' || c == '\r' || c == '\f') {
            found_eol = true;
            indent = 0;
            skip(lexer);
        } else if (c == ' ') {
            indent++;
            skip(lexer);
        } else if (c == '\t') {
            indent += TAB_WIDTH;
            skip(lexer);
        } else if (c == '#') {
            /* A trailing comment is lexed as an extra first; scan again after it. */
            if (!found_eol) return false;
            if (comment_indent == -1) comment_indent = (int32_t)indent;
            while (!lexer->eof(lexer) && lexer->lookahead != '\n' && lexer->lookahead != '\r') skip(lexer);
        } else {
            break;
        }
    }

    if (found_eol) {
        uint32_t current = s->indents[s->depth];

        /* An unexpected indent at a statement start is pushed anyway, as a parse error. */
        if (indent > current && (valid_symbols[INDENT] || statement_start) && s->depth < MAX_DEPTH) {
            s->indents[++s->depth] = (uint16_t)indent;
            lexer->result_symbol = INDENT;
            return true;
        }

        /* Only the code line decides the DEDENT; a comment still at block indent
           is placed inside the block by emitting the DEDENT after it. */
        if (valid_symbols[DEDENT] && indent < current && comment_indent < (int32_t)current) {
            s->depth--;
            lexer->result_symbol = DEDENT;
            return true;
        }

        if (valid_symbols[NEWLINE]) {
            lexer->result_symbol = NEWLINE;
            return true;
        }
    }

    /* Skipped comments must become extras before a token with width is returned. */
    if (directive_valid && comment_indent == -1 && lexer->lookahead == '@') return scan_directive(lexer, valid_symbols);

    return false;
}
