<template>
  <div class="kir-region" :class="`kir-region--${data.region.kind}`" :style="{ width: `${data.region.w}px`, height: `${data.region.h}px` }">
    <div class="kir-region__head">
      <span :class="ICON[data.region.kind] || 'i-carbon-tag'" class="text-[11px]" />
      <span class="truncate">{{ data.region.title }}</span>
    </div>
  </div>
</template>

<script setup>
/** A frames-style control region: a namespace, branch arm, loop body, try / except or dataflow block. */
defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
})

const ICON = {
  branch: "i-carbon-flow-connection",
  switch: "i-carbon-tree-view-alt",
  parallel: "i-carbon-split",
  each: "i-carbon-repeat",
  loop: "i-carbon-renew",
  try: "i-carbon-warning-alt",
  except: "i-carbon-warning-alt-filled",
  dataflow: "i-carbon-data-share",
  namespace: "i-carbon-tag",
}
</script>
