"""Source-module composition is visible, isolated, portable, and executable."""

import hashlib
from dataclasses import replace

import pytest

from kohakunode import (
    Interpreter,
    KirCheckError,
    Library,
    NodeFailure,
    compile_file,
    compile_source,
)
from kohakunode.lower import PASSES
from kohakunode.sig.files import save_library
from kohakunode.sig.model import Port, Signature
from kohakunode.syntax.ast import TypeExpr

LIBRARY = """
@export transform
@def (xs: list, keep: bool = True)transform(result: list):
    result = []
    (xs)each(x, `body`)
    body:
        (keep)branch(`yes`, `no`)
        yes:
            (result, x)append(result)
        no:
            skipped = x
"""
ENTRY = """
@import "lib.kir" as lib
@def (xs: list)main(result: list):
    (xs)lib.transform(result)
"""


@pytest.mark.parametrize("passes", [list(PASSES)[:i] for i in range(len(PASSES) + 1)])
def test_imported_control_flow_runs_after_every_pass_prefix(passes):
    source = ENTRY + "([1, 2, 3])main(result)\n"
    compiled = compile_source(source, modules={"lib.kir": LIBRARY}, passes=passes)
    interpreter = Interpreter(compiled.lowered, compiled.env)
    interpreter.run()
    assert interpreter.source_values()["result"] == [1, 2, 3]
    assert compiled.source_program.imports
    assert not compiled.program.imports
    assert compiled.dependencies["version"] == 1


def test_private_names_and_signature_aliases_are_isolated():
    source = """
@import "a.kir" as a
@import "b.kir" as b
(a_value = 1)a.convert(a_result)
(2)b.convert(b_result)
"""
    module = """
@export convert
@def (a_value: int)helper(result: int):
    result = a_value
@def (a_value: int)convert(result: int):
    (a_value)helper(result)
"""
    compiled = compile_source(source, modules={"a.kir": module, "b.kir": module})
    interp = Interpreter(compiled.lowered, compiled.env)
    interp.run()
    values = interp.source_values()
    assert values["a_result"] == 1
    assert values["b_result"] == 2


@pytest.mark.parametrize(
    ("source", "modules", "message"),
    [
        ('@import "missing.kir" as lib\n', {}, "missing"),
        (
            '@import "lib.kir" as lib\n()lib.private()\n',
            {"lib.kir": "@def ()private():\n    x = 1\n"},
            "not exported",
        ),
        ('@import "lib.kir" as lib\n', {"lib.kir": "x = 1\n"}, "declarations only"),
        ('@import "lib.kir" as lib\n', {"lib.kir": "@export nope\n"}, "not a top-level"),
        (
            '@import "lib.kir" as lib\n',
            {
                "lib.kir": LIBRARY.replace(
                    "@export transform", "@export transform\n@export transform"
                )
            },
            "duplicate export",
        ),
        (
            '@import "lib.kir" as lib\n@import "other.kir" as lib\n',
            {"lib.kir": LIBRARY},
            "ambiguous import alias",
        ),
        ('@import "lib.kir" as lib\n', {"lib.kir": '@import "lib.kir" as again\n'}, "import cycle"),
        ('@import "../outside.kir" as lib\n', {}, "escapes"),
        ('@import "/absolute.kir" as lib\n', {}, "relative POSIX"),
    ],
)
def test_module_errors_are_explicit(source, modules, message):
    with pytest.raises(KirCheckError, match=message):
        compile_source(source, modules=modules)


def test_recursive_imported_subgraph_remains_rejected():
    module = "@export recur\n@def (x)recur(y):\n    (x)recur(y)\n"
    with pytest.raises(KirCheckError, match=r"r\.kir.*calls itself"):
        compile_source('@import "r.kir" as r\n(1)r.recur(y)\n', modules={"r.kir": module})


def test_transitive_relative_import_and_relocation(tmp_path):
    source = '@import "package/outer.kir" as lib\n(7)lib.convert(result)\n'
    modules = {
        "package/outer.kir": '@import "inner.kir" as inner\n@export convert\n@def (x: int)convert(y: int):\n    (x)inner.convert(y)\n',
        "package/inner.kir": "@export convert\n@def (x: int)convert(y: int):\n    y = x\n",
    }
    results = []
    for directory in (tmp_path / "original", tmp_path / "moved"):
        directory.mkdir()
        (directory / "main.kir").write_text(source, encoding="utf-8")
        for name, text in modules.items():
            path = directory / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8")
        results.append(compile_file(directory / "main.kir"))
    mapped = compile_source(source, modules=modules, source_name="main.kir")
    assert results[0].dependencies == results[1].dependencies == mapped.dependencies
    assert results[0].semantic_hash == results[1].semantic_hash == mapped.semantic_hash


def test_dependency_identity_ignores_metadata_but_tracks_unused_exports():
    first = compile_source(ENTRY, modules={"lib.kir": LIBRARY})
    metadata = LIBRARY.replace("    result = []", '    @meta node_id="collection"\n    result = []')
    second = compile_source(ENTRY, modules={"lib.kir": metadata})
    assert first.dependencies == second.dependencies
    assert first.semantic_hash == second.semantic_hash
    changed = LIBRARY + "@def ()unused(value):\n    value = 42\n"
    third = compile_source(ENTRY, modules={"lib.kir": changed})
    assert first.dependencies != third.dependencies
    assert first.semantic_hash != third.semantic_hash


def test_signature_contract_changes_dependency_identity_without_loading_implementations():
    node = Signature("identity", (Port("x", TypeExpr("name", "int"), 1),), (Port("y"),))
    lib = Library("host", {"identity": node})
    module = '@use "host" as h\n@export value\n@def ()value(y):\n    ()h.identity(y)\n'
    source = '@import "lib.kir" as lib\n()lib.value(result)\n'
    first = compile_source(source, [lib], modules={"lib.kir": module})
    changed = Library("host", {"identity": replace(node, ordered=True)})
    second = compile_source(source, [changed], modules={"lib.kir": module})
    assert first.dependencies["hash"] != second.dependencies["hash"]


def test_given_host_library_remains_visible_to_entry_and_import():
    lib = Library("host")
    lib.add_signature(Signature("identity", (Port("x"),), (Port("y"),)), lambda x: x)
    module = "@export value\n@def (x)value(y):\n    (x)identity(y)\n"
    source = '@import "lib.kir" as lib\n(4)identity(x)\n(x)lib.value(result)\n'
    compiled = compile_source(source, [lib], modules={"lib.kir": module})
    interp = Interpreter(compiled.lowered, compiled.env)
    interp.run()
    assert interp.source_values()["result"] == 4


def test_imported_standard_node_is_not_shadowed_by_entry_definition():
    module = "@export collect\n@def (x)collect(ys):\n    ([], x)append(ys)\n"
    source = """
@import "lib.kir" as lib
@def (xs, x)append(ys):
    ys = [99]
(4)lib.collect(result)
"""
    compiled = compile_source(source, modules={"lib.kir": module})
    interp = Interpreter(compiled.lowered, compiled.env)
    interp.run()
    assert interp.source_values()["result"] == [4]


def test_nominal_types_are_module_local_and_accessible_through_exports():
    module = "@export identity\n@def (x: Token)identity(y: Token):\n    y = x\n"
    source = """
@import "a.kir" as a
@import "b.kir" as b
@def (x: a.Token)main(y: a.Token):
    (x)a.identity(y)
"""
    compile_source(source, modules={"a.kir": module, "b.kir": module})
    with pytest.raises(KirCheckError, match="E04"):
        compile_source(
            source.replace("(x)a.identity(y)", "(x)b.identity(y)"),
            modules={"a.kir": module, "b.kir": module},
        )


def test_module_map_is_authoritative_even_with_a_filesystem_base(tmp_path):
    (tmp_path / "lib.kir").write_text(LIBRARY, encoding="utf-8")
    with pytest.raises(KirCheckError, match="missing from the module map"):
        compile_source(ENTRY, base_dir=tmp_path, modules={})


def test_generated_alias_namespace_cannot_be_shadowed_by_entry():
    alias = "_kir_" + hashlib.sha256(b"lib.kir").hexdigest()[:16] + "__lib0"
    lib = Library("host")
    source = f'@use "host" as {alias}\n@import "lib.kir" as lib\n'
    with pytest.raises(KirCheckError, match="reserved prefix"):
        compile_source(source, [lib], modules={"lib.kir": LIBRARY})


def test_nominal_identity_follows_transitive_export_signature():
    modules = {
        "inner.kir": "@export identity\n@def (x: Token)identity(y: Token):\n    y = x\n",
        "outer.kir": '@import "inner.kir" as inner\n@export relay\n@def (x: inner.Token)relay(y: inner.Token):\n    (x)inner.identity(y)\n',
    }
    source = '@import "outer.kir" as outer\n@def (x: outer.inner.Token)main(y: outer.inner.Token):\n    (x)outer.relay(y)\n'
    compiled = compile_source(source, modules=modules, passes=[])
    assert compiled.program.body[-1].params[0].type == compiled.program.body[0].params[0].type


def test_imported_typehint_names_do_not_collapse_or_shadow_definitions():
    module = """
@export wrapper
@typehint:
    (int)a.b(int)
    (str)a__b(str)
@def (x: int)a__b(y: int):
    y = x
@def (x: int)wrapper(y: int):
    (x)a.b(y)
"""
    compiled = compile_source(
        '@import "lib.kir" as lib\n(1)lib.wrapper(y)\n', modules={"lib.kir": module}, passes=[]
    )
    names = list(compiled.env.typehints)
    assert len(names) == 2
    assert names[0] != names[1]
    assert not set(names) & set(compiled.env.defs)


@pytest.mark.parametrize("default", [{1: "one", "two": 2}, {1: "one"}, (1, 2), float("nan")])
def test_nonportable_default_is_a_signature_diagnostic_not_a_crash(default):
    lib = Library("host")
    lib.add_signature(Signature("f", (Port("x", default=default),), ()))
    with pytest.raises(KirCheckError, match="nonportable signature default"):
        compile_source(ENTRY, [lib], modules={"lib.kir": LIBRARY})


def _fail(x):
    raise ValueError("synthetic failure")


@pytest.mark.parametrize("passes", [[], ["order_dataflow", "inline", "strip_meta"]])
def test_reference_failure_keeps_definition_and_callsite_origin(passes):
    lib = Library("host")
    lib.add_signature(Signature("fail", (Port("x"),), (Port("y"),)), _fail)
    module = "@export wrapper\n@def (x)wrapper(y):\n    (x)fail(y)\n"
    source = '@import "lib.kir" as lib\n(1)lib.wrapper(result)\n'
    compiled = compile_source(source, [lib], modules={"lib.kir": module}, passes=passes)
    with pytest.raises(NodeFailure) as raised:
        Interpreter(compiled.lowered, compiled.env).run()
    origin = raised.value.origin
    assert origin.module == "lib.kir"
    assert origin.definition == "wrapper"
    assert origin.calls[0].module == "<text>"
    assert origin.calls[0].line == 2


@pytest.mark.parametrize(
    "body",
    [
        "_kir_local = 1\n",
        "@typehint:\n    (int)_kir_fake(int)\n",
        "@def (x: _kir_fake)main(y):\n    y = x\n",
    ],
)
def test_generated_namespace_is_reserved_in_modular_source(body):
    with pytest.raises(KirCheckError, match="reserved prefix"):
        compile_source('@import "lib.kir" as lib\n' + body, modules={"lib.kir": LIBRARY})


def test_filesystem_alias_cycle_is_reported_without_unbounded_recursion(tmp_path):
    (tmp_path / "main.kir").write_text('@import "lib.kir" as lib\n', encoding="utf-8")
    (tmp_path / "lib.kir").write_text('@import "alias/lib.kir" as again\n', encoding="utf-8")
    try:
        (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this platform")
    with pytest.raises(KirCheckError, match="import cycle"):
        compile_file(tmp_path / "main.kir")


def test_signature_paths_and_documentation_do_not_change_dependency_identity(tmp_path):
    sig = Signature("identity", (Port("x"),), (Port("y"),))
    compiled = []
    for name, doc in (("one", "first documentation"), ("two", "updated documentation")):
        folder = tmp_path / name
        folder.mkdir()
        signature = folder / "host.kirsig.json"
        save_library(Library("host", {"identity": replace(sig, doc=doc)}), signature)
        (folder / "lib.kir").write_text(
            f'@use "{signature.as_posix()}" as h\n@export identity\n'
            '@def (x)identity(y):\n    (x)h.identity(y)\n',
            encoding="utf-8",
        )
        (folder / "main.kir").write_text(
            '@import "lib.kir" as lib\n(1)lib.identity(result)\n', encoding="utf-8"
        )
        compiled.append(compile_file(folder / "main.kir"))
    assert compiled[0].dependencies == compiled[1].dependencies
    assert compiled[0].semantic_hash == compiled[1].semantic_hash
