<template>
  <div class="card px-2.5 py-2 text-[10.5px] font-mono text-warm-600 dark:text-warm-300 select-none" :class="open ? 'w-44' : ''">
    <button class="flex items-center gap-1 w-full section-title" @click="open = !open">
      <span :class="open ? 'i-carbon-chevron-down' : 'i-carbon-chevron-right'" class="text-[10px]" />
      legend
    </button>
    <div v-if="open" class="mt-1.5 flex flex-col gap-1">
      <div class="flex items-center gap-2"><span class="inline-block w-6 h-0.5 rounded" :style="{ background: CTRL_COLOR }" />control</div>
      <div class="flex items-center gap-2"><span class="inline-block w-6 border-t-2 border-dashed" :style="{ borderColor: CTRL_COLOR }" />back edge</div>
      <div v-for="t in TYPES" :key="t" class="flex items-center gap-2"><span class="inline-block w-6 h-0.5 rounded" :style="{ background: typeColor(t) }" />{{ t }}</div>
      <div class="flex items-center gap-2"><span class="inline-block w-6 h-0.5 rounded" :style="{ background: typeColor(null) }" />_ untyped</div>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue"

import { CTRL_COLOR, typeColor } from "@/graph/types"

const TYPES = ["int", "float", "str", "bool", "list", "dict"]
const open = ref(false)
</script>
