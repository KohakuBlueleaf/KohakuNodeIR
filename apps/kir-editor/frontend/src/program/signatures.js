/** Signature-file projections for the palette. Raw uploads stay portable kirsig JSON.
 * Schema semantics (defaults, types, references and cycles) are validated by the
 * backend; this boundary validates shape and derives only visible port metadata.
 */
const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/
const RESERVED = new Set(["_", "True", "False", "None"])
const BUILTINS = new Set(["_", "bool", "int", "float", "str", "None", "list", "dict"])
const validName = (name) => typeof name === "string" && IDENT.test(name) && !RESERVED.has(name)

export function validateSignatureFile(data) {
  if (![1, 2].includes(data?.kirsig) || typeof data.library !== "string" || !data.library || !Array.isArray(data.nodes))
    throw new Error("not a .kirsig.json file (kirsig 1 or 2)")
  const records = data.records === undefined ? [] : data.records
  if (!Array.isArray(records) || (data.kirsig === 1 && records.length))
    throw new Error("record schemas require kirsig 2 and a records array")
  const names = new Set()
  for (const node of data.nodes) {
    if (!node || typeof node.name !== "string" || names.has(node.name)
      || (node.inputs !== undefined && !Array.isArray(node.inputs))
      || (node.outputs !== undefined && !Array.isArray(node.outputs)))
      throw new Error("signature nodes must have unique names")
    for (const port of [...(node.inputs || []), ...(node.outputs || [])]) {
      if (!port || typeof port !== "object" || typeof port.name !== "string"
        || (port.type !== undefined && typeof port.type !== "string"))
        throw new Error("signature ports need a name and an optional type string")
    }
    names.add(node.name)
  }
  const add = (name) => {
    if (names.has(name)) throw new Error(`duplicate record or generated node: ${name}`)
    names.add(name)
  }
  for (const record of records) {
    if (!record || !validName(record.name) || BUILTINS.has(record.name) || !Array.isArray(record.fields))
      throw new Error("record schemas need a name and fields array")
    add(record.name)
    add(`${record.name}.make`)
    const fields = new Set()
    for (const field of record.fields) {
      if (!field || !validName(field.name) || typeof field.type !== "string" || !field.type.trim() || fields.has(field.name))
        throw new Error("record fields need unique names and explicit type strings")
      recordType(field.type, data.library)
      fields.add(field.name)
      add(`${record.name}.get.${field.name}`)
      add(`${record.name}.with.${field.name}`)
    }
  }
  return data
}

// Only a display projection of the portable field-type grammar. The backend
// remains authoritative for allowed containers, nominal references and defaults.
function recordType(text, library) {
  const tokens = text.match(/[A-Za-z_][A-Za-z0-9_.]*|[\[\],|?]/g) || []
  if (tokens.join("") !== text.replace(/\s/g, "")) throw new Error(`invalid record field type: ${text}`)
  let at = 0
  const atom = () => {
    const name = tokens[at++]
    if (!name || !/^[A-Za-z_][A-Za-z0-9_.]*$/.test(name)) throw new Error(`invalid record field type: ${text}`)
    if (name === "_") return { kind: "name", name }
    let type = { kind: "name", name }
    if (tokens[at] === "[") {
      at++
      const args = [union()]
      while (tokens[at] === ",") { at++; args.push(union()) }
      if (tokens[at++] !== "]") throw new Error(`invalid record field type: ${text}`)
      type = { kind: "generic", name, args }
    }
    if (tokens[at] === "?") {
      at++
      if (name !== "None" || type.kind !== "name") type = { kind: "optional", args: [type] }
    }
    return type
  }
  const union = () => {
    const args = [atom()]
    while (tokens[at] === "|") { at++; args.push(atom()) }
    const unique = [...new Map(args.map((arg) => [JSON.stringify(arg), arg])).values()]
    return unique.length === 1 ? unique[0] : { kind: "union", args: unique }
  }
  const type = union()
  if (at !== tokens.length) throw new Error(`invalid record field type: ${text}`)
  const emit = (value) => {
    if (value.kind === "union") return value.args.map(emit).join(" | ")
    if (value.kind === "optional") return `${emit(value.args[0])}?`
    if (value.kind === "generic") return `${value.name}[${value.args.map(emit).join(", ")}]`
    return !value.name.includes(".") && !BUILTINS.has(value.name) ? `${library}.${value.name}` : value.name
  }
  return emit(type)
}

export function projectLibraries(catalog, uploaded) {
  // The backend also gives uploaded libraries precedence over on-disk signatures.
  const names = new Set(uploaded.map((lib) => lib.library))
  return [
    ...catalog.filter((lib) => !names.has(lib.library)),
    ...uploaded.map((lib) => ({ ...lib, source: "loaded file", runnable: false })),
  ].map(expandRecordSignatures)
}

export function expandRecordSignatures(data) {
  if (!data.records?.length) return data
  const local = new Set(data.records.map((r) => r.name))
  const qualify = (text, all = false) => text?.replace(/[A-Za-z_][A-Za-z0-9_.]*/g, (name) =>
    !name.includes(".") && !BUILTINS.has(name) && (all || local.has(name)) ? `${data.library}.${name}` : name)
  const nodes = data.nodes.map((node) => ({
    ...node,
    inputs: (node.inputs || []).map((port) => ({ ...port, ...(port.type ? { type: qualify(port.type) } : {}) })),
    outputs: (node.outputs || []).map((port) => ({ ...port, ...(port.type ? { type: qualify(port.type) } : {}) })),
  }))
  const port = (name, text) => {
    const type = recordType(text, data.library)
    return { name, ...(type === "_" ? {} : { type }) }
  }
  for (const schema of data.records) {
    const record = { name: "record", type: `${data.library}.${schema.name}` }
    nodes.push({
      name: `${schema.name}.make`,
      inputs: schema.fields.map((field) => ({ ...port(field.name, field.type), ...("default" in field ? { default: field.default } : {}) })),
      outputs: [{ ...record }],
    })
    for (const field of schema.fields) {
      const value = port("value", field.type)
      nodes.push({ name: `${schema.name}.get.${field.name}`, inputs: [{ ...record }], outputs: [{ ...value }] })
      nodes.push({ name: `${schema.name}.with.${field.name}`, inputs: [{ ...record }, { ...value }], outputs: [{ ...record }] })
    }
  }
  return { ...data, nodes, runnable: data.runnable || data.nodes.length === 0 }
}
