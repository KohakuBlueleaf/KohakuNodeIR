import { reactive, computed } from 'vue';
import { defineStore } from 'pinia';
import { save, load } from '../utils/persist.js';
import { listNodes, registerNode } from '../api/backend.js';

// ---- ID helpers ----
let _portCounter = 0;
function pid(label) {
  return `${label}-${++_portCounter}`;
}

// ---- Built-in node type definitions ----
// Each definition is the canonical template; createNodeData() deep-clones it
// and assigns fresh port ids so every placed node has unique port ids.

/**
 * @typedef {object} PortDef
 * @property {string} id       - template id (re-generated per instance)
 * @property {string} name
 * @property {string} [dataType]
 * @property {*}      [defaultValue]
 */

/**
 * @typedef {object} NodeDefinition
 * @property {string} type
 * @property {string} name
 * @property {string} category
 * @property {string} description
 * @property {{ inputs: PortDef[], outputs: PortDef[] }} dataPorts
 * @property {{ inputs: PortDef[], outputs: PortDef[] }} controlPorts
 * @property {string} [code]   - for user-defined 'function' nodes
 */

/** @type {NodeDefinition[]} */
const BUILT_IN_DEFINITIONS = [
  {
    type: 'branch',
    name: 'Branch',
    category: 'Control Flow',
    description: 'Evaluates a boolean condition and routes control to the true or false output.',
    dataPorts: {
      inputs: [{ id: 'dp-condition', name: 'condition', dataType: 'bool', defaultValue: false }],
      outputs: [],
    },
    controlPorts: {
      inputs: [{ id: 'cp-in', name: 'in' }],
      outputs: [
        { id: 'cp-true',  name: 'true'  },
        { id: 'cp-false', name: 'false' },
      ],
    },
  },
  {
    type: 'merge',
    name: 'Merge',
    category: 'Control Flow',
    description: 'Merges multiple control flows into one. Any incoming execution activates the output.',
    dataPorts: {
      inputs: [],
      outputs: [],
    },
    controlPorts: {
      inputs: [
        { id: 'cp-in-0', name: 'in 0' },
        { id: 'cp-in-1', name: 'in 1' },
      ],
      outputs: [{ id: 'cp-out', name: 'out' }],
    },
  },
  {
    type: 'switch',
    name: 'Switch',
    category: 'Control Flow',
    description: 'Routes control based on the value of a data input. Add case outputs as needed.',
    dataPorts: {
      inputs: [{ id: 'dp-value', name: 'value', dataType: 'any', defaultValue: null }],
      outputs: [],
    },
    controlPorts: {
      inputs: [{ id: 'cp-in', name: 'in' }],
      outputs: [{ id: 'cp-case-0', name: 'case 0' }],
    },
  },
  {
    type: 'parallel',
    name: 'Parallel',
    category: 'Control Flow',
    description: 'Fans out a single control input to multiple parallel outputs simultaneously.',
    dataPorts: {
      inputs: [],
      outputs: [],
    },
    controlPorts: {
      inputs: [{ id: 'cp-in', name: 'in' }],
      outputs: [
        { id: 'cp-out-0', name: 'out 0' },
        { id: 'cp-out-1', name: 'out 1' },
      ],
    },
  },
  {
    type: 'value',
    name: 'Value',
    category: 'Data',
    description: 'Holds a constant value and exposes it as a data output.',
    dataPorts: {
      inputs: [],
      outputs: [{ id: 'dp-out', name: 'value', dataType: 'any' }],
    },
    controlPorts: {
      inputs: [],
      outputs: [],
    },
    properties: { value: 0, valueType: 'int' },
  },
  {
    type: 'code',
    name: 'Code',
    category: 'Advanced',
    description: 'Inline KIR code block. Write KIR directly in the graph.',
    dataPorts: { inputs: [], outputs: [] },
    controlPorts: {
      inputs: [{ id: 'cp-in', name: 'in' }],
      outputs: [{ id: 'cp-out', name: 'out' }],
    },
    properties: { code: '' },
    minWidth: 280,
    minHeight: 240,
  },
  // ── Store / Load (remote data connections) ──
  {
    type: 'store',
    name: 'Store',
    category: 'Data',
    description: 'Store a value under a name. Use Load with the same name to retrieve it elsewhere.',
    dataPorts: {
      inputs: [{ id: 'dp-value', name: 'value', dataType: 'any' }],
      outputs: [],
    },
    controlPorts: {
      inputs: [{ id: 'cp-in', name: 'in' }],
      outputs: [{ id: 'cp-out', name: 'out' }],
    },
  },
  {
    type: 'load',
    name: 'Load',
    category: 'Data',
    description: 'Load a value by name. Must match a Store node with the same name.',
    dataPorts: {
      inputs: [],
      outputs: [{ id: 'dp-value', name: 'value', dataType: 'any' }],
    },
    controlPorts: {
      inputs: [],
      outputs: [],
    },
  },
  // ── Math ──
  {
    type: 'add', name: 'Add', category: 'Math',
    description: 'Add two numbers.',
    dataPorts: {
      inputs: [
        { id: 'dp-a', name: 'a', dataType: 'float', defaultValue: 0 },
        { id: 'dp-b', name: 'b', dataType: 'float', defaultValue: 0 },
      ],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'float' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'subtract', name: 'Subtract', category: 'Math',
    description: 'Subtract b from a.',
    dataPorts: {
      inputs: [
        { id: 'dp-a', name: 'a', dataType: 'float', defaultValue: 0 },
        { id: 'dp-b', name: 'b', dataType: 'float', defaultValue: 0 },
      ],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'float' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'multiply', name: 'Multiply', category: 'Math',
    description: 'Multiply two numbers.',
    dataPorts: {
      inputs: [
        { id: 'dp-a', name: 'a', dataType: 'float', defaultValue: 1 },
        { id: 'dp-b', name: 'b', dataType: 'float', defaultValue: 1 },
      ],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'float' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'divide', name: 'Divide', category: 'Math',
    description: 'Divide a by b.',
    dataPorts: {
      inputs: [
        { id: 'dp-a', name: 'a', dataType: 'float', defaultValue: 1 },
        { id: 'dp-b', name: 'b', dataType: 'float', defaultValue: 1 },
      ],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'float' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  // ── Comparison ──
  {
    type: 'greater_than', name: 'Greater Than', category: 'Comparison',
    description: 'Returns true if a > b.',
    dataPorts: {
      inputs: [
        { id: 'dp-a', name: 'a', dataType: 'float', defaultValue: 0 },
        { id: 'dp-b', name: 'b', dataType: 'float', defaultValue: 0 },
      ],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'bool' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'less_than', name: 'Less Than', category: 'Comparison',
    description: 'Returns true if a < b.',
    dataPorts: {
      inputs: [
        { id: 'dp-a', name: 'a', dataType: 'float', defaultValue: 0 },
        { id: 'dp-b', name: 'b', dataType: 'float', defaultValue: 0 },
      ],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'bool' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'equal', name: 'Equal', category: 'Comparison',
    description: 'Returns true if a == b.',
    dataPorts: {
      inputs: [
        { id: 'dp-a', name: 'a', dataType: 'any' },
        { id: 'dp-b', name: 'b', dataType: 'any' },
      ],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'bool' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'and', name: 'And', category: 'Comparison',
    description: 'Logical AND of two booleans.',
    dataPorts: {
      inputs: [
        { id: 'dp-a', name: 'a', dataType: 'bool', defaultValue: false },
        { id: 'dp-b', name: 'b', dataType: 'bool', defaultValue: false },
      ],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'bool' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'not', name: 'Not', category: 'Comparison',
    description: 'Logical NOT.',
    dataPorts: {
      inputs: [{ id: 'dp-a', name: 'value', dataType: 'bool', defaultValue: false }],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'bool' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  // ── String ──
  {
    type: 'concat', name: 'Concat', category: 'String',
    description: 'Concatenate two strings.',
    dataPorts: {
      inputs: [
        { id: 'dp-a', name: 'a', dataType: 'str', defaultValue: '' },
        { id: 'dp-b', name: 'b', dataType: 'str', defaultValue: '' },
      ],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'str' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'format_string', name: 'Format', category: 'String',
    description: 'Format a string with values.',
    dataPorts: {
      inputs: [
        { id: 'dp-template', name: 'template', dataType: 'str', defaultValue: '{}' },
        { id: 'dp-value', name: 'value', dataType: 'any' },
      ],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'str' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  // ── Display ──
  {
    type: 'print', name: 'Print', category: 'Display',
    description: 'Print a value to the console.',
    dataPorts: {
      inputs: [{ id: 'dp-value', name: 'value', dataType: 'any' }],
      outputs: [],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'display', name: 'Display', category: 'Display',
    description: 'Display a value (shows result in the node).',
    dataPorts: {
      inputs: [{ id: 'dp-value', name: 'value', dataType: 'any' }],
      outputs: [{ id: 'dp-pass', name: 'pass', dataType: 'any' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  // ── File I/O ──
  {
    type: 'read_file', name: 'Read File', category: 'File',
    description: 'Read a file from disk.',
    dataPorts: {
      inputs: [{ id: 'dp-path', name: 'path', dataType: 'str', defaultValue: '' }],
      outputs: [{ id: 'dp-data', name: 'data', dataType: 'any' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'write_file', name: 'Write File', category: 'File',
    description: 'Write data to a file.',
    dataPorts: {
      inputs: [
        { id: 'dp-path', name: 'path', dataType: 'str', defaultValue: '' },
        { id: 'dp-data', name: 'data', dataType: 'any' },
      ],
      outputs: [],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  // ── Convert ──
  {
    type: 'to_int', name: 'To Int', category: 'Convert',
    description: 'Convert value to integer.',
    dataPorts: {
      inputs: [{ id: 'dp-value', name: 'value', dataType: 'any' }],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'int' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'to_float', name: 'To Float', category: 'Convert',
    description: 'Convert value to float.',
    dataPorts: {
      inputs: [{ id: 'dp-value', name: 'value', dataType: 'any' }],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'float' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
  {
    type: 'to_string', name: 'To String', category: 'Convert',
    description: 'Convert value to string.',
    dataPorts: {
      inputs: [{ id: 'dp-value', name: 'value', dataType: 'any' }],
      outputs: [{ id: 'dp-result', name: 'result', dataType: 'str' }],
    },
    controlPorts: { inputs: [{ id: 'cp-in', name: 'in' }], outputs: [{ id: 'cp-out', name: 'out' }] },
  },
];

// ---- Store ----

export const useNodeRegistryStore = defineStore('nodeRegistry', () => {
  // Registry: type key -> NodeDefinition
  // Using a reactive Map so Vue tracks additions
  /** @type {Map<string, NodeDefinition>} */
  const registry = reactive(new Map());

  // Seed built-ins
  for (const def of BUILT_IN_DEFINITIONS) {
    registry.set(def.type, def);
  }

  // ---- Computed ----
  const allDefinitions = computed(() => Array.from(registry.values()));

  const categories = computed(() => {
    const cats = new Set();
    for (const def of registry.values()) {
      cats.add(def.category);
    }
    return Array.from(cats).sort();
  });

  // ---- Methods ----

  /**
   * Register a new node type (or overwrite an existing one).
   * @param {NodeDefinition} definition
   */
  function registerNodeType(definition) {
    if (!definition.type) throw new Error('NodeDefinition must have a type field.');
    registry.set(definition.type, definition);
    _persistUserTypes();
  }

  /** Save user-defined (non-builtin) types to localStorage. */
  function _persistUserTypes() {
    const builtinTypes = new Set(BUILT_IN_DEFINITIONS.map(d => d.type));
    const userDefs = [];
    for (const [type, def] of registry) {
      if (!builtinTypes.has(type)) userDefs.push(def);
    }
    save('userNodeTypes', userDefs);
  }

  /** Load user-defined types from localStorage on store init. */
  function _loadUserTypes() {
    const saved = load('userNodeTypes', []);
    for (const def of saved) {
      if (def.type && !registry.has(def.type)) {
        registry.set(def.type, def);
      }
    }
  }
  _loadUserTypes();

  /**
   * Look up a node type definition by type key.
   * @param {string} type
   * @returns {NodeDefinition|undefined}
   */
  function getNodeType(type) {
    return registry.get(type);
  }

  /**
   * Return an array of unique category names.
   * @returns {string[]}
   */
  function getCategories() {
    return categories.value;
  }

  /**
   * Return all definitions belonging to a given category.
   * @param {string} category
   * @returns {NodeDefinition[]}
   */
  function getNodesByCategory(category) {
    return allDefinitions.value.filter(d => d.category === category);
  }

  /**
   * Deep-clone a port list, assigning fresh unique ids.
   * @param {PortDef[]} ports
   * @returns {PortDef[]}
   */
  function _clonePorts(ports) {
    return ports.map(p => ({ ...p, id: pid(p.name.replace(/\s+/g, '-')) }));
  }

  /**
   * Create a NodeData object ready to pass to graph.addNode().
   * Fresh port ids are generated so every instance has unique ids.
   *
   * @param {string} typeName   - The type key (e.g. 'branch', 'function')
   * @param {number} x          - Canvas X position
   * @param {number} y          - Canvas Y position
   * @param {object} [overrides] - Optional extra fields (name, properties, etc.)
   * @returns {object} NodeData
   */
  function createNodeData(typeName, x, y, overrides = {}) {
    const def = registry.get(typeName);
    if (!def) throw new Error(`Unknown node type: "${typeName}"`);

    // Determine a sensible default size based on port counts
    const maxDataPorts = Math.max(
      (def.dataPorts.inputs.length),
      (def.dataPorts.outputs.length),
    );
    const maxCtrlPorts = Math.max(
      (def.controlPorts.inputs.length),
      (def.controlPorts.outputs.length),
    );
    const ctrlRowH = (def.controlPorts.inputs.length > 0 ? 18 : 0)
      + (def.controlPorts.outputs.length > 0 ? 18 : 0);
    const width  = Math.max(def.minWidth ?? 180, maxCtrlPorts * 60);
    const height = Math.max(def.minHeight ?? 120, maxDataPorts * 28 + ctrlRowH + 60);

    return {
      type: def.type,
      name: def.name,
      x,
      y,
      width,
      height,
      dataPorts: {
        inputs:  _clonePorts(def.dataPorts.inputs),
        outputs: _clonePorts(def.dataPorts.outputs),
      },
      controlPorts: {
        inputs:  _clonePorts(def.controlPorts.inputs),
        outputs: _clonePorts(def.controlPorts.outputs),
      },
      properties: {
        ...(Array.isArray(def.properties)
          ? Object.fromEntries(def.properties.map(p => [p.name, p.default]))
          : def.properties ? { ...def.properties } : {}),
        ...(def.code !== undefined ? { code: def.code } : {}),
      },
      ...overrides,
    };
  }

  async function syncWithBackend() {
    try {
      const nodes = await listNodes();
      for (const def of nodes) {
        if (!registry.has(def.type)) {
          registry.set(def.type, def);
        }
      }
    } catch (e) {
      console.warn('Backend sync failed:', e);
    }
  }

  async function saveToBackend(definition) {
    try {
      await registerNode(definition);
    } catch (e) {
      console.warn('Failed to save node to backend:', e);
    }
  }

  return {
    registry,
    allDefinitions,
    categories,
    registerNodeType,
    getNodeType,
    getCategories,
    getNodesByCategory,
    createNodeData,
    syncWithBackend,
    saveToBackend,
  };
});
