<template>
  <div class="sb-item group/sb" draggable="true" :data-kind="kind" @dragstart.stop="onDrag" @dragend="dragState.current = null">
    <!-- ======================================================== command blocks -->
    <div v-if="item.t === 'stmt'" class="sb-block sb-cmd" :class="[`sb-cat--${cat}`, { 'sb-cap': s.type === 'jump' }]">
      <template v-if="s.type === 'call'">
        <span class="sb-text sb-text--name">{{ s.name }}</span>
        <template v-for="(a, i) in s.args" :key="i">
          <span v-if="a.key" class="sb-text sb-text--key">{{ a.key }}:</span>
          <ScratchSlot :expr="a.value" :placeholder="'?'" @update="(e) => set(() => (a.value = e))" />
        </template>
        <template v-if="s.outs.length">
          <span class="sb-text sb-text--arrow">→</span>
          <ScratchName v-for="(o, i) in s.outs" :key="`o${i}`" :value="o" allow-empty title="output name (empty: discard _)" @update="(n) => set(() => (s.outs[i] = n))" />
        </template>
      </template>
      <template v-else-if="s.type === 'assign'">
        <span class="sb-text">set</span>
        <ScratchName :value="s.target" @update="(n) => set(() => (s.target = n))" />
        <span class="sb-text">to</span>
        <ScratchSlot :expr="s.value" @update="(e) => set(() => (s.value = e))" />
      </template>
      <template v-else-if="s.type === 'jump'">
        <span class="i-carbon-renew text-xs" />
        <span class="sb-text">{{ loops.includes(s.label) ? "repeat loop" : "jump to" }}</span>
        <ScratchName :value="s.label" kind="label" @update="(n) => set(() => (s.label = n))" />
      </template>
      <template v-else-if="s.type === 'typehints'">
        <span class="sb-text">typehint</span>
        <span v-for="e in s.entries" :key="e.name" class="sb-text sb-text--mono">({{ e.inputs.join(", ") }}){{ e.name }}({{ e.outputs.join(", ") }})</span>
      </template>
      <template v-else-if="s.type === 'branch'">
        <span class="sb-text">branch</span>
        <ScratchSlot :expr="s.cond" shape="hex" @update="(e) => set(() => (s.cond = e))" />
        <span class="sb-text">→ {{ s.true_label }} / {{ s.false_label }}</span>
      </template>
      <template v-else-if="s.type === 'switch'">
        <span class="sb-text">switch</span>
        <ScratchSlot :expr="s.value" @update="(e) => set(() => (s.value = e))" />
        <span class="sb-text">→ {{ [...s.cases.map((c) => c[1]), s.default].filter(Boolean).join(" / ") }}</span>
      </template>
      <template v-else-if="s.type === 'parallel'">
        <span class="sb-text">parallel → {{ s.labels.join(" / ") }}</span>
      </template>
      <template v-else-if="s.type === 'each'">
        <span class="sb-text">each {{ s.item }} in</span>
        <ScratchSlot :expr="s.items" @update="(e) => set(() => (s.items = e))" />
        <span class="sb-text">→ {{ s.label }}</span>
      </template>
      <span v-if="s.hint" class="sb-text sb-text--hint" :title="hintText">@hint</span>
      <button class="sb-del" title="Delete this block" @click.stop="remove"><span class="i-carbon-close" /></button>
    </div>

    <!-- ======================================================== C blocks -->
    <div v-else class="sb-c" :class="`sb-cat--${cat}`">
      <template v-for="(m, i) in mouths" :key="i">
        <div class="sb-block sb-c__bar" :class="i === 0 ? 'sb-c__bar--top' : 'sb-c__bar--mid'">
          <template v-if="i === 0">
            <!-- the construct's own header -->
            <template v-if="item.t === 'group' && s.type === 'branch'">
              <span class="sb-text">if</span>
              <ScratchSlot :expr="s.cond" shape="hex" @update="(e) => set(() => (s.cond = e))" />
            </template>
            <template v-else-if="item.t === 'group' && s.type === 'switch'">
              <span class="sb-text">switch</span>
              <ScratchSlot :expr="s.value" @update="(e) => set(() => (s.value = e))" />
            </template>
            <template v-else-if="item.t === 'group' && s.type === 'each'">
              <span class="i-carbon-repeat text-xs" />
              <span class="sb-text">for each</span>
              <ScratchName :value="s.item" allow-empty @update="(n) => set(() => (s.item = n))" />
              <template v-if="s.has_index">
                <span class="sb-text">,</span>
                <ScratchName :value="s.index" allow-empty @update="(n) => set(() => (s.index = n))" />
              </template>
              <span class="sb-text">in</span>
              <ScratchSlot :expr="s.items" @update="(e) => set(() => (s.items = e))" />
            </template>
            <template v-else-if="item.t === 'group' && s.type === 'parallel'">
              <span class="i-carbon-split text-xs" />
              <span class="sb-text">run in parallel</span>
            </template>
            <template v-else-if="item.t === 'loop'">
              <span class="i-carbon-renew text-xs" />
              <span class="sb-text">loop</span>
              <ScratchName :value="item.ns.label" kind="label" @update="(n) => renameLoop(n)" />
            </template>
            <template v-else-if="item.t === 'label'">
              <span class="i-carbon-tag text-xs" />
              <span class="sb-text">label</span>
              <ScratchName :value="item.ns.label" kind="label" @update="(n) => set(() => (item.ns.label = n))" />
            </template>
            <template v-else-if="item.t === 'try'">
              <span class="i-carbon-warning-alt text-xs" />
              <span class="sb-text">try</span>
            </template>
            <template v-else-if="item.t === 'dataflow'">
              <span class="i-carbon-data-share text-xs" />
              <span class="sb-text">dataflow (in data order)</span>
            </template>
            <span v-if="s?.hint" class="sb-text sb-text--hint" :title="hintText">@hint</span>
            <button class="sb-del" title="Delete this block and what it holds" @click.stop="remove"><span class="i-carbon-close" /></button>
          </template>
          <!-- the arm header -->
          <template v-if="m.head">
            <template v-if="m.head.kind === 'case'">
              <span class="sb-text">case</span>
              <ScratchSlot :expr="{ lit: s.cases[m.head.index][0] }" @update="(e) => setCase(m.head.index, e)" />
            </template>
            <span v-else class="sb-text">{{ m.head.text }}</span>
            <ScratchName v-if="m.head.name !== undefined" :value="m.head.name" :allow-empty="m.head.allowEmpty" :kind="m.head.nameKind || 'var'" @update="m.head.rename" />
            <span v-if="m.head.label" class="sb-label" title="the namespace this arm is">{{ m.head.label }}</span>
          </template>
        </div>
        <div class="sb-c__mouth">
          <div class="sb-c__spine" />
          <ScratchStack :list="m.list" :loops="m.loops" />
        </div>
      </template>
      <div class="sb-block sb-c__bar sb-c__bar--bottom">
        <span v-if="item.t === 'loop'" class="sb-text sb-text--foot">↺ repeats when the body jumps to {{ item.ns.label }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"

import { dragState, ITEM_MIME, removeItem } from "@/program/edit"
import { useStatementTree } from "@/program/useStatementTree"
import ScratchName from "@/views/blocks/ScratchName.vue"
import ScratchSlot from "@/views/blocks/ScratchSlot.vue"
import ScratchStack from "@/views/blocks/ScratchStack.vue"

/** One Scratch block: a command, or a C block holding stacks (if / else, switch, loops, try, dataflow). */
const props = defineProps({
  item: { type: Object, required: true },
  list: { type: Array, required: true },
  loops: { type: Array, default: () => [] },
})

defineOptions({ name: "ScratchBlock" })

const ctx = useStatementTree()
const s = computed(() => props.item.s)
const kind = computed(() => (props.item.t === "stmt" || props.item.t === "group" ? s.value.type : props.item.t))

const cat = computed(() => {
  const t = props.item.t
  if (t === "stmt") {
    if (s.value.type === "call") return ctx.category(s.value.name)
    if (s.value.type === "assign") return "var"
    if (s.value.type === "typehints") return "meta"
    return "control"
  }
  if (t === "try") return "try"
  if (t === "dataflow") return "dataflow"
  return "control"
})

const hintText = computed(() =>
  Object.entries(s.value?.hint || {})
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(" "),
)

/** The stacks a C block holds, each with the header bar above it. */
const mouths = computed(() => {
  const it = props.item
  const loops = props.loops
  switch (it.t) {
    case "group": {
      const st = it.s
      return it.arms.map((a) => {
        const label = a.ns.label
        let head = null
        if (st.type === "branch") head = { text: label === st.true_label ? "then" : "else", label }
        else if (st.type === "switch") {
          const index = st.cases.findIndex((c) => c[1] === label)
          head = index >= 0 ? { kind: "case", index, label } : { text: "default", label }
        } else if (st.type === "parallel") head = { text: "arm", label }
        else if (st.type === "each") head = { text: "do", label }
        return { list: a.items, loops, head }
      })
    }
    case "loop":
      return [{ list: it.items, loops: [...loops, it.ns.label] }]
    case "label":
      return [{ list: it.items, loops }]
    case "try":
      return [
        { list: it.body, loops },
        {
          list: it.handler,
          loops,
          head: { text: "except", name: it.s.error_name, allowEmpty: true, rename: (n) => set(() => (it.s.error_name = n)) },
        },
      ]
    case "dataflow":
      return [{ list: it.body, loops }]
    default:
      return []
  }
})

function set(fn) {
  fn()
  ctx.commit()
}

function setCase(index, e) {
  if (!e || !("lit" in e)) return
  set(() => (s.value.cases[index][0] = e.lit))
}

/** A loop's label is written twice (the entering jump and the namespace): rename both, and the jumps back. */
function renameLoop(name) {
  const old = props.item.ns.label
  const walk = (items) => {
    for (const it of items) {
      if (it.t === "stmt" && it.s.type === "jump" && it.s.label === old) it.s.label = name
      for (const l of it.t === "group" ? it.arms.map((a) => a.items) : [it.items, it.body, it.handler].filter(Boolean)) walk(l)
    }
  }
  set(() => {
    props.item.s.label = name
    props.item.ns.label = name
    walk(props.item.items)
  })
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
