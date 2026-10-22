//! Source module linking is deterministic, declaration-only, and origin-preserving.
use kohakunode_rs::compiler::compile_program_with_modules;
use kohakunode_rs::modules::{link_program, module_id, ModuleMap};
use kohakunode_rs::syntax::ast::{walk, Kind};
use kohakunode_rs::syntax::{parse, write};

fn resources(items: &[(&str, &str)]) -> ModuleMap {
    items.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
}

const LIB: &str = "@export identity\n@def (x: int = 7)identity(y: int):\n    y = x\n";

#[test]
fn native_compilation_links_resources_and_preserves_origins() {
    let source = "@import \"lib/id.kir\" as lib\n()lib.identity(result)\n";
    let map = resources(&[("lib/id.kir", LIB)]);
    let c = compile_program_with_modules(parse(source).unwrap(), &[], None, &[], None, Some(&map), "main.kir").unwrap();
    assert_eq!(c.source_program.imports.len(), 1);
    assert!(c.program.imports.is_empty());
    assert_eq!(c.dependencies.get("modules").unwrap().as_array().unwrap().len(), 2);
    assert!(walk(&c.lowered.body).iter().all(|s| s.origin.is_some()));
    let definition_origins: Vec<_> = walk(&c.lowered.body)
        .into_iter()
        .filter_map(|s| s.origin.as_ref())
        .filter(|o| o.module == "lib/id.kir")
        .collect();
    assert!(!definition_origins.is_empty());
    assert!(definition_origins.iter().any(|o| o.calls.iter().any(|c| c.module == "main.kir")));
    assert!(write(&c.program).unwrap().contains("_kir_"));
}

#[test]
fn modules_have_separate_private_names_and_nested_imports() {
    let map = resources(&[
        ("a.kir", "@import \"sub/b.kir\" as b\n@export f\n@def (x)helper(y):\n    (x)b.f(y)\n@def (x)f(y):\n    (x)helper(y)\n"),
        ("sub/b.kir", "@export f\n@def (x)helper(y):\n    y = x\n@def (x)f(y):\n    (x)helper(y)\n"),
    ]);
    let c = compile_program_with_modules(
        parse("@import \"a.kir\" as a\n(1)a.f(y)\n").unwrap(),
        &[],
        None,
        &[],
        None,
        Some(&map),
        "main.kir",
    )
    .unwrap();
    let defs: Vec<_> = walk(&c.program.body)
        .into_iter()
        .filter_map(|s| match &s.kind {
            Kind::Def(d) => Some(&d.name),
            _ => None,
        })
        .collect();
    assert_eq!(defs.len(), 4);
    let unique: std::collections::HashSet<_> = defs.into_iter().collect();
    assert_eq!(unique.len(), 4);
}

#[test]
fn module_link_errors_are_actionable() {
    for (source, map, expected) in [
        ("@import \"missing.kir\" as m\n", resources(&[]), "missing from the module map"),
        ("@import \"a.kir\" as a\n", resources(&[("a.kir", "x = 1\n")]), "declarations only"),
        ("@import \"a.kir\" as a\n", resources(&[("a.kir", "@import \"main.kir\" as m\n")]), "import cycle"),
        ("@import \"a.kir\" as a\n()a.private()\n", resources(&[("a.kir", LIB)]), "not exported"),
        ("@export absent\n", resources(&[]), "not a top-level definition"),
        ("@export f\n@export f\n@def ()f():\n    x = 1\n", resources(&[]), "duplicate export"),
        ("@import \"a.kir\" as a\n@import \"a.kir\" as a\n", resources(&[("a.kir", LIB)]), "ambiguous import alias"),
        ("@export _kir_bad\n@def ()_kir_bad():\n    x = 1\n", resources(&[]), "reserved prefix"),
    ] {
        let err = match link_program(&parse(source).unwrap(), &[], None, &[], Some(&map), "main.kir") {
            Ok(_) => panic!("accepted {source}"),
            Err(e) => e,
        };
        assert!(err.to_string().contains(expected), "{err} missing {expected}");
    }
}

#[test]
fn contract_identity_ignores_doc_and_object_and_node_order() {
    use kohakunode_rs::modules::contract_hash;
    use kohakunode_rs::sig::files::library_from_text;
    let a = library_from_text(r#"{"kirsig":1,"library":"host","nodes":[{"name":"z","inputs":[{"name":"x","default":{"a":1,"b":2}}],"doc":"first"},{"name":"a"}]}"#).unwrap();
    let b = library_from_text(r#"{"kirsig":1,"library":"host","nodes":[{"name":"a"},{"name":"z","inputs":[{"name":"x","default":{"b":2,"a":1}}],"doc":"second"}]}"#).unwrap();
    assert_eq!(contract_hash(&a).unwrap(), contract_hash(&b).unwrap());
}

#[test]
fn modular_contract_rejects_nonportable_defaults_without_changing_legacy_serialization() {
    use kohakunode_rs::modules::contract_hash;
    use kohakunode_rs::sig::files::library_to_json;
    use kohakunode_rs::sig::model::{Library, Port, Signature};
    use kohakunode_rs::syntax::ast::TypeExpr;
    use kohakunode_rs::syntax::value::Value;
    for value in [
        Value::Tuple(vec![]),
        Value::Float(f64::NAN),
        Value::Float(f64::INFINITY),
        Value::Dict(vec![(Value::int(1), Value::str("x"))]),
        Value::List(vec![Value::Tuple(vec![])]),
    ] {
        let mut lib = Library::new("host");
        lib.add_signature(Signature::new(
            "op",
            vec![Port { name: "x".into(), ty: TypeExpr::Any, default: Some(value) }],
            vec![],
        ))
        .unwrap();
        assert!(library_to_json(&lib).is_ok());
        assert!(contract_hash(&lib).unwrap_err().to_string().contains("nonportable signature default"));
    }
}

#[test]
fn custom_standard_library_cannot_capture_actual_standard_fallback() {
    use kohakunode_rs::sig::model::Library;
    use std::sync::Arc;
    let map = resources(&[("lib.kir", LIB)]);
    let result = link_program(
        &parse("@import \"lib.kir\" as lib\n").unwrap(),
        &[Arc::new(Library::new("kir.std"))],
        None,
        &[],
        Some(&map),
        "main.kir",
    );
    let error = match result {
        Err(e) => e.to_string(),
        Ok(_) => panic!("accepted conflicting kir.std"),
    };
    assert!(error.contains("incompatible signature libraries share name 'kir.std'"));
}

#[test]
fn module_ids_are_portable_and_root_bounded() {
    assert_eq!(module_id("../a/./b.kir", "sub/main.kir").unwrap(), "a/b.kir");
    for name in ["", "../a", "/a", "C:/a", "https://a", "a\\b", "a/../.."] {
        assert!(module_id(name, "main.kir").is_err(), "accepted {name}");
    }
}

#[test]
fn dependency_identity_changes_for_transitive_edits_not_metadata() {
    let source = parse("@import \"lib.kir\" as lib\n()lib.identity(result)\n").unwrap();
    let compile = |library: &str| {
        compile_program_with_modules(
            source.clone(),
            &[],
            None,
            &[],
            None,
            Some(&resources(&[("lib.kir", library)])),
            "main.kir",
        )
        .unwrap()
    };
    let a = compile(LIB);
    let b = compile(&LIB.replace("y = x", "@meta pos=(3, 4)\n    y = x"));
    let c = compile(&LIB.replace("= 7", "= 8"));
    assert_eq!(a.dependencies, b.dependencies);
    assert_eq!(a.semantic_hash, b.semantic_hash);
    assert_ne!(a.semantic_hash, c.semantic_hash);
}

#[test]
fn imported_std_is_not_shadowed_by_entry_definition() {
    let source = "@import \"lib.kir\" as lib\n@def (a, b)add(c):\n    c = 999\n(2)lib.f(y)\n";
    let map = resources(&[("lib.kir", "@export f\n@def (x)f(y):\n    (x, 1)add(y)\n")]);
    let linked = link_program(&parse(source).unwrap(), &[], None, &[], Some(&map), "main.kir").unwrap();
    let text = write(&linked.program).unwrap();
    assert!(text.contains("lib0.add(y)"), "{text}");
    compile_program_with_modules(parse(source).unwrap(), &[], None, &[], None, Some(&map), "main.kir").unwrap();
}

#[test]
fn exported_nominal_types_accept_alias_qualification() {
    let source = "@import \"lib.kir\" as lib\n@def (x: lib.Token)main(y: lib.Token):\n    (x)lib.id(y)\n";
    let map = resources(&[("lib.kir", "@export id\n@def (x: Token)id(y: Token):\n    y = x\n")]);
    let c = compile_program_with_modules(parse(source).unwrap(), &[], None, &[], Some(&[]), Some(&map), "main.kir")
        .unwrap();
    assert!(!write(&c.program).unwrap().contains("lib.Token"));
}

#[test]
fn filesystem_imports_check_lower_and_hash_through_legacy_api() {
    use kohakunode_rs::api::{self, Signatures};
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("target")
        .join(format!("linking-api-{}", std::process::id()));
    std::fs::create_dir_all(&root).unwrap();
    std::fs::write(root.join("lib.kir"), LIB).unwrap();
    let base = root.to_str().unwrap();
    let sigs = Signatures { base: Some(base), ..Signatures::default() };
    let source = "@import \"lib.kir\" as lib\n()lib.identity(result)\n";
    assert_eq!(api::check(source, sigs).unwrap(), "[]");
    assert!(api::lower(source, sigs, None).unwrap().contains("7"));
    assert!(api::hashes(source, sigs, None).is_ok());
    assert!(link_program(&parse(source).unwrap(), &[], Some(&root), &[], Some(&ModuleMap::new()), "main.kir").is_err());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn physical_symlink_import_cycle_is_rejected_when_supported() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("target")
        .join(format!("linking-symlink-{}", std::process::id()));
    std::fs::create_dir_all(&root).unwrap();
    std::fs::write(root.join("lib.kir"), "@import \"alias/lib.kir\" as again\n").unwrap();
    #[cfg(windows)]
    let made = std::os::windows::fs::symlink_dir(&root, root.join("alias"));
    #[cfg(unix)]
    let made = std::os::unix::fs::symlink(&root, root.join("alias"));
    #[cfg(not(any(windows, unix)))]
    let made: std::io::Result<()> = Err(std::io::Error::other("symlinks unsupported"));
    if made.is_ok() {
        let result =
            link_program(&parse("@import \"lib.kir\" as lib\n").unwrap(), &[], Some(&root), &[], None, "main.kir");
        let error = match result {
            Err(e) => e.to_string(),
            Ok(_) => panic!("accepted physical cycle"),
        };
        assert!(error.contains("import cycle"), "{error}");
        #[cfg(windows)]
        std::fs::remove_dir(root.join("alias")).unwrap();
        #[cfg(unix)]
        std::fs::remove_file(root.join("alias")).unwrap();
    }
    std::fs::remove_dir_all(root).unwrap();
}
