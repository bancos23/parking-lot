<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useT } from '@frontend/composables/i18n'
import { LANGUAGES } from '@frontend/locales/index'

defineProps({ compact: { type: Boolean, default: false } })

const { lang, setLang } = useT()
const open = ref(false)
const root = ref(null)
const current = computed(() => LANGUAGES.find(l => l.code === lang.value) || LANGUAGES[0])

function onDocumentClick(e) {
  if (root.value && !root.value.contains(e.target)) open.value = false
}

onMounted(() => document.addEventListener('mousedown', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocumentClick))
</script>

<template>
  <div ref="root" class="lang-switcher">
    <button class="lang-trigger" type="button" aria-label="Language" @click="open = !open">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="2" y1="12" x2="22" y2="12" />
        <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
      </svg>
      <span class="lang-code">{{ current.short }}</span>
      <svg v-if="!compact" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:.6">
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>

    <div v-if="open" class="lang-menu">
      <button v-for="item in LANGUAGES" :key="item.code" type="button" class="lang-item"
        :class="{ active: item.code === lang }" @click="setLang(item.code); open = false">
        <span class="lang-flag">{{ item.flag }}</span>
        <span class="lang-name">{{ item.label }}</span>
        <span class="lang-short">{{ item.short }}</span>
        <svg v-if="item.code === lang" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--bm-blue)">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </button>
    </div>
  </div>
</template>
