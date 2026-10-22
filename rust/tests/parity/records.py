"""K3 schema/generated-signature parity against the native extension.

Use --extension /absolute/path/to/kohakunode_rs.dll for an uninstalled build.
"""
import argparse
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))
parser = argparse.ArgumentParser()
parser.add_argument('--extension')
args = parser.parse_args()
if args.extension:
    loader = importlib.machinery.ExtensionFileLoader('kohakunode._rs', str(Path(args.extension).resolve()))
    spec = importlib.util.spec_from_loader('kohakunode._rs', loader)
    native = importlib.util.module_from_spec(spec)
    loader.exec_module(native)
    sys.modules['kohakunode._rs'] = native

from kohakunode import _rs, compile_source, parse, write
from kohakunode.check import check
from kohakunode.graph import from_graph, to_graph
from kohakunode.sig.env import build_env
from kohakunode.sig.files import library_from_json, library_to_json

POINT = {'kirsig': 2, 'library': 'geometry', 'nodes': [], 'records': [
    {'name': 'Point', 'fields': [
        {'name': 'x', 'type': 'float'}, {'name': 'y', 'type': 'float', 'default': 0},
        {'name': 'label', 'type': 'str?', 'default': None},
    ]},
    {'name': 'Collection', 'fields': [
        {'name': 'points', 'type': 'list[Point]'},
        {'name': 'tags', 'type': 'dict[str, str]', 'default': {'雪': 'café 😀'}},
        {'name': 'extra', 'type': '_', 'default': [1e-7, 1e20, -0.0, {'a': True}]},
    ]},
]}

sources = [
    '@use "geometry" as g\n(1)g.Point.make(p)\n(p)g.Point.get.x(x)\n(p, 3)g.Point.with.x(q)\n',
    '@use "geometry"\n(1, 2, "name")Point.make(p)\n(p, None)Point.with.label(q)\n',
    '@use "geometry" as g\n([])g.Collection.make(items)\n(items)g.Collection.get.tags(tags)\n',
    '@use "geometry" as g\n@def (p: g.Point)read(x: float):\n    (p)g.Point.get.x(x)\n(1)g.Point.make(p)\n(p)read(x)\n',
    '@use "geometry"\n@def (p: Point)read(x: float):\n    (p)Point.get.x(x)\n(1)Point.make(p)\n(p)read(x)\n',
    '@use "geometry" as g\n@typehint:\n    (g.Point)custom(float)\n(1)g.Point.make(p)\n(p)custom(x)\n',
    '@use "geometry" as g\n()g.Point.make(p)\n',
    '@use "geometry" as g\n("bad")g.Point.make(p)\n',
    '@use "geometry" as g\n(1)g.Point.make(p)\n(p)g.Point.get.absent(x)\n',
    '@use "geometry" as g\n(1)g.Point.make(p)\n(p, "bad")g.Point.with.x(q)\n',
]
checks = 0
for source in sources:
    lib = library_from_json(POINT)
    text = json.dumps(POINT, ensure_ascii=False)
    program = parse(source)
    env = build_env(program, [lib])
    expected = [{'code': d.code, 'message': d.message, 'line': d.line, 'severity': d.severity} for d in check(program, env)]
    assert json.loads(_rs.check(source, [text])) == expected, (source, 'diagnostics')
    for style in ['wires', 'variables']:
        expected_graph = to_graph(program, env, data=style)
        got_graph = json.loads(_rs.to_graph(source, [text], data=style))
        assert got_graph == expected_graph, (source, style, 'graph')
        for meta in [False, True]:
            assert _rs.from_graph(json.dumps(got_graph), meta) == write(from_graph(expected_graph, with_meta=meta))
    if not any(d['severity'] == 'error' for d in expected):
        for passes in [[], ['order_dataflow', 'inline'], None]:
            compiled = compile_source(source, libraries=[lib], passes=passes)
            got = json.loads(_rs.compile_modules(source, '{}', sigs=[text], passes=passes))
            assert got['lowered_text'] == write(compiled.lowered), 'lowering'
            assert got['semantic'] == compiled.semantic_hash, 'semantic hash'
            assert got['full'] == compiled.full_hash, 'full hash'
    checks += 1

modules = {'lib.kir': '@use "geometry" as g\n@export point\n@def (x: float)point(p: geometry.Point):\n    (x)g.Point.make(p)\n'}
source = '@import "lib.kir" as lib\n(3)lib.point(p)\n'
compiled = compile_source(source, libraries=[library_from_json(POINT)], modules=modules, source_name='main.kir')
got = json.loads(_rs.compile_modules(source, json.dumps(modules), 'main.kir', sigs=[json.dumps(POINT)]))
assert got['dependencies'] == compiled.dependencies, 'record dependency identity'
assert got['semantic'] == compiled.semantic_hash
assert got['full'] == compiled.full_hash
checks += 1

for record in [
    {'name': 'Bad', 'fields': [{'name': 'x', 'type': 'int', 'default': True}]},
    {'name': 'Bad', 'fields': [{'name': 'x', 'type': 'str', 'default': None}]},
    {'name': 'Bad', 'fields': [{'name': 'x', 'type': 'float', 'default': float('nan')}]},
    {'name': 'Bad', 'fields': [{'name': 'x', 'type': 'Point', 'default': {}}]},
    {'name': 'Bad', 'fields': [{'name': 'x'}, {'name': 'x'}]},
    {'name': 'Bad', 'fields': [{'name': '_', 'type': 'int'}]},
    {'name': 'Bad', 'fields': [{'name': 'x', 'type': 'int'}, {'name': 'x', 'type': 'str'}]},
    {'name': 'Bad', 'fields': [{'name': 'x', 'type': 'Box[int]'}]},
    {'name': 'Bad', 'fields': [{'name': 'x', 'type': 'dict[int, str]'}]},
    {'name': 'Bad', 'fields': [{'name': 'x', 'type': 'list[int, str]'}]},
    {'name': 'Bad', 'fields': [{'name': 'self', 'type': 'Bad?'}]},
    {'name': 'list', 'fields': []},
]:
    data = {'kirsig': 2, 'library': 'geometry', 'nodes': [], 'records': [record]}
    try:
        library_from_json(data)
    except Exception as exc:
        expected = str(exc)
    else:
        raise AssertionError(('Python accepted invalid record', record))
    try:
        _rs.check('x = 1\n', [json.dumps(data)])
    except Exception as exc:
        assert str(exc) == expected, (record, str(exc), expected)
    else:
        raise AssertionError(('Rust accepted invalid record', record))
    checks += 1
def schema_library(name, record, fields):
    return {'kirsig': 2, 'library': name, 'nodes': [], 'records': [{'name': record, 'fields': fields}]}

for source, contracts in [
    ('x = 1\n', [schema_library('a', 'A', [{'name': 'b', 'type': 'b.B?'}])]),
    ('x = 1\n', [schema_library('a', 'A', [{'name': 'b', 'type': 'b.B?'}]), schema_library('b', 'B', [{'name': 'a', 'type': 'list[a.A]'}])]),
    ('@def (p: Point)f(q: Point):\n    q = p\n', [schema_library('a', 'Point', []), schema_library('b', 'Point', [])]),
]:
    try:
        compile_source(source, libraries=[library_from_json(c) for c in contracts])
    except Exception as exc:
        expected = str(exc)
    else:
        raise AssertionError('Python accepted invalid record environment')
    try:
        _rs.compile_modules(source, '{}', sigs=[json.dumps(c) for c in contracts])
    except Exception as exc:
        assert str(exc) == expected, (source, expected, str(exc))
    else:
        raise AssertionError('Rust accepted invalid record environment')
    checks += 1

# Source exports retain host-record identity through both signature and source aliases.
for exported_type in ['geometry.Point', 'g.Point']:
    modules = {'lib.kir': f'@use "geometry" as g\n@export point\n@def (x: float)point(p: {exported_type}):\n    (x)g.Point.make(p)\n'}
    source = f'@import "lib.kir" as lib\n@def ()main(p: lib.{exported_type}):\n    (3)lib.point(p)\n'
    compiled = compile_source(source, libraries=[library_from_json(POINT)], modules=modules, source_name='main.kir')
    got = json.loads(_rs.compile_modules(source, json.dumps(modules), 'main.kir', sigs=[json.dumps(POINT)]))
    assert got['dependencies'] == compiled.dependencies
    assert got['text'] == write(compiled.program)
    assert got['lowered_text'] == write(compiled.lowered)
    assert got['semantic'] == compiled.semantic_hash
    checks += 1

# Contract docs/node/record declaration order are nonsemantic; defaults and
# field declaration order remain semantic.
import copy
base = copy.deepcopy(POINT)
base['nodes'] = [{'name': 'z', 'inputs': [], 'outputs': [], 'doc': 'first'}, {'name': 'a', 'inputs': [], 'outputs': []}]
variants = [base]
reordered = copy.deepcopy(base)
reordered['nodes'].reverse()
reordered['nodes'][1]['doc'] = 'different documentation'
variants.append(reordered)
changed = copy.deepcopy(base)
changed['records'][0]['fields'][1]['default'] = 99
variants.append(changed)
reordered_records = copy.deepcopy(base)
reordered_records['records'].reverse()
variants.append(reordered_records)
identities = []
for contract in variants:
    source = '@use "geometry" as g\n(1)g.Point.make(p)\n'
    compiled = compile_source(source, libraries=[library_from_json(contract)])
    got = json.loads(_rs.compile_modules(source, '{}', sigs=[json.dumps(contract)]))
    assert got['dependencies'] == compiled.dependencies
    assert got['semantic'] == compiled.semantic_hash
    assert got['full'] == compiled.full_hash
    identities.append(got['semantic'])
    checks += 1
assert identities[0] == identities[1]
assert identities[0] != identities[2]
assert identities[0] == identities[3]

# Resolve record references against the complete signature closure, including
# contracts loaded only through an imported source module.
import tempfile
with tempfile.TemporaryDirectory(dir=REPO / 'rust' / 'target') as directory:
    root = Path(directory)
    request = schema_library('requests', 'Request', [{'name': 'point', 'type': 'geometry.Point'}])
    (root / 'request.kirsig.json').write_text(json.dumps(request), encoding='utf-8')
    (root / 'geometry.kirsig.json').write_text(json.dumps(POINT), encoding='utf-8')
    (root / 'lib.kir').write_text('@use "geometry.kirsig.json" as g\n@export point\n@def ()point(p: g.Point):\n    (1)g.Point.make(p)\n', encoding='utf-8')
    source = '@use "request.kirsig.json" as r\n@import "lib.kir" as lib\n()lib.point(p)\n(p)r.Request.make(request)\n'
    compiled = compile_source(source, base_dir=root, source_name='main.kir')
    got = json.loads(_rs.compile_modules(source, None, 'main.kir', base=root))
    assert got['dependencies'] == compiled.dependencies
    assert got['lowered_text'] == write(compiled.lowered)
    assert got['semantic'] == compiled.semantic_hash
    checks += 1

print(f'Record schema parity: {checks} cases passed')
