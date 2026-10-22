// K4 parse/check/graph/lowering through actual WebAssembly.
const assert = require('node:assert/strict');
const path = require('node:path');
const kir = require(path.resolve(process.argv[2] || path.join(__dirname, '../../target/wasm-node/kohakunode_rs.js')));
const source = 'xs = [1, 2]\n(xs)collect(x, i, `body`, value -> results)\nbody:\n    (x, i)add(value)\n(results)len(count)\n';
assert.equal(kir.format(source), source);
assert.deepEqual(JSON.parse(kir.check(source, [])), []);
const ast = JSON.parse(kir.parseToJson(source));
assert.equal(ast.body[1].kind, 'collect');
assert.equal(ast.body[1].target, 'results');
for (const style of ['wires', 'variables']) {
  const graph = JSON.parse(kir.toGraph(source, [], style));
  const node = graph.graphs[0].nodes.find(n => n.kind === 'collect');
  assert.equal(node.inputs.find(p => p.port === 'value').deferred, 'body_end');
  assert(node.outputs.some(p => p.port === 'results'));
  assert.equal(kir.fromGraph(JSON.stringify(graph), false), source);
}
const expanded = kir.lower(source, [], ['expand_collect']);
assert(expanded.includes('kir.collect_append'));
assert(expanded.includes('results = collect__1__values'));
assert(!expanded.includes(')collect('));
assert.throws(() => kir.lower(source, [], ['expand_each']), /needs 'expand_collect'/);
const complete = JSON.parse(kir.compileModules(source, '{}', 'main.kir', [], undefined));
assert(complete.lowered_text.includes('kir.collect_append'));
const walk = items => items.flatMap(s => [s, ...walk(s.body || []), ...walk(s.handler || [])]);
assert(walk(complete.lowered.body).some(s => s.origin?.generated === 'collect.append'));
const bad = '([1])collect(x, `body`, x -> results)\nbody:\n    results = x\n';
assert(JSON.parse(kir.check(bad, [])).some(d => d.code === 'E070'));
console.log('WASM collect: syntax, checker, deferred graph, passes, hashes, origins passed');
