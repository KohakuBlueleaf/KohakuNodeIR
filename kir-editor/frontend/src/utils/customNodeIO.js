/**
 * Export / import utilities for custom node definition packs.
 */

function validateDefinition(def) {
  const required = ['type', 'name', 'category', 'inputs', 'outputs', 'code'];
  for (const field of required) {
    if (!(field in def)) throw new Error(`Missing field: ${field}`);
  }
  return { ...def, properties: def.properties || [] };
}

export function exportNodePack(definitions) {
  return JSON.stringify({
    version: '1.0',
    type: 'kir-node-pack',
    nodes: definitions,
  }, null, 2);
}

export function importNodePack(json) {
  const pack = JSON.parse(json);
  if (pack.type !== 'kir-node-pack') throw new Error('Invalid node pack');
  return pack.nodes.map(validateDefinition);
}
