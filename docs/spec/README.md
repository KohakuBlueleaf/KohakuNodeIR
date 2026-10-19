# KIR v2 specification

KIR (Kohaku Node IR) describes one job as a node graph. Its text is that graph
written line by line, and its meaning is a sequential run of that text.

| Document | Contents |
|---|---|
| [language.md](language.md) | Lexical structure, statements, builtins, directives, grammar |
| [semantics.md](semantics.md) | What a program means: the sequential run, parallel by default, scopes, `each`, errors, node flags |
| [signatures.md](signatures.md) | Node signatures, the signature file, `@use`, the Python registry |
| [graph.md](graph.md) | The graph view (`.kirgraph`) and how it maps to and from text |
| [passes.md](passes.md) | Optimization passes, the fully optimized form, program hashes |
| [checks.md](checks.md) | Every rule the checker enforces |

## One language, many forms

A program is one thing, shown as a graph for editors or as text for people
and tools. Optimization passes rewrite it into simpler programs in the same
language, down to a form an interpreter can run directly. There are no levels
in the language: a graph, hand-written text and fully optimized text are all
KIR, and any of them runs.

## Conformance

A conforming executor produces, for every job, the result the reference
interpreter produces when it runs the program sequentially with the same node
results. How it schedules nodes is its own business (semantics.md, "Parallel by
default").

The Python package `kohakunode` is the reference implementation. The Rust core
must produce byte-identical canonical text, graph JSON, optimized text and
hashes for the same input.
