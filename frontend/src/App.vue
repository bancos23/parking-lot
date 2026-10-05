<script setup>
import { onMounted, ref } from 'vue'
import GateModal from '@frontend/components/GateModal.vue'

const gateReady = ref(false)
const gatePassed = ref(false)

onMounted(async () => {
  try {
    const res = await fetch('/api/gate/status', { credentials: 'include' })
    gatePassed.value = res.ok ? (await res.json()).passed : false
  } catch {
    gatePassed.value = false
  }
  gateReady.value = true
})
</script>

<template>
  <router-view v-if="gatePassed" />
  <GateModal v-else-if="gateReady" @success="gatePassed = true" />
</template>
