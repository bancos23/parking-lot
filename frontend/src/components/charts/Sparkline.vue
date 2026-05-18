<script setup>
import { computed } from 'vue'
const props = defineProps({ data: { type: Array, required: true }, color: { type: String, default: 'var(--bm-blue)' }, height: { type: Number, default: 28 } })
const viewBox = computed(() => `0 0 100 ${props.height}`)
const points = computed(() => {
  if (!props.data.length) return ''
  const max = Math.max(...props.data)
  const min = Math.min(...props.data)
  const range = max - min || 1
  const step = 100 / Math.max(1, props.data.length - 1)
  return props.data.map((v, i) => `${i * step},${props.height - 4 - ((v - min) / range) * (props.height - 8)}`).join(' ')
})
const areaPoints = computed(() => `0,${props.height} ${points.value} 100,${props.height}`)
</script>
<template>
  <svg v-if="props.data?.length" class="spark" :viewBox="viewBox" preserveAspectRatio="none">
    <polygon :points="areaPoints" :fill="props.color" opacity="0.12" />
    <polyline :points="points" fill="none" :stroke="props.color" stroke-width="1.5" vector-effect="non-scaling-stroke" />
  </svg>
</template>
