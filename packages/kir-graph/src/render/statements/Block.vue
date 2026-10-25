<template>
  <!-- ======================================================== jump back (a cap: nothing follows it) -->
  <div v-if="item.t === 'jump'" class="kg-block kg-block--cap kg-tone--iolite" :title="`jump back to the loop ${node.props?.label}`" @click.stop="pick">
    <Icon name="renew" class="kg-block__icon" />
    <span class="kg-block__text">jump back to</span>
    <span class="kg-block__label">{{ node.props?.label }}</span>
  </div>

  <!-- ======================================================== command block -->
  <div v-else-if="item.t === 'stmt'" class="kg-block kg-block--cmd" :class="[`kg-tone--${tone}`, marks]" :style="heat" @click.stop="pick" @dblclick.stop="open" @mouseenter="hover(true)" @mouseleave="hover(false)">
    <Icon :name="kindIcon(iconKind)" class="kg-block__icon" />
    <span class="kg-block__text kg-block__text--name">{{ title }}</span>
    <template v-if="node.kind === 'assign'">
      <span class="kg-block__name" :data-wr="outs[0]?.name">{{ outs[0]?.name ?? "_" }}</span>
      <span class="kg-block__text">to</span>
      <Slot v-if="args[0]" :expr="args[0].expr" />
    </template>
    <template v-else-if="node.kind === 'inputs'">
      <span v-for="o in outs" :key="o.port" class="kg-block__name" :data-wr="o.name" :title="o.type ? `${o.port}: ${o.type}` : o.port">{{ o.port }}</span>
    </template>
    <template v-else>
      <template v-for="(a, i) in args" :key="i">
        <span v-if="(a.keyword || args.length > 1) && a.expr.name !== a.label" class="kg-block__text kg-block__text--key">{{ a.label }}</span>
        <Slot :expr="a.expr" />
      </template>
      <template v-if="outs.length">
        <span class="kg-block__text kg-block__text--arrow">→</span>
        <span v-for="o in outs" :key="o.port" class="kg-block__name" :data-wr="o.name" :title="o.port">{{ o.name ?? "_" }}</span>
      </template>
    </template>
    <span v-if="node.hints" class="kg-block__hint" :title="hintText">@hint</span>
    <OverlayMarks :entry="entry" placement="inline" />
  </div>

  <!-- ======================================================== C block -->
  <div v-else class="kg-cblock" :class="[`kg-tone--${tone}`, marks]" :style="heat">
    <div class="kg-block kg-cblock__bar kg-cblock__bar--top" @click.stop="pick" @mouseenter="hover(true)" @mouseleave="hover(false)">
      <Icon :name="kindIcon(iconKind)" class="kg-block__icon" />
      <span class="kg-block__text kg-block__text--name">{{ title }}</span>
      <Slot v-for="(a, i) in headArgs" :key="i" :expr="a.expr" />
      <template v-if="node.kind === 'collect'">
        <span class="kg-block__text">→</span>
        <span class="kg-block__name" :data-wr="node.props?.target">{{ node.props?.target }}</span>
      </template>
      <OverlayMarks :entry="entry" placement="inline" />
    </div>
    <template v-for="(arm, i) in arms" :key="arm.region.id">
      <div v-if="arms.length > 1 || armHead(i)" class="kg-block kg-cblock__bar kg-cblock__bar--mid" @click.stop="pickRegion(arm.region.id)">
        <button class="kg-fold" :title="folded(arm.region.id) ? 'Expand' : 'Collapse'" @click.stop="state.toggle?.(arm.region.id)">
          <Icon :name="folded(arm.region.id) ? 'chevron-right' : 'chevron-down'" />
        </button>
        <span class="kg-block__text">{{ armHead(i) }}</span>
        <span v-if="arm.region.label" class="kg-block__label">{{ arm.region.label }}</span>
        <OverlayMarks :entry="state.regions.get(arm.region.id)" placement="inline" />
      </div>
      <div class="kg-cblock__mouth">
        <div v-if="folded(arm.region.id)" class="kg-folded" @click.stop="state.toggle?.(arm.region.id)">… {{ count(arm.items) }} statements</div>
        <template v-else>
          <Block v-for="(child, j) in arm.items" :key="child.node.id + j" :item="child" :model="model" />
          <div v-if="!arm.items.length" class="kg-empty">empty</div>
        </template>
      </div>
    </template>
    <div class="kg-block kg-cblock__bar kg-cblock__bar--bottom">
      <template v-if="node.kind === 'collect'">
        <span class="kg-block__text">capture at body end</span>
        <Slot :expr="collectValue" />
      </template>
      <span v-if="item.t === 'loop'" class="kg-block__text kg-block__text--foot">↺ {{ loopNote }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"

import { inputExpr, nodeKey } from "../../model/graph.js"
import { itemSlots, loopSources } from "../../model/tree.js"
import Icon from "../Icon.vue"
import { kindIcon } from "../kinds.js"
import OverlayMarks from "../OverlayMarks.vue"
import { heatStyle, useGraphState } from "../overlay.js"
import { markClasses } from "../flow/marks.js"
import { armTitle, binds, itemTitle, itemTone, slots } from "./describe.js"
import Slot from "./Slot.vue"

/** One Scratch-style block: a command, or a C block holding the stacks of its arms. */
const props = defineProps({ item: { type: Object, required: true }, model: { type: Object, required: true } })
defineOptions({ name: "Block" })

const state = useGraphState()
const node = computed(() => props.item.node)
const key = computed(() => nodeKey(node.value))
const entry = computed(() => state.nodes.get(key.value) || null)
const heat = computed(() => heatStyle(entry.value))
const marks = computed(() => markClasses(state, key.value, node.value.id, entry.value))
const tone = computed(() => itemTone(props.model, props.item))
const title = computed(() => itemTitle(props.model, props.item))
const iconKind = computed(() => {
  if (props.item.t === "loop") return "loop"
  if (node.value.kind === "call" && props.model.defNames.has(node.value.name)) return "defcall"
  return node.value.kind
})
const args = computed(() => slots(props.model, node.value))
const outs = computed(() => binds(props.model, node.value))
const headArgs = computed(() => (["branch", "switch", "each", "collect"].includes(node.value.kind) ? args.value.slice(0, 1) : []))
const collectValue = computed(() => inputExpr(props.model, node.value, "value"))
const arms = computed(() => props.item.arms || [{ region: props.item.region, items: props.item.items }])
const armHead = (i) => (props.item.arms ? armTitle(props.item, i) : "")
const hintText = computed(() =>
  Object.entries(node.value.hints || {})
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(" "),
)
const loopNote = computed(() => {
  const back = loopSources(props.model, node.value.id).length
  return back ? `repeats when the body jumps back (${back} way${back > 1 ? "s" : ""})` : "runs once"
})

const folded = (rid) => state.collapsed.value.has(rid)
const count = (items) => items.reduce((n, it) => n + 1 + itemSlots(it).reduce((m, l) => m + count(l), 0), 0)
const pick = () => state.select?.({ type: "node", id: node.value.id, key: key.value, node: node.value })
const open = () => state.open?.({ type: "node", id: node.value.id, key: key.value, node: node.value })
const pickRegion = (rid) => state.select?.({ type: "region", id: rid, key: rid })
function hover(on) {
  state.hovered.value = on ? key.value : null
}
</script>
