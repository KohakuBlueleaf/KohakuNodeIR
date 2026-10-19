/**
 * The statement tree a statement view (blocks, sequence) edits, kept in step
 * with the store's AST. An edit changes the tree in place, then `commit()`
 * writes it back as the program (AST -> text -> every view).
 */

import { provide, inject, ref, watch } from "vue"

import { itemFor } from "@/program/create"
import { programTree, treeToAst } from "@/program/structure"
import { useDocumentStore } from "@/stores/document"
import { useLibraryStore } from "@/stores/library"

const KEY = Symbol("kir-statement-tree")

/** Category of a call for colouring: a @def, kir.std, the demo library, or another library. */
export function callCategory(name, doc, lib) {
  const r = lib.resolveCall(name, doc)
  if (r?.kind === "def") return "def"
  if (r?.library === "kir.std") return "std"
  if (r?.library === "demo") return "demo"
  return r ? "ext" : "unknown"
}

export function provideStatementTree() {
  const docStore = useDocumentStore()
  const lib = useLibraryStore()
  const tree = ref(null)
  watch(
    () => docStore.ast,
    (ast) => {
      tree.value = ast ? programTree(ast) : null
    },
    { immediate: true },
  )

  async function commit() {
    if (!tree.value) return false
    return docStore.applyAst(treeToAst(tree.value))
  }

  /** Insert the statement a palette entry stands for at `index` of `list`. */
  function insert(spec, list, index) {
    const item = itemFor(spec, tree.value)
    if (!item) return false
    if (spec.use && !tree.value.uses.some((u) => u.library === spec.use.library)) tree.value.uses.push(spec.use)
    list.splice(index, 0, item)
    commit()
    return true
  }

  const category = (name) => callCategory(name, docStore.doc, lib)
  const ctx = { tree, commit, insert, category }
  provide(KEY, ctx)
  return ctx
}

export const useStatementTree = () => inject(KEY)
