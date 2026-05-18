<script setup>
import { computed } from 'vue'
const props = defineProps({ data: { type: Array, required: true }, spotsLabel: { type: String, default: 'spots' } })
const total = computed(() => props.data.reduce((sum, d) => sum + d.value, 0))
const segments = computed(() => {
  const r = 64, R = 78, cx = 100, cy = 100
  if (total.value <= 0) return []
  let acc = 0
  return props.data.map(item => {
    const start = acc / total.value * Math.PI * 2 - Math.PI / 2
    acc += item.value
    const end = acc / total.value * Math.PI * 2 - Math.PI / 2
    const large = end - start > Math.PI ? 1 : 0
    const x1 = cx + R * Math.cos(start), y1 = cy + R * Math.sin(start)
    const x2 = cx + R * Math.cos(end), y2 = cy + R * Math.sin(end)
    const x3 = cx + r * Math.cos(end), y3 = cy + r * Math.sin(end)
    const x4 = cx + r * Math.cos(start), y4 = cy + r * Math.sin(start)
    return { ...item, d: `M ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2} L ${x3} ${y3} A ${r} ${r} 0 ${large} 0 ${x4} ${y4} Z` }
  })
})
</script>
<template>
  <div class="donut-wrap">
    <svg viewBox="0 0 200 200" width="160" height="160">
      <path v-for="(seg, i) in segments" :key="i" :d="seg.d" :fill="seg.color" />
      <text x="100" y="98" text-anchor="middle" font-size="22" font-weight="600" fill="var(--text)" font-family="var(--font-sans)">{{ total }}</text>
      <text x="100" y="116" text-anchor="middle" font-size="10" fill="var(--text-muted)" font-family="var(--font-mono)">{{ props.spotsLabel }}</text>
    </svg>
    <div class="donut-legend">
      <div v-for="seg in segments" :key="seg.label" class="donut-legend-row">
        <span :style="{ background: seg.color }"></span>
        <div><div>{{ seg.label }}</div><small>{{ seg.value }} · {{ total ? Math.round(seg.value / total * 100) : 0 }}%</small></div>
      </div>
    </div>
  </div>
</template>
