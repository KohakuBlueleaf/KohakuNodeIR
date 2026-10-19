<template>
  <div class="ev-param" :style="{ '--ev-color': color }" :data-rd="expr && 'name' in expr ? expr.name : null">
    <ScratchSlot class="ev-param__box" :expr="expr" :placeholder="placeholder" :shape="kind === 'bool' ? 'hex' : 'round'" @update="(e) => emit('update', e)" />
    <span class="ev-param__label" :title="label">{{ label }}</span>
  </div>
</template>

<script setup>
import { computed, inject } from "vue"

import { EV_COLOR, evKindOfLiteral, evKindOfType } from "@/views/sequence/evTypes"
import ScratchSlot from "@/views/blocks/ScratchSlot.vue"

/**
 * A parameter box along the bottom of an EV3 block: the value it takes (a
 * literal you can edit, or the variable wired into it) and its name, coloured
 * by data kind.
 */
const props = defineProps({
  expr: { type: Object, default: null },
  label: { type: String, default: "" },
  type: { type: String, default: null },
  placeholder: { type: String, default: "?" },
})
const emit = defineEmits(["update"])

const ev = inject("ev")
const kind = computed(() => {
  if (props.type) return evKindOfType(props.type)
  if (props.expr && "lit" in props.expr) return evKindOfLiteral(props.expr.lit)
  if (props.expr && "name" in props.expr) return ev.kinds.value.get(props.expr.name) || "other"
  return "other"
})
const color = computed(() => EV_COLOR[kind.value])
</script>
