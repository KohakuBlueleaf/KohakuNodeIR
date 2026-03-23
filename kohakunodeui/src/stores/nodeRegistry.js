import { reactive, computed } from 'vue';
import { defineStore } from 'pinia';

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
  }

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
    const width  = Math.max(160, maxCtrlPorts * 60);
    const height = Math.max(100, maxDataPorts * 30 + 60);

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
        ...(def.code !== undefined ? { code: def.code } : {}),
      },
      ...overrides,
    };
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
  };
});
