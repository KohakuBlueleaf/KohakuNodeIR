//! Additive module declarations and durable origins, without changing old documents.
use kohakunode_rs::api::program_json;
use kohakunode_rs::graph::{from_graph, to_graph, DataStyle};
use kohakunode_rs::lower::{full_hash, run_passes, semantic_hash};
use kohakunode_rs::origins::stamp_origins;
use kohakunode_rs::sig::env::build_env;
use kohakunode_rs::syntax::ast::{walk, Kind};
use kohakunode_rs::syntax::{parse, write};

#[test]
fn module_declarations_roundtrip() {
    let source = "@use \"kir.std\" as std\n@import \"./lib/tools.kir\" as tools\n@export first\n@export second\n\n@def ()first():\n    ()tools.work()\n\n@def ()second():\n    ()first()\n";
    let p = parse(source).unwrap();
    assert_eq!(write(&p).unwrap(), source);
    assert_eq!(p.imports[0].module, "./lib/tools.kir");
    assert_eq!(p.imports[0].alias, "tools");
    assert_eq!(p.exports, ["first", "second"]);
    let ast = program_json(&p);
    assert!(ast.contains_key("imports"));
    assert!(ast.contains_key("exports"));
    for style in [DataStyle::Wires, DataStyle::Variables] {
        let g = to_graph(&p, None, style).unwrap();
        let q = from_graph(&g, false).unwrap();
        assert_eq!(q.imports, p.imports);
        assert_eq!(q.exports, p.exports);
        assert_eq!(write(&q).unwrap(), source);
    }
}

#[test]
fn declarations_are_preamble_only_and_alias_is_required() {
    for source in [
        "@import \"a.kir\"\n",
        "@export a b\n",
        "@export a.b\n",
        "x = 1\n@import \"a.kir\" as a\n",
        "x = 1\n@export x\n",
        "@def ()f():\n    @import \"a.kir\" as a\n",
        "@def ()f():\n    @export f\n",
    ] {
        assert!(parse(source).is_err(), "unexpectedly accepted {source:?}");
    }
}

#[test]
fn stamped_origins_survive_inlining_and_metadata_stripping() {
    let p = parse("@def (a)f(o):\n    @meta node_id=source_node\n    o = a\n\n(1)f(x)\n(2)f(y)\n").unwrap();
    let p = stamp_origins(&p, "lib/main.kir");
    let env = build_env(&p, &[], None, &[], false).unwrap();
    let q = run_passes(&p, &env, Some(&["order_dataflow", "inline", "strip_meta"])).unwrap();
    let copies: Vec<_> =
        walk(&q.body).into_iter().filter_map(|s| s.origin.as_ref()).filter(|o| o.node_id == "source_node").collect();
    assert_eq!(copies.len(), 2);
    assert_eq!(copies[0].definition.as_deref(), Some("f"));
    assert_eq!(copies[0].module, "lib/main.kir");
    assert_eq!(copies[0].calls.len(), 1);
    assert_ne!(copies[0].calls[0].node_id, copies[1].calls[0].node_id);
    assert!(walk(&q.body).iter().all(|s| s.meta.is_empty() && s.origin.is_some()));
    assert!(walk(&q.body).iter().any(|s| s.origin.as_ref().unwrap().generated.as_deref() == Some("inline.arg")));
    assert_eq!(stamp_origins(&p, "ignored.kir").body[0].origin, p.body[0].origin);
}

#[test]
fn deeply_nested_call_origins_are_flat_and_bounded() {
    let depth = 24;
    let mut source = String::new();
    for i in 0..depth {
        source.push_str(&format!("@def ()f{i}():\n"));
        if i + 1 < depth {
            source.push_str(&format!("    ()f{}()\n", i + 1));
        } else {
            source.push_str("    x = 1\n");
        }
    }
    source.push_str("()f0()\n");
    let p = stamp_origins(&parse(&source).unwrap(), "deep.kir");
    let env = build_env(&p, &[], None, &[], false).unwrap();
    let q = run_passes(&p, &env, Some(&["order_dataflow", "inline"])).unwrap();
    let origin = q.body[0].origin.as_ref().unwrap();
    assert_eq!(origin.calls.len(), depth);
    assert!(origin.calls.iter().all(|call| call.calls.is_empty()));
    assert!(kohakunode_rs::origins::origin_json(origin).dumps().len() < 10000);
}

#[test]
fn origins_do_not_affect_text_or_hashes() {
    let p = parse("@meta node_id=original\nx = 1\n").unwrap();
    let q = stamp_origins(&p, "main.kir");
    assert_eq!(write(&p).unwrap(), write(&q).unwrap());
    assert_eq!(semantic_hash(&p).unwrap(), semantic_hash(&q).unwrap());
    assert_eq!(full_hash(&p).unwrap(), full_hash(&q).unwrap());
    assert!(p.body[0].origin.is_none());
    assert_eq!(q.body[0].origin.as_ref().unwrap().node_id, "original");
}

#[test]
fn generated_each_version_and_group_origins() {
    let p = stamp_origins(
        &parse("xs = [1, 2]\nx = 0\n(xs)each(item, `body`)\nbody:\n    x = item\ny = x\n").unwrap(),
        "main.kir",
    );
    let env = build_env(&p, &[], None, &[], false).unwrap();
    let q = run_passes(&p, &env, None).unwrap();
    let statements = walk(&q.body);
    assert!(statements.iter().all(|s| s.origin.is_some()));
    let roles: Vec<_> = statements.iter().filter_map(|s| s.origin.as_ref()?.generated.as_deref()).collect();
    for role in ["each.items", "each.init", "each.test", "each.next", "each.repeat", "version.home", "group"] {
        assert!(roles.contains(&role), "missing generated role {role}: {roles:?}");
    }
    let original_body =
        statements.iter().find(|s| matches!(&s.kind, Kind::Namespace { label, .. } if label == "body")).unwrap();
    assert_eq!(original_body.origin.as_ref().unwrap().node_id, "body/3");
}

#[test]
fn graph_origins_preserve_compound_declarations_and_jumps_without_meta() {
    for source in [
        "@typehint:\n    (int)foo(int)\n\n@typehint:\n    (int)bar(int)\n\n@def (a)f(o):\n    o = a\n\nx = 1\n(x)branch(`yes`, `no`)\nyes:\n    y = 2\nno:\n    y = 3\n",
        "()jump(`loop`)\nloop:\n    x = 1\n    ()jump(`loop`)\n",
        "xs = [1]\n(xs)each(item, `body`)\nbody:\n    x = item\n",
        "@dataflow:\n    x = 1\n    y = 2\n@try:\n    z = 3\n@except err:\n    z = 4\n",
    ] {
        let p = stamp_origins(&parse(source).unwrap(), "main.kir");
        for style in [DataStyle::Wires, DataStyle::Variables] {
            let g = to_graph(&p, None, style).unwrap();
            let q = from_graph(&g, false).unwrap();
            let origins: Vec<_> = walk(&q.body).iter().filter_map(|s| s.origin.as_ref()).cloned().collect();
            for s in walk(&p.body) {
                assert!(origins.contains(s.origin.as_ref().unwrap()), "lost {:?} in {:?}: {}", s.origin, style, g.dumps());
            }
            assert!(walk(&q.body).iter().all(|s| s.meta.is_empty()));
        }
    }
}

#[test]
fn graph_control_entry_does_not_depend_on_origins() {
    for source in [
        "()jump(`loop`)\nloop:\n    x = 1\n    ()jump(`loop`)\n",
        "loop:\n    x = 1\n    ()jump(`loop`)\n",
        "([1])each(x, `body`)\nbody:\n    y = x\n",
        "(True)branch(`a`, `b`)\na:\n    ()jump(`join`)\nb:\n    ()jump(`join`)\njoin:\n    x = 1\n",
    ] {
        let p = parse(source).unwrap();
        for style in [DataStyle::Wires, DataStyle::Variables] {
            let plain = from_graph(&to_graph(&p, None, style).unwrap(), false).unwrap();
            let sourced = from_graph(&to_graph(&stamp_origins(&p, "main.kir"), None, style).unwrap(), false).unwrap();
            assert_eq!(write(&plain).unwrap(), write(&sourced).unwrap(), "provenance changed control flow");
            let again = from_graph(&to_graph(&plain, None, style).unwrap(), false).unwrap();
            assert_eq!(write(&plain).unwrap(), write(&again).unwrap());
            if source.starts_with("()jump") {
                assert!(matches!(plain.body[0].kind, Kind::Jump { .. }));
            }
            if source.starts_with("loop:") {
                assert!(matches!(plain.body[0].kind, Kind::Namespace { .. }));
            }
        }
    }
}

#[test]
fn origin_json_validation_and_recursive_roundtrip() {
    use kohakunode_rs::origins::{origin_from_json, origin_json};
    use kohakunode_rs::util::json::loads;
    let raw = loads(r#"{"module":"a.kir","node_id":"n","line":123456789012345678901234567890,"calls":[{"module":"b.kir","node_id":"c","line":-1}]}"#).unwrap();
    let origin = origin_from_json(Some(&raw)).unwrap().unwrap();
    assert_eq!(origin_from_json(Some(&origin_json(&origin))).unwrap().as_ref(), Some(&origin));
    for raw in [
        r#"{"module":1,"node_id":"n"}"#,
        r#"{"module":"a","node_id":"n","line":true}"#,
        r#"{"module":"a","node_id":"n","calls":[null]}"#,
        r#"{"module":"a","node_id":"n","definition":3}"#,
    ] {
        assert!(origin_from_json(Some(&loads(raw).unwrap())).is_err());
    }
}

#[test]
fn old_serializations_omit_new_fields() {
    let p = parse("x = 1\n").unwrap();
    for j in [program_json(&p), to_graph(&p, None, DataStyle::Wires).unwrap()] {
        assert!(!j.contains_key("imports"));
        assert!(!j.contains_key("exports"));
        assert!(!j.dumps().contains("origin"));
    }
}
