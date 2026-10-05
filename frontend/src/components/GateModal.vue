<script setup>
import { ref } from 'vue'
import { useT } from '@frontend/composables/i18n'

const emit = defineEmits(['success'])
const { t } = useT()
const key = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  if (!key.value.trim() || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const res = await fetch('/api/gate/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ key: key.value.trim() }),
    })
    if (!res.ok) {
      error.value = t('gate.error')
      key.value = ''
      return
    }
    emit('success')
  } catch {
    error.value = t('gate.error')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop gate-backdrop">
    <div class="modal gate-modal" @click.stop>
      <div class="modal-head">
        <h3>{{ t('gate.title') }}</h3>
      </div>
      <form class="modal-body" @submit.prevent="submit">
        <p class="modal-sub">{{ t('gate.hint') }}</p>
        <div class="field">
          <label>{{ t('gate.label') }}</label>
          <input v-model="key" type="password" autocomplete="off" :placeholder="t('gate.placeholder')"
            :disabled="loading" autofocus>
        </div>
        <p v-if="error" class="gate-error">{{ error }}</p>
        <div class="modal-foot">
          <button class="btn btn-primary" type="submit" :disabled="!key.trim() || loading">
            {{ loading ? t('gate.checking') : t('gate.submit') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.gate-backdrop {
  z-index: 2000;
}

.gate-modal {
  max-width: 380px;
}

.gate-modal .modal-foot {
  justify-content: center;
}

.gate-error {
  margin: 0;
  color: var(--danger, #d92d20);
  font-size: 13px;
}
</style>
