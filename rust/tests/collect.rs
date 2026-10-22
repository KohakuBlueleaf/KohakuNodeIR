//! K4 collection control, deferred reads, graph representation and correctness lowering.
use kohakunode_rs::check::check;
use kohakunode_rs::flow::cfg::{build_cfg, NodeKind};
use kohakunode_rs::lower::run_passes;
use kohakunode_rs::sig::build_env;
use kohakunode_rs::syntax::ast::{walk, Kind};
use kohakunode_rs::syntax::{parse, write};

const SOURCE: &str = "xs = [1, 2]\n(xs)collect(item, i, `body`, value -> results)\nbody:\n    (item, i)add(value)\n(results)len(count)\n";

#[test]
fn collect_parse_write_and_deferred_ast_contract() {
    let p = parse(SOURCE).unwrap();
    assert_eq!(write(&p).unwrap(), SOURCE);
    let collect = &p.body[1];
    assert!(matches!(collect.kind, Kind::Collect { has_index: true, .. }));
    assert_eq!(collect.reads(), ["xs"]);
    assert_eq!(collect.deferred_reads(), ["value"]);
    assert_eq!(collect.writes(), ["item", "i", "results"]);
    let ast = kohakunode_rs::api::program_json(&p);
    assert!(ast.dumps().contains("\"kind\": \"collect\""));
    for source in [
        "(xs)collect(x, `b`, x -> _)\nb:\n",
        "(xs)collect(x, `b`, x)\nb:\n",
        "()collect(x, `b`, x -> out)\nb:\n",
        "(xs)f(x, `b`, x -> out)\nb:\n",
    ] {
        assert!(parse(source).is_err(), "accepted {source}");
    }
}

#[test]
fn qualified_host_collect_remains_an_ordinary_call() {
    let source = "@use \"host\" as h\n\n(1)h.collect(result)\n";
    let p = parse(source).unwrap();
    assert!(matches!(&p.body[0].kind, Kind::Call { name, .. } if name == "h.collect"));
    assert_eq!(write(&p).unwrap(), source);
    let lib = kohakunode_rs::sig::library_from_text(r#"{"kirsig":1,"library":"host","nodes":[{"name":"collect","inputs":[{"name":"value","type":"int"}],"outputs":[{"name":"result","type":"int"}]}]}"#).unwrap();
    let compiled = kohakunode_rs::compiler::compile_program(p, &[std::sync::Arc::new(lib)], None, &[], None).unwrap();
    assert!(write(&compiled.lowered).unwrap().contains("h.collect"));
}

#[test]
fn cfg_samples_at_body_end_and_publishes_only_on_completion() {
    let p = parse(SOURCE).unwrap();
    let cfg = build_cfg(&p.body, &[]);
    let uid = p.body[1].uid;
    let controller = cfg.node_of[&uid];
    let sample = cfg.samples[&uid];
    let done = cfg.completions[&uid];
    assert_eq!(cfg.nodes[controller].kind, NodeKind::Stmt);
    assert_eq!(cfg.nodes[controller].reads, ["xs"]);
    assert!(cfg.nodes[controller].writes.is_empty());
    assert_eq!(cfg.nodes[sample].reads, ["value"]);
    assert_eq!(cfg.nodes[done].writes, ["results"]);
    assert_eq!(cfg.nodes[sample].kind, NodeKind::CollectSample);
    assert_eq!(cfg.nodes[done].kind, NodeKind::CollectDone);
    let env = build_env(&p, &[], None, &[], false).unwrap();
    assert!(check(&p, &env).is_empty());
}

#[test]
fn graph_value_port_is_explicitly_deferred_and_roundtrips() {
    use kohakunode_rs::graph::{from_graph, to_graph, DataStyle};
    let p = parse(SOURCE).unwrap();
    let env = build_env(&p, &[], None, &[], false).unwrap();
    for style in [DataStyle::Wires, DataStyle::Variables] {
        let graph = to_graph(&p, Some(&env), style).unwrap();
        let text = graph.dumps();
        assert!(text.contains("\"deferred\": \"body_end\""));
        assert!(text.contains("\"port\": \"results\""));
        let q = from_graph(&graph, false).unwrap();
        assert_eq!(write(&q).unwrap(), SOURCE);
    }
}

#[test]
fn checker_rejects_target_access_escape_mutation_and_missing_yield() {
    for (source, expected) in [
        ("([1])collect(x, `b`, missing -> out)\nb:\n    y = x\n", "E020"),
        ("([1])collect(out, `b`, out -> out)\nb:\n    y = 1\n", "E070"),
        ("([1])collect(x, `b`, x -> out)\nb:\n    out = x\n", "E070"),
        ("([1])collect(x, `b`, x -> out)\nb:\n    ()jump(`outside`)\noutside:\n    y = 1\n", "E071"),
    ] {
        let p = parse(source).unwrap();
        let env = build_env(&p, &[], None, &[], false).unwrap();
        assert!(check(&p, &env).iter().any(|d| d.code == expected), "missing {expected} for {source}");
    }
    let p = parse("([1])collect(x, `b`, x -> out)\nb:\n    y = x\n(out)mutate()\n").unwrap();
    let lib = kohakunode_rs::sig::library_from_text(r#"{"kirsig":1,"library":"host","nodes":[{"name":"mutate","inputs":[{"name":"value"}],"outputs":[],"flags":{"mutates":["value"],"ordered":false}}]}"#).unwrap();
    let env = build_env(&p, &[std::sync::Arc::new(lib)], None, &[], false).unwrap();
    assert!(check(&p, &env).iter().any(|d| d.code == "E072"));
}

#[test]
fn lowering_has_private_accumulator_internal_append_and_origins() {
    let p = kohakunode_rs::origins::stamp_origins(&parse(SOURCE).unwrap(), "main.kir");
    let env = build_env(&p, &[], None, &[], false).unwrap();
    let q = run_passes(&p, &env, Some(&["expand_collect"])).unwrap();
    let text = write(&q).unwrap();
    assert!(text.contains("collect__1__values = []"));
    assert!(text.contains("kir.collect_append(collect__1__values)"));
    assert!(text.contains("results = collect__1__values"));
    assert!(!walk(&q.body).iter().any(|s| matches!(s.kind, Kind::Collect { .. })));
    assert!(matches!(&q.body[1].kind, Kind::Call { name, .. } if name == "kir.collect_items"));
    for role in ["collect.items", "collect.init", "collect.append", "collect.result"] {
        assert!(walk(&q.body).iter().any(|s| s.origin.as_ref().and_then(|o| o.generated.as_deref()) == Some(role)));
    }
    assert!(run_passes(&p, &env, Some(&["expand_each"])).unwrap_err().to_string().contains("needs 'expand_collect'"));
    kohakunode_rs::compiler::compile_program(p, &[], None, &[], None).unwrap();
}

#[test]
fn collect_types_follow_dependencies_not_lexical_order() {
    for body in [
        "([1])collect(x, `first`, 7 -> xs)\nfirst:\n    a = x\n([1])collect(y, `second`, xs -> ys)\nsecond:\n    b = y\n",
        "second:\n    b = y\nfirst:\n    a = x\n([1])collect(x, `first`, 7 -> xs)\n([1])collect(y, `second`, xs -> ys)\n",
    ] {
        let source = format!("@typehint:\n    (list[list[str]])consume()\n{body}(ys)consume()\n");
        let p = parse(&source).unwrap();
        let env = build_env(&p, &[], None, &[], false).unwrap();
        assert!(check(&p, &env).iter().any(|d| d.code == "E040" && d.message.contains("list[list[int]]")));
    }
    let p = parse(
        "xs = []\n([1])collect(x, `a`, ys -> xs)\na:\n    y = 1\n([1])collect(z, `b`, xs -> ys)\nb:\n    w = 2\n",
    )
    .unwrap();
    let env = build_env(&p, &[], None, &[], false).unwrap();
    assert!(check(&p, &env).iter().any(|d| d.code == "E020"));
}

#[test]
fn collect_namespace_before_owner_and_nested_collection_lower() {
    for source in [
        "b:\n    value = 1\n([1])collect(x, `b`, value -> out)\n",
        "([1])collect(x, `outer`, inner_values -> out)\nouter:\n    ([2])collect(y, `inner`, y -> inner_values)\n    inner:\n        z = y\n",
    ] {
        let compiled = kohakunode_rs::compiler::compile_program(parse(source).unwrap(), &[], None, &[], None).unwrap();
        assert!(!walk(&compiled.lowered.body).iter().any(|s| matches!(s.kind, Kind::Collect { .. } | Kind::Each { .. })));
    }
}
