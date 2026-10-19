//! Every case of `../tests/corpus/golden/cases` byte for byte: canonical text,
//! the fully optimized form, the graph view in both data styles and both
//! hashes; plus the graph -> text round trip fixed point of each style.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use kohakunode_rs::compiler::compile_program;
use kohakunode_rs::graph::{from_graph, to_graph, DataStyle};
use kohakunode_rs::sig::env::build_env;
use kohakunode_rs::sig::files::library_from_text;
use kohakunode_rs::syntax::{parse, write};
use kohakunode_rs::util::json;

fn cases() -> Vec<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../tests/corpus/golden/cases");
    let mut out: Vec<PathBuf> = fs::read_dir(&root)
        .unwrap_or_else(|e| panic!("{}: {e}", root.display()))
        .map(|e| e.expect("dir entry").path())
        .filter(|p| p.is_dir())
        .collect();
    out.sort();
    out
}

/// A file as Python's `read_text` gives it (universal newlines).
fn read(path: &Path) -> String {
    fs::read_to_string(path).unwrap_or_else(|e| panic!("{}: {e}", path.display())).replace("\r\n", "\n")
}

fn first_diff(a: &str, b: &str) -> String {
    let line = a.lines().zip(b.lines()).position(|(x, y)| x != y).unwrap_or(a.lines().count().min(b.lines().count()));
    format!(
        "first difference at line {}:\n  got:  {:?}\n  want: {:?}",
        line + 1,
        a.lines().nth(line),
        b.lines().nth(line)
    )
}

#[test]
fn golden_cases() {
    let cases = cases();
    assert_eq!(cases.len(), 46, "golden corpus size");
    let mut failures = Vec::new();
    for d in &cases {
        let name = d.file_name().unwrap().to_string_lossy().to_string();
        let libs = [Arc::new(library_from_text(&read(&d.join("sig.kirsig.json"))).expect("signature file"))];
        let program = parse(&read(&d.join("input.kir"))).expect("input parses");
        let canonical = write(&program).expect("canonical text");
        let env = build_env(&program, &libs, None, &[], false).expect("env");
        let graph = to_graph(&program, Some(&env), DataStyle::Wires).expect("graph").dumps_indent(2) + "\n";
        let graph_vars = to_graph(&program, Some(&env), DataStyle::Variables).expect("graph").dumps_indent(2) + "\n";
        let compiled = compile_program(program, &libs, None, &[], None).expect("compiles");
        let lowered = write(&compiled.lowered).expect("lowered text");
        let hashes = json::loads(&read(&d.join("hashes.json"))).expect("hashes.json");
        let checks = [
            ("canonical.kir", canonical, read(&d.join("canonical.kir"))),
            ("lowered.kir", lowered, read(&d.join("lowered.kir"))),
            ("graph.kirgraph", graph.clone(), read(&d.join("graph.kirgraph"))),
            ("graph.variables.kirgraph", graph_vars.clone(), read(&d.join("graph.variables.kirgraph"))),
            ("semantic", compiled.semantic_hash.clone(), hashes.get("semantic").unwrap().as_str().unwrap().to_string()),
            ("full", compiled.full_hash.clone(), hashes.get("full").unwrap().as_str().unwrap().to_string()),
        ];
        for (what, got, want) in checks {
            if got != want {
                failures.push(format!("{name} {what}: {}", first_diff(&got, &want)));
            }
        }
        for (style, text) in [(DataStyle::Wires, &graph), (DataStyle::Variables, &graph_vars)] {
            let g1 = json::loads(text).expect("graph json");
            let t1 = from_graph(&g1, true).expect("from_graph");
            let env1 = build_env(&t1, &libs, None, &[], false).expect("env");
            let t2 = from_graph(&to_graph(&t1, Some(&env1), style).expect("graph"), true).expect("from_graph");
            let (w1, w2) = (write(&t1).expect("t1"), write(&t2).expect("t2"));
            if w1 != w2 {
                failures.push(format!("{name} round trip ({style:?}): {}", first_diff(&w2, &w1)));
            }
        }
    }
    assert!(failures.is_empty(), "{} failures:\n{}", failures.len(), failures.join("\n"));
}
