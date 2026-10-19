// The golden corpus through the wasm build, byte for byte (see rust/README.md):
//   node rust/tests/wasm/golden.cjs [path/to/kohakunode_rs.js]
const fs = require("fs");
const path = require("path");

const pkgPath = process.argv[2] || path.join(__dirname, "../../target/wasm-node/kohakunode_rs.js");
const kir = require(path.resolve(pkgPath));
const casesDir = path.join(__dirname, "../../../tests/corpus/golden/cases");

const read = (file) => fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n");

let cases = 0;
const failures = [];
for (const name of fs.readdirSync(casesDir).sort()) {
  const d = path.join(casesDir, name);
  if (!fs.statSync(d).isDirectory()) continue;
  cases += 1;
  const src = read(path.join(d, "input.kir"));
  const sigs = [read(path.join(d, "sig.kirsig.json"))];
  const hashes = JSON.parse(read(path.join(d, "hashes.json")));
  const graphs = { wires: kir.toGraph(src, sigs, undefined), variables: kir.toGraph(src, sigs, "variables") };
  const got = {
    "canonical.kir": kir.format(src),
    "lowered.kir": kir.lower(src, sigs, undefined),
    "graph.kirgraph": graphs.wires,
    "graph.variables.kirgraph": graphs.variables,
  };
  for (const [file, text] of Object.entries(got)) {
    if (text !== read(path.join(d, file))) failures.push(`${name} ${file}`);
  }
  const h = JSON.parse(kir.hashes(src, sigs, undefined));
  if (h.semantic !== hashes.semantic || h.full !== hashes.full) failures.push(`${name} hashes`);
  for (const [data, graph] of Object.entries(graphs)) {
    try {
      const t1 = kir.fromGraph(graph, true);
      if (kir.fromGraph(kir.toGraph(t1, sigs, data), true) !== t1) failures.push(`${name} round trip (${data})`);
    } catch (e) {
      failures.push(`${name} round trip (${data}): ${e}`);
    }
  }
}
let unknownStyle = false;
try {
  kir.toGraph("x = 1\n", [], "wire");
} catch (e) {
  unknownStyle = String(e).startsWith("Error: ValueError");
}
if (!unknownStyle) failures.push("an unknown data style is not a ValueError");
let rejected = false;
try {
  kir.format("True = 1\n");
} catch (e) {
  rejected = String(e).startsWith("Error: KirSyntaxError");
}
if (!rejected) failures.push("syntax errors are not raised as KirSyntaxError");
console.log(`${cases} cases, ${failures.length} failures`);
for (const f of failures) console.log("  " + f);
process.exit(failures.length || cases !== 46 ? 1 : 0);
