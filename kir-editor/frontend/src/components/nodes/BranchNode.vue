<script setup>
defineProps({ node: { type: Object, required: true } });
</script>

<template>
  <div class="branch-body">
    <div class="outcomes">
      <div class="outcome outcome--true">
        <span class="letter">T</span><span class="label">true</span>
      </div>
      <div class="outcome outcome--false">
        <span class="letter">F</span><span class="label">false</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.branch-body {
  font-size: 11px;
}
.outcomes {
  display: flex;
  gap: 6px;
}
.outcome {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  padding: 3px 6px;
  border-radius: 4px;
  border: 1px solid transparent;
}
.outcome--true {
  background: rgba(166, 227, 161, 0.1);
  border-color: rgba(166, 227, 161, 0.25);
}
.outcome--false {
  background: rgba(243, 139, 168, 0.1);
  border-color: rgba(243, 139, 168, 0.25);
}
.letter {
  font-size: 11px;
  font-weight: 800;
  width: 12px;
  text-align: center;
}
.outcome--true .letter {
  color: #a6e3a1;
}
.outcome--false .letter {
  color: #f38ba8;
}
.label {
  font-size: 10px;
  color: #9399b2;
}
</style>
