// K3 record schemas are parsed/generated/checked without host filesystem access.
const assert = require('node:assert/strict');
const path = require('node:path');
const kir = require(path.resolve(process.argv[2] || path.join(__dirname, '../../target/wasm-node/kohakunode_rs.js')));
const contract = {kirsig: 2, library: 'geometry', nodes: [], records: [{name: 'Point', fields: [
  {name: 'x', type: 'float'}, {name: 'y', type: 'float', default: 0}, {name: 'label', type: 'str?', default: null}
]}]};
const sigs = [JSON.stringify(contract)];
const source = '@use "geometry" as g\n@def (p: g.Point)read(x: float):\n    (p)g.Point.get.x(x)\n(1)g.Point.make(p)\n(p)read(x)\n(p, 3)g.Point.with.x(q)\n';
assert.deepEqual(JSON.parse(kir.check(source, sigs)), []);
const compiled = JSON.parse(kir.compileModules(source, '{}', '<text>', sigs, undefined));
assert(compiled.text.includes('p: geometry.Point'));
assert.equal(compiled.dependencies.modules.length, 0);
assert.equal(compiled.dependencies.signatures.length, 1);
const graph = JSON.parse(kir.toGraph(source, sigs, 'wires'));
assert(graph.graphs[0].nodes.some(n => n.name === 'g.Point.make' && n.outputs[0].type === 'geometry.Point'));
const revised = structuredClone(contract);
revised.records[0].fields[1].default = 1;
const changed = JSON.parse(kir.compileModules(source, '{}', '<text>', [JSON.stringify(revised)], undefined));
assert.notEqual(changed.semantic, compiled.semantic);
assert.equal(changed.lowered_text, compiled.lowered_text);
const bad = structuredClone(contract);
bad.records[0].fields[0].default = true;
assert.throws(() => kir.check('x = 1\n', [JSON.stringify(bad)]), /does not match its type/);
const unknown = structuredClone(contract);
unknown.records[0].fields[0].type = 'Missing';
assert(JSON.parse(kir.check('x = 1\n', [JSON.stringify(unknown)]))[0].message.includes('unknown schema'));
console.log('WASM records: generated nodes, canonical annotations, graph ports, schema hashes, strict validation passed');
