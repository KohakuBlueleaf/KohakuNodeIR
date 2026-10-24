<template>
  <!-- ======================================================== jump back -->
  <div v-if="item.t === 'jump'" class="kg-tile kg-tile--jump kg-tone--iolite" :title="`jump back to the loop ${node.props?.label}`" @click.stop="pick">
    <div class="kg-tile__top">
      <Icon name="renew" class="kg-tile__icon" />
      <span class="kg-tile__name">loop again</span>
    </div>
    <div class="kg-tile__params"><span class="kg-block__label">{{ node.props?.label }}</span></div>
  </div>

  <!-- ======================================================== tile -->
  <div v-else-if="item.t === 'stmt'" class="kg-tile" :class="[`kg-tone--${tone}`, marks]" :style="heat" @click.stop="pick" @mouseenter="hover(true)" @mouseleave="hover(false)">
    <div class="kg-tile__top">
      <Icon :name="kindIcon(iconKind)" class="kg-tile__icon" />
      <span class="kg-tile__name" :title="title">{{ title }}</span>
    </div>
    <OverlayMarks :entry="entry" placement="inline" />
    <div v-if="args.length" class="kg-tile__params">
      <span v-for="(a, i) in args" :key="i" class="kg-param">
        <span class="kg-param__label">{{ a.label }}</span>
        <Slot :expr="a.expr" />
      </span>
    </div>
    <div v-if="plugs.length" class="kg-tile__plugs">
      <span v-for="p in plugs" :key="p.port" class="kg-plug" :data-wr="p.name" :data-kind="typeKind(p.type)" :style="{ '--kg-plug': plugColor(p.type) }" :title="`${p.port} → ${p.name ?? '_'}`">{{ p.name ?? "_" }}</span>
    </div>
  </div>

  <!-- ======================================================== container -->
  <div v-else class="kg-cont" :class="[`kg-tone--${tone}`, marks]" :style="heat">
    <div class="kg-cont__head" @click.stop="pick" @mouseenter="hover(true)" @mouseleave="hover(false)">
      <Icon :name="kindIcon(iconKind)" class="kg-tile__icon" />
      <span class="kg-cont__title">{{ title }}</span>
      <span v-for="(a, i) in headArgs" :key="i" class="kg-param"><span class="kg-param__label">{{ a.label }}</span><Slot :expr="a.expr" /></span>
      <span v-for="p in headPlugs" :key="p.port" class="kg-plug" :data-wr="p.name" :data-kind="typeKind(p.type)" :style="{ '--kg-plug': plugColor(p.type) }">{{ p.name ?? "_" }}</span>
      <OverlayMarks :entry="entry" placement="inline" />
    </div>
    <div class="kg-lanes">
      <div v-for="(arm, i) in arms" :key="arm.region.id" class="kg-lane">
        <div class="kg-lane__tab" @click.stop="pickRegion(arm.region.id)">
          <button class="kg-fold" :title="folded(arm.region.id) ? 'Expand' : 'Collapse'" @click.stop="state.toggle?.(arm.region.id)">
            <Icon :name="folded(arm.region.id) ? 'chevron-right' : 'chevron-down'" />
          </button>
          {{ laneTitle(i) }}
          <OverlayMarks :entry="state.regions.get(arm.region.id)" placement="inline" />
        </div>
        <div v-if="folded(arm.region.id)" class="kg-folded" @click.stop="state.toggle?.(arm.region.id)">… {{ arm.items.length }} items</div>
        <div v-else class="kg-beam">
          <Tile v-for="(child, j) in arm.items" :key="child.node.id + j" :item="child" :model="model" />
          <span v-if="!arm.items.length" class="kg-empty">empty</span>
        </div>
      </div>
    </div>
    <div v-if="node.kind === 'collect'" class="kg-cont__head kg-cont__foot">
      <span class="kg-param"><span class="kg-param__label">capture at body end</span><Slot :expr="collectValue" /></span>
      <span class="kg-plug" :data-wr="node.props?.target" :style="{ '--kg-plug': 'var(--kg-ev-other)' }">{{ node.props?.target }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"

import { inputExpr, nodeKey } from "../../model/graph.js"
import { typeKind } from "../../model/types.js"
import Icon from "../Icon.vue"
import { kindIcon } from "../kinds.js"
import OverlayMarks from "../OverlayMarks.vue"
import { heatStyle, useGraphState } from "../overlay.js"
import { markClasses } from "../flow/marks.js"
import { armTitle, binds, itemTitle, itemTone, slots } from "./describe.js"
import Slot from "./Slot.vue"

/** One EV3-style tile (parameter boxes below, output plugs) or container with stacked lanes. */
const props = defineProps({ item: { type: Object, required: true }, model: { type: Object, required: true } })
defineOptions({ name: "Tile" })

const state = useGraphState()
const node = computed(() => props.item.node)
const key = computed(() => nodeKey(node.value))
const entry = computed(() => state.nodes.get(key.value) || null)
const heat = computed(() => heatStyle(entry.value))
const marks = computed(() => markClasses(state, key.value, node.value.id, entry.value))
const tone = computed(() => itemTone(props.model, props.item))
const title = computed(() => (node.value.kind === "assign" ? "write" : itemTitle(props.model, props.item)))
const iconKind = computed(() => (props.item.t === "loop" ? "loop" : node.value.kind))
const args = computed(() => slots(props.model, node.value))
const plugs = computed(() => binds(props.model, node.value))
const headArgs = computed(() => (["branch", "switch", "each", "collect"].includes(node.value.kind) ? args.value.slice(0, 1) : []))
const headPlugs = computed(() => (["each", "collect"].includes(node.value.kind) ? plugs.value.filter((p) => p.port !== "results" && p.name) : []))
const collectValue = computed(() => inputExpr(props.model, node.value, "value"))
const arms = computed(() => props.item.arms || [{ region: props.item.region, items: props.item.items }])
const laneTitle = (i) => {
  const r = arms.value[i].region
  const head = props.item.arms ? armTitle(props.item, i) : props.item.t
  return r.label ? `${head} · ${r.label}` : head
}
const plugColor = (type) => `var(--kg-ev-${typeKind(type)})`
const folded = (rid) => state.collapsed.value.has(rid)
const pick = () => state.select?.({ type: "node", id: node.value.id, key: key.value, node: node.value })
const pickRegion = (rid) => state.select?.({ type: "region", id: rid, key: rid })
function hover(on) {
  state.hovered.value = on ? key.value : null
}
</script>
