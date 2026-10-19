<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="kir-viewbar">
      <span class="kir-viewbar__title"><span class="i-carbon-code" />Text</span>
      <span class="text-[10.5px] text-warm-500">the program itself · every other view is drawn from it</span>
    </div>
    <div class="flex-1 min-h-0">
      <CodeEditor />
    </div>
  </div>
</template>

<script setup>
import CodeEditor from "@/views/text/CodeEditor.vue"
</script>
