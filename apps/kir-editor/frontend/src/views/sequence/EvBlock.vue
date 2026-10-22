<template>
  <div class="ev-item" draggable="true" :data-kind="kind" @dragstart.stop="onDrag" @dragend="dragState.current = null">
    <!-- ======================================================== blocks -->
    <div v-if="item.t === 'stmt'" class="ev-tile" :class="`ev-cat--${cat}`">
      <div class="ev-tile__top">
        <span :class="icon" class="ev-tile__icon" />
        <span class="ev-tile__name" :title="title">{{ title }}</span>
        <button class="ev-del" title="Delete this block" @click.stop="remove"><span class="i-carbon-close" /></button>
      </div>
      <div class="ev-tile__params">
        <template v-if="s.type === 'call'">
          <EvParam v-for="(a, i) in s.args" :key="i" :expr="a.value" :label="argLabel(a, i)" :type="argType(a, i)" @update="(e) => set(() => (a.value = e))" />
        </template>
        <EvParam v-else-if="s.type === 'assign'" :expr="s.value" label="value" :type="s.vtype" @update="(e) => set(() => (s.value = e))" />
        <EvParam v-else-if="s.type === 'branch'" :expr="s.cond" label="cond" type="bool" @update="(e) => set(() => (s.cond = e))" />
        <EvParam v-else-if="s.type === 'switch'" :expr="s.value" label="value" @update="(e) => set(() => (s.value = e))" />
        <EvParam v-else-if="['each', 'collect'].includes(s.type)" :expr="s.items" label="items" @update="(e) => set(() => (s.items = e))" />
        <span v-else-if="s.type === 'jump'" class="ev-tile__note">{{ s.label }}</span>
        <span v-else-if="s.type === 'typehints'" class="ev-tile__note">{{ s.entries.map((e) => e.name).join(", ") }}</span>
        <span v-else-if="s.type === 'parallel'" class="ev-tile__note">{{ s.labels.join(" · ") }}</span>
        <EvParam v-if="s.type === 'collect'" :expr="s.value" label="capture at body end" @update="(e) => set(() => (s.value = e))" />
      </div>
      <div v-if="plugs.length" class="ev-tile__plugs">
        <span v-for="p in plugs" :key="p.i" class="ev-plug" :data-wr="p.name" :style="{ '--ev-color': colorOf(p.name) }" :title="`output → ${p.name ?? '_'}`">
          <ScratchName :value="p.name" :allow-empty="p.allowEmpty" @update="p.rename" />
        </span>
      </div>
    </div>

    <!-- ======================================================== containers -->
    <div v-else class="ev-cont" :class="`ev-cont--${contKind}`">
      <div class="ev-cont__head">
        <span :class="icon" class="ev-tile__icon" />
        <span class="ev-cont__title">{{ contTitle }}</span>
        <EvParam v-if="item.t === 'group' && s.type === 'branch'" :expr="s.cond" label="cond" type="bool" @update="(e) => set(() => (s.cond = e))" />
        <EvParam v-else-if="item.t === 'group' && s.type === 'switch'" :expr="s.value" label="value" @update="(e) => set(() => (s.value = e))" />
        <template v-else-if="item.t === 'group' && ['each', 'collect'].includes(s.type)">
          <EvParam :expr="s.items" label="items" @update="(e) => set(() => (s.items = e))" />
          <span class="ev-plug" :data-wr="s.item" :style="{ '--ev-color': colorOf(s.item) }" title="item"><ScratchName :value="s.item" allow-empty @update="(n) => set(() => (s.item = n))" /></span>
          <span v-if="s.has_index" class="ev-plug" :data-wr="s.index" :style="{ '--ev-color': colorOf(s.index) }" title="index"><ScratchName :value="s.index" allow-empty @update="(n) => set(() => (s.index = n))" /></span>
        </template>
        <span class="flex-1" />
        <button class="ev-del" title="Delete this block and what it holds" @click.stop="remove"><span class="i-carbon-close" /></button>
      </div>
      <div v-if="lanes.length > 1 && ui.lanes === 'tabs'" class="ev-tabs">
        <button v-for="(l, i) in lanes" :key="i" class="ev-tab" :class="{ 'is-on': tab === i }" @click.stop="tab = i">{{ l.title }}</button>
      </div>
      <div class="ev-lanes">
        <template v-for="(l, i) in lanes" :key="i">
          <div v-if="lanes.length === 1 || ui.lanes === 'stacked' || tab === i" class="ev-lane">
            <div v-if="lanes.length > 1 && ui.lanes === 'stacked'" class="ev-lane__tab">
              {{ l.title }}
              <span v-if="l.plug" class="ev-plug" :data-wr="l.plug.name" :style="{ '--ev-color': colorOf(l.plug.name) }"><ScratchName :value="l.plug.name" allow-empty @update="l.plug.rename" /></span>
            </div>
            <EvSeq :list="l.list" :loops="l.loops" />
          </div>
        </template>
      </div>
      <div v-if="s?.type === 'collect'" class="ev-cont__head">
        <EvParam :expr="s.value" label="capture at body end" @update="(e) => set(() => (s.value = e))" />
        <span class="ev-plug" :data-wr="s.target" :style="{ '--ev-color': colorOf(s.target) }" title="results (after completion)">
          <ScratchName :value="s.target" @update="(n) => set(() => (s.target = n))" />
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, ref } from "vue"

import { shortLiteral } from "@/graph/literal"
import { ITEM_MIME, dragState, removeItem } from "@/program/edit"
import { useStatementTree } from "@/program/useStatementTree"
import { useUiStore } from "@/stores/ui"
import ScratchName from "@/views/blocks/ScratchName.vue"
import EvParam from "@/views/sequence/EvParam.vue"
import EvSeq from "@/views/sequence/EvSeq.vue"
import { EV_COLOR } from "@/views/sequence/evTypes"

/** One EV3 block (a coloured tile with parameter boxes and output plugs) or container (loop, switch, try, …). */
const props = defineProps({
  item: { type: Object, required: true },
  list: { type: Array, required: true },
  loops: { type: Array, default: () => [] },
})

defineOptions({ name: "EvBlock" })

const ctx = useStatementTree()
const ev = inject("ev")
const ui = useUiStore()
const tab = ref(0)

const s = computed(() => props.item.s)
const kind = computed(() => (props.item.t === "stmt" || props.item.t === "group" ? s.value.type : props.item.t))

const cat = computed(() => {
  if (s.value.type === "call") return ctx.category(s.value.name)
  if (s.value.type === "assign") return "var"
  if (s.value.type === "typehints") return "meta"
  return "flow"
})

const ICONS = {
  call: "i-carbon-function",
  assign: "i-carbon-portfolio",
  jump: "i-carbon-renew",
  branch: "i-carbon-flow-connection",
  switch: "i-carbon-tree-view-alt",
  each: "i-carbon-repeat",
  collect: "i-carbon-repeat",
  parallel: "i-carbon-split",
  loop: "i-carbon-renew",
  try: "i-carbon-warning-alt",
  dataflow: "i-carbon-data-share",
  label: "i-carbon-tag",
  typehints: "i-carbon-text-annotation-toggle",
}
const icon = computed(() => ICONS[kind.value] || "i-carbon-function")

const title = computed(() => {
  const st = s.value
  switch (st.type) {
    case "call":
      return st.name
    case "assign":
      return `write ${st.target}`
    case "jump":
      return props.loops.includes(st.label) ? "loop again" : "jump to"
    default:
      return st.type
  }
})

const sig = computed(() => (s.value.type === "call" ? ev.sigOf(s.value.name) : null))

function argLabel(a, i) {
  if (a.key) return a.key
  const positional = s.value.args.slice(0, i).filter((x) => !x.key).length
  return sig.value?.inputs?.[positional]?.name ?? `in${positional}`
}

function argType(a, i) {
  const name = argLabel(a, i)
  return sig.value?.inputs?.find((p) => p.name === name)?.type ?? null
}

/** Output plugs of a tile: each name the block writes. */
const plugs = computed(() => {
  const st = s.value
  if (st.type === "call")
    return st.outs.map((o, i) => ({ i, name: o, allowEmpty: true, rename: (n) => set(() => (st.outs[i] = n)) }))
  if (st.type === "assign" || st.type === "collect") return [{ i: 0, name: st.target, rename: (n) => set(() => (st.target = n)) }]
  return []
})

const colorOf = (name) => EV_COLOR[ev.kinds.value.get(name) || "other"]

const contKind = computed(() => {
  const it = props.item
  if (it.t === "group") return ["each", "collect"].includes(s.value.type) ? "loop" : s.value.type === "parallel" ? "parallel" : "switch"
  return it.t
})

const contTitle = computed(() => {
  const it = props.item
  if (it.t === "group") {
    const st = s.value
    if (["each", "collect"].includes(st.type)) return `${st.type} ${[st.item || "_", ...(st.has_index ? [st.index || "_"] : [])].join(", ")} in`
    return st.type
  }
  if (it.t === "loop") return `loop ${it.ns.label}`
  if (it.t === "label") return `label ${it.ns.label}`
  if (it.t === "try") return "try"
  if (it.t === "dataflow") return "dataflow · in data order"
  return it.t
})

/** The lanes of a container, each a sequence with a title. */
const lanes = computed(() => {
  const it = props.item
  const loops = props.loops
  switch (it.t) {
    case "group": {
      const st = it.s
      return it.arms.map((a) => {
        const label = a.ns.label
        let t = label
        if (st.type === "branch") t = `${label === st.true_label ? "true" : "false"} · ${label}`
        if (st.type === "switch") {
          const c = st.cases.find((x) => x[1] === label)
          t = c ? `${shortLiteral(c[0], 10)} · ${label}` : `default · ${label}`
        }
        return { title: t, list: a.items, loops }
      })
    }
    case "loop":
      return [{ title: it.ns.label, list: it.items, loops: [...loops, it.ns.label] }]
    case "label":
      return [{ title: it.ns.label, list: it.items, loops }]
    case "try":
      return [
        { title: "try", list: it.body, loops },
        {
          title: "except",
          list: it.handler,
          loops,
          plug: { name: it.s.error_name, rename: (n) => set(() => (it.s.error_name = n)) },
        },
      ]
    case "dataflow":
      return [{ title: "dataflow", list: it.body, loops }]
    default:
      return []
  }
})

function set(fn) {
  fn()
  ctx.commit()
}

function remove() {
  removeItem(props.item, props.list)
  ctx.commit()
}

function onDrag(event) {
  dragState.current = { item: props.item, from: props.list }
  event.dataTransfer.setData(ITEM_MIME, "1")
  event.dataTransfer.effectAllowed = "move"
}
</script>
