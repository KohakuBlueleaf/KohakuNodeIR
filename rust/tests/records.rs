//! K3 schemas are immutable metadata and ordinary pure derived node signatures.
use kohakunode_rs::sig::files::{library_from_text, library_to_json};
use kohakunode_rs::sig::model::{Port, Signature};
use kohakunode_rs::sig::types::parse_type;
use kohakunode_rs::sig::{Library, RecordField, RecordSchema};
use kohakunode_rs::syntax::ast::TypeExpr;
use kohakunode_rs::syntax::value::Value;
use std::sync::Arc;

fn field(name: &str, ty: &str, default: Option<Value>) -> RecordField {
    RecordField::new(name, parse_type(ty).unwrap(), default).unwrap()
}

const POINT: &str = r#"{"kirsig":2,"library":"geometry","nodes":[],"records":[{"name":"Point","fields":[{"name":"x","type":"float"},{"name":"y","type":"float","default":0},{"name":"label","type":"str?","default":null}]}]}"#;

#[test]
fn schemas_derive_typed_pure_signatures_without_duplicating_exported_nodes() {
    let lib = library_from_text(POINT).unwrap();
    assert_eq!(lib.records["Point"].schema_id(), "geometry.Point");
    let make = &lib.signatures["Point.make"];
    assert_eq!(make.inputs.len(), 3);
    assert!(make.inputs[0].required());
    assert!(!make.inputs[2].required());
    assert!(matches!(make.inputs[2].default, Some(Value::None)));
    assert_eq!(make.outputs[0].ty, TypeExpr::name("geometry.Point"));
    assert_eq!(lib.signatures["Point.get.x"].outputs[0].ty, TypeExpr::name("float"));
    assert_eq!(lib.signatures["Point.with.x"].inputs[0].name, "record");
    assert_eq!(lib.signatures["Point.with.x"].inputs[1].name, "value");
    assert!(lib.signatures.values().all(|s| !s.ordered && s.mutates.is_empty()));
    let json = library_to_json(&lib).unwrap();
    assert!(json.get("nodes").unwrap().as_array().unwrap().is_empty());
    assert_eq!(library_to_json(&library_from_text(&json.dumps()).unwrap()).unwrap(), json);
}

#[test]
fn defaults_are_strict_and_missing_is_not_nullable() {
    let nullable = field("x", "int?", None);
    assert!(!nullable.has_default());
    assert!(field("x", "int?", Some(Value::None)).has_default());
    for (ty, value) in [
        ("int", Value::Bool(true)),
        ("bool", Value::int(1)),
        ("int", Value::None),
        ("Point", Value::Dict(vec![])),
        ("list[int]", Value::List(vec![Value::Bool(false)])),
        ("dict[str, int]", Value::Dict(vec![(Value::str("x"), Value::str("bad"))])),
        ("_", Value::Tuple(vec![])),
        ("float", Value::Float(f64::INFINITY)),
        ("dict", Value::Dict(vec![(Value::int(1), Value::None)])),
        ("dict", Value::Dict(vec![(Value::str("x"), Value::int(1)), (Value::str("x"), Value::int(2))])),
    ] {
        assert!(RecordField::new("x", parse_type(ty).unwrap(), Some(value)).is_err(), "accepted {ty}");
    }
    for ty in ["list[int, str]", "dict[int, str]", "Box[int]", "list[]"] {
        assert!(parse_type(ty).and_then(|t| RecordField::new("x", t, None).map_err(|e| e.to_string())).is_err());
    }
}

#[test]
fn registration_is_atomic_and_rejects_collisions_and_cycles() {
    let mut lib = Library::new("geometry");
    lib.add_signature(Signature::new("Point.get.x", vec![], vec![])).unwrap();
    assert!(lib.add_record(RecordSchema::new("Point", vec![field("x", "int", None)]).unwrap()).is_err());
    assert!(lib.records.is_empty());
    assert_eq!(lib.signatures.len(), 1);
    let mut lib = Library::new("geometry");
    lib.add_record(RecordSchema::new("A", vec![field("b", "B?", None)]).unwrap()).unwrap();
    let before = lib.signatures.len();
    assert!(lib.add_record(RecordSchema::new("B", vec![field("a", "list[A]", None)]).unwrap()).is_err());
    assert_eq!(lib.records.len(), 1);
    assert_eq!(lib.signatures.len(), before);
    assert!(RecordSchema::new("Bad", vec![field("x", "int", None), field("x", "int", None)]).is_err());
}

#[test]
fn local_record_references_qualify_handwritten_signatures() {
    let mut lib = Library::new("geometry");
    lib.add_signature(Signature::new("consume", vec![Port::new("value", TypeExpr::name("Point"))], vec![])).unwrap();
    lib.add_record(RecordSchema::new("Point", vec![]).unwrap()).unwrap();
    assert_eq!(lib.signatures["consume"].inputs[0].ty, TypeExpr::name("geometry.Point"));
    lib.add_signature(Signature::new("later", vec![Port::new("value", TypeExpr::name("Point"))], vec![])).unwrap();
    assert_eq!(lib.signatures["later"].inputs[0].ty, TypeExpr::name("geometry.Point"));
}

#[test]
fn generated_nodes_are_available_to_checker_graph_and_compiler() {
    let lib = Arc::new(library_from_text(POINT).unwrap());
    let source = "@use \"geometry\" as g\n(1)g.Point.make(p)\n(p)g.Point.get.x(x)\n(p, 3)g.Point.with.x(q)\n";
    let p = kohakunode_rs::syntax::parse(source).unwrap();
    let env = kohakunode_rs::sig::build_env(&p, std::slice::from_ref(&lib), None, &[], false).unwrap();
    assert!(kohakunode_rs::check::check(&p, &env).is_empty());
    let graph = kohakunode_rs::graph::to_graph(&p, Some(&env), kohakunode_rs::graph::DataStyle::Wires).unwrap();
    assert!(graph.dumps().contains("geometry.Point"));
    kohakunode_rs::compiler::compile_program(p, &[lib], None, &[], None).unwrap();
}

#[test]
fn schema_identity_includes_defaults_but_generated_mutation_is_rejected() {
    let mut lib = library_from_text(POINT).unwrap();
    let first = kohakunode_rs::modules::contract_hash(&lib).unwrap();
    let changed = library_from_text(&POINT.replace("\"default\":0", "\"default\":1")).unwrap();
    assert_ne!(first, kohakunode_rs::modules::contract_hash(&changed).unwrap());
    lib.signatures.get_mut("Point.make").unwrap().ordered = true;
    assert!(library_to_json(&lib).is_err());
    for default in [Value::Bool(false), Value::Float(0.0), Value::Float(-0.0)] {
        let mut lib = library_from_text(POINT).unwrap();
        lib.signatures.get_mut("Point.make").unwrap().inputs[1].default = Some(default);
        assert!(library_to_json(&lib).is_err(), "type-sensitive generated default mutation accepted");
    }
}

#[test]
fn aliases_canonicalize_annotations_but_keep_authored_source() {
    let lib = Arc::new(library_from_text(POINT).unwrap());
    let source = "@use \"geometry\" as g\n@def (p: g.Point)read(x: float):\n    (p)g.Point.get.x(x)\n(1)g.Point.make(p)\n(p)read(x)\n";
    let program = kohakunode_rs::syntax::parse(source).unwrap();
    let env = kohakunode_rs::sig::build_env(&program, std::slice::from_ref(&lib), None, &[], false).unwrap();
    assert!(kohakunode_rs::check::check(&program, &env).is_empty());
    let compiled = kohakunode_rs::compiler::compile_program(program, &[lib], None, &[], None).unwrap();
    assert!(kohakunode_rs::syntax::write(&compiled.program).unwrap().contains("p: geometry.Point"));
    assert_eq!(
        kohakunode_rs::syntax::write(&compiled.source_program).unwrap(),
        kohakunode_rs::api::format(source).unwrap()
    );
    assert!(compiled.dependencies.contains_key("hash"));
    assert!(compiled.dependencies.get("modules").unwrap().as_array().unwrap().is_empty());
}

#[test]
fn full_environment_rejects_unknown_and_recursive_cross_library_schemas() {
    let mut a = Library::new("a");
    a.add_record(RecordSchema::new("A", vec![field("b", "b.B?", None)]).unwrap()).unwrap();
    let p = kohakunode_rs::syntax::parse("x = 1\n").unwrap();
    let a = Arc::new(a);
    let error = kohakunode_rs::sig::build_env(&p, std::slice::from_ref(&a), None, &[], false).unwrap_err();
    assert!(error.to_string().contains("references unknown schema 'b.B'"));
    let mut b = Library::new("b");
    b.add_record(RecordSchema::new("B", vec![field("a", "list[a.A]", None)]).unwrap()).unwrap();
    let error = kohakunode_rs::sig::build_env(&p, &[a, Arc::new(b)], None, &[], false).unwrap_err();
    assert!(error.to_string().contains("recursive record schema"));
}

#[test]
fn record_type_ambiguity_and_unknown_nominals_remain_distinct() {
    let libs: Vec<_> = ["a", "b"]
        .into_iter()
        .map(|name| {
            let mut lib = Library::new(name);
            lib.add_record(RecordSchema::new("Point", vec![]).unwrap()).unwrap();
            Arc::new(lib)
        })
        .collect();
    let p = kohakunode_rs::syntax::parse("@def (p: Point)f(q: Point):\n    q = p\n").unwrap();
    let env = kohakunode_rs::sig::build_env(&p, &libs, None, &[], false).unwrap();
    assert!(env
        .record_type(&TypeExpr::name("Point"))
        .unwrap_err()
        .to_string()
        .contains("ambiguous record type 'Point': a.Point, b.Point"));
    assert_eq!(env.record_type(&TypeExpr::name("Other")).unwrap(), TypeExpr::name("Other"));
    assert_eq!(kohakunode_rs::check::check(&p, &env)[0].code, "E002");
}

#[test]
fn conflicting_same_id_defaults_are_type_sensitive() {
    let schema = |value| {
        let mut lib = Library::new("host");
        lib.add_record(RecordSchema::new("Data", vec![field("value", "_", Some(value))]).unwrap()).unwrap();
        Arc::new(lib)
    };
    for (a, b) in [
        (Value::Bool(true), Value::int(1)),
        (Value::int(1), Value::Float(1.0)),
        (Value::Float(0.0), Value::Float(-0.0)),
    ] {
        let env = kohakunode_rs::sig::NodeEnv {
            libraries: vec![(schema(a), Some("a".into())), (schema(b), Some("b".into()))],
            ..Default::default()
        };
        assert!(env.record_schemas().unwrap_err().to_string().contains("conflicting record schema 'host.Data'"));
    }
}

#[test]
fn programmatic_types_normalize_to_roundtrippable_text() {
    let any = RecordField::new("any", TypeExpr::Optional(Box::new(TypeExpr::Any)), None).unwrap();
    assert!(any.ty().is_any());
    let union = RecordField::new(
        "value",
        TypeExpr::Optional(Box::new(TypeExpr::Union(vec![TypeExpr::name("int"), TypeExpr::name("str")]))),
        Some(Value::None),
    )
    .unwrap();
    assert_eq!(
        union.ty(),
        &TypeExpr::Union(vec![TypeExpr::name("int"), TypeExpr::name("str"), TypeExpr::name("None")])
    );
    let mut lib = Library::new("host");
    lib.add_record(RecordSchema::new("Record", vec![any, union]).unwrap()).unwrap();
    let json = library_to_json(&lib).unwrap();
    assert_eq!(library_to_json(&library_from_text(&json.dumps()).unwrap()).unwrap(), json);
}

#[test]
fn record_only_compilation_hashes_change_with_schema_defaults() {
    let p = kohakunode_rs::syntax::parse("@use \"geometry\" as g\n(1)g.Point.make(p)\n").unwrap();
    let compile = |text: &str| {
        kohakunode_rs::compiler::compile_program(
            p.clone(),
            &[Arc::new(library_from_text(text).unwrap())],
            None,
            &[],
            None,
        )
        .unwrap()
    };
    let a = compile(POINT);
    let b = compile(&POINT.replace("\"default\":0", "\"default\":1"));
    assert_eq!(kohakunode_rs::syntax::write(&a.lowered).unwrap(), kohakunode_rs::syntax::write(&b.lowered).unwrap());
    assert_ne!(a.semantic_hash, b.semantic_hash);
    assert_ne!(a.full_hash, b.full_hash);
}

#[test]
fn format_one_remains_unchanged_and_empty_v2_canonicalizes_v1() {
    let old = r#"{"kirsig":1,"library":"host","nodes":[]}"#;
    let v1 = library_to_json(&library_from_text(old).unwrap()).unwrap();
    let v2 = library_to_json(&library_from_text(&old.replace(":1", ":2")).unwrap()).unwrap();
    assert_eq!(v1, v2);
    assert!(!v1.contains_key("records"));
    assert!(library_from_text(&POINT.replace("\"kirsig\":2", "\"kirsig\":1")).is_err());
}
