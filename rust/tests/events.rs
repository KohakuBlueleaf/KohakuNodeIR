//! Semantic emit remains an ordinary ordered call in the KIR tooling core.
use kohakunode_rs::check::check;
use kohakunode_rs::sig::{build_env, library_from_text};
use kohakunode_rs::syntax::ast::{Kind, TypeExpr};
use kohakunode_rs::syntax::{parse, write};

#[test]
fn standard_emit_has_ordered_typed_signature_and_no_outputs() {
    let std = kohakunode_rs::sig::std::std_library();
    let emit = &std.signatures["emit"];
    assert!(emit.ordered);
    assert!(emit.mutates.is_empty() && emit.outputs.is_empty());
    assert_eq!(emit.inputs[0].name, "topic");
    assert_eq!(emit.inputs[0].ty, TypeExpr::name("str"));
    assert_eq!(emit.inputs[1].name, "payload");
    assert!(emit.inputs[1].ty.is_any());
    let text = "(\"progress\", {\"count\": 1})emit()\n";
    let program = parse(text).unwrap();
    let env = build_env(&program, &[], None, &[], false).unwrap();
    assert!(check(&program, &env).is_empty());
    assert!(matches!(&program.body[0].kind, Kind::Call { name, .. } if name == "emit"));
    assert_eq!(write(&program).unwrap(), text);
}

#[test]
fn authentic_alias_and_host_emit_are_both_ordinary_calls() {
    let source = "@use \"kir.std\" as std\n\n(\"topic\", 7)std.emit()\n";
    let program = parse(source).unwrap();
    let env = build_env(&program, &[], None, &[], false).unwrap();
    assert!(env.resolve("std.emit").found().unwrap().signature.ordered);
    assert!(check(&program, &env).is_empty());
    let host = library_from_text(
        r#"{"kirsig":1,"library":"host","nodes":[{"name":"emit","inputs":[{"name":"x"}],"outputs":[{"name":"y"}]}]}"#,
    )
    .unwrap();
    let program = parse("(7)emit(y)\n").unwrap();
    let env = build_env(&program, &[std::sync::Arc::new(host)], None, &[], false).unwrap();
    assert!(!env.resolve("emit").found().unwrap().signature.ordered);
    assert!(check(&program, &env).is_empty());
}

#[test]
fn emit_invalid_topic_and_output_count_are_checked() {
    for (source, code) in [("(7, None)emit()\n", "E040"), ("(\"topic\", 7)emit(x)\n", "E012")] {
        let program = parse(source).unwrap();
        let env = build_env(&program, &[], None, &[], false).unwrap();
        assert!(check(&program, &env).iter().any(|d| d.code == code));
    }
}
