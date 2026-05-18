<script setup>
import { computed } from 'vue'
const props = defineProps({ data: { type: Array, required: true }, labels: { type: Array, required: true }, color: { type: String, default: 'var(--bm-red)' }, height: { type: Number, default: 200 } })
const w = 600, padL = 40, padB = 24, padT = 10, padR = 10
const innerW = w - padL - padR
const innerH = computed(() => props.height - padT - padB)
const max = computed(() => Math.max(...props.data) * 1.1)
const gap = computed(() => innerW / props.data.length)
const bw = computed(() => gap.value * 0.65)
const barHeight = v => (v / max.value) * innerH.value
</script>
<template>
  <svg :viewBox="`0 0 ${w} ${props.height}`" width="100%" :height="props.height" style="display:block">
    <g v-for="p in [0,0.5,1]" :key="p">
      <line :x1="padL" :x2="padL + innerW" :y1="padT + innerH * (1 - p)" :y2="padT + innerH * (1 - p)" stroke="var(--border)" :stroke-dasharray="p === 0 ? '0' : '2,3'" />
      <text :x="padL - 6" :y="padT + innerH * (1 - p) + 3" font-size="9" text-anchor="end" fill="var(--text-faint)" font-family="var(--font-mono)">{{ Math.round(max * p / 1000) }}k</text>
    </g>
    <g v-for="(v, i) in props.data" :key="i">
      <rect :x="padL + i * gap + (gap - bw) / 2" :y="padT + innerH - barHeight(v)" :width="bw" :height="barHeight(v)" :fill="props.color" rx="2" />
      <text :x="padL + i * gap + gap / 2" :y="props.height - 6" font-size="9" text-anchor="middle" fill="var(--text-faint)" font-family="var(--font-mono)">{{ props.labels[i] }}</text>
    </g>
  </svg>
</template>
