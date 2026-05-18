<script setup>
import { computed } from 'vue'
const props = defineProps({ actual: { type: Array, required: true }, forecast: { type: Array, required: true }, labels: { type: Array, required: true } })
const w = 600, h = 200, padL = 36, padB = 24, padT = 10, padR = 10
const innerW = w - padL - padR
const innerH = h - padT - padB
const step = computed(() => innerW / Math.max(1, props.actual.length - 1))
const y = v => padT + innerH - (v / 100) * innerH
const actualPts = computed(() => props.actual.map((v, i) => `${padL + i * step.value},${y(v)}`).join(' '))
const forecastPts = computed(() => props.forecast.map((v, i) => `${padL + i * step.value},${y(v)}`).join(' '))
const areaPts = computed(() => `${padL},${padT + innerH} ${actualPts.value} ${padL + innerW},${padT + innerH}`)
</script>
<template>
  <svg :viewBox="`0 0 ${w} ${h}`" width="100%" :height="h" style="display:block">
    <g v-for="g in [0,25,50,75,100]" :key="g">
      <line :x1="padL" :x2="padL + innerW" :y1="y(g)" :y2="y(g)" stroke="var(--border)" :stroke-dasharray="g === 0 ? '0' : '2,3'" />
      <text :x="padL - 6" :y="y(g) + 3" font-size="9" text-anchor="end" fill="var(--text-faint)" font-family="var(--font-mono)">{{ g }}%</text>
    </g>
    <polygon :points="areaPts" fill="var(--bm-blue)" opacity="0.14" />
    <polyline :points="actualPts" fill="none" stroke="var(--bm-blue)" stroke-width="2" />
    <polyline :points="forecastPts" fill="none" stroke="var(--bm-red)" stroke-width="2" stroke-dasharray="4,3" />
    <template v-for="(label, i) in props.labels" :key="label">
      <text v-if="i % 3 === 0 || i === props.labels.length - 1" :x="padL + i * step" :y="h - 6" font-size="9" text-anchor="middle" fill="var(--text-faint)" font-family="var(--font-mono)">{{ label }}</text>
    </template>
  </svg>
</template>
