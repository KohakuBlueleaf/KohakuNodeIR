<template>
  <span v-if="'lit' in expr" class="kg-slot kg-slot--lit" :class="`kg-slot--${literalKind(expr.lit)}`" :title="formatLiteral(expr.lit)">{{ shortLiteral(expr.lit, 24) }}</span>
  <span v-else-if="expr.name" class="kg-slot kg-slot--name" :data-rd="expr.name" :title="`reads ${expr.name}`">{{ expr.name }}</span>
  <span v-else-if="expr.wire" class="kg-slot kg-slot--wire" :title="`wired from ${expr.wire}`">{{ expr.wire }}</span>
  <span v-else class="kg-slot kg-slot--missing" title="not given">?</span>
</template>

<script setup>
import { formatLiteral, literalKind, shortLiteral } from "../../model/literal.js"

/** An expression slot of a statement: a literal, a name it reads, an unnamed wire, or nothing. */
defineProps({ expr: { type: Object, required: true } })
</script>
