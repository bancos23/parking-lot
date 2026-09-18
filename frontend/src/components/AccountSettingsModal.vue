<script setup>
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useT } from '@frontend/composables/i18n'
import { useAuth } from '@frontend/stores/auth'

const props = defineProps({ user: { type: Object, required: true } })
const emit = defineEmits(['close', 'updated'])
const { t } = useT()
const { expireSession } = useAuth()

const now = new Date()
const today = new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
const form = reactive({ name: '', email: '', phone: '', birthDate: '', city: '' })
const plates = ref([])
const newPlate = ref('')
const busy = ref(false)
const error = ref('')
const success = ref('')

function syncAccount(account) {
  form.name = account?.name || ''
  form.email = account?.email || ''
  form.phone = account?.phone || ''
  form.birthDate = account?.birth_date ?? ''
  form.city = account?.city || ''
  plates.value = Array.isArray(account?.license_plates) ? account.license_plates : []
}

watch(() => props.user, syncAccount, { immediate: true })

function apiError(data) {
  if (typeof data?.detail === 'string') return data.detail
  if (Array.isArray(data?.detail)) return data.detail.map(item => item.msg || String(item)).join(' ')
  return t('account.error')
}

async function accountRequest(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'include',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  })
  const data = await response.json().catch(() => null)
  if (response.status === 401) expireSession()
  if (!response.ok) throw new Error(apiError(data))
  return data
}

function applyUpdate(account, message = '') {
  syncAccount(account)
  emit('updated', account)
  success.value = message
  error.value = ''
}

async function saveAccount() {
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    const account = await accountRequest('/api/auth/me', {
      method: 'PATCH',
      body: JSON.stringify({
        name: form.name,
        email: form.email,
        phone: form.phone || null,
        birth_date: form.birthDate || null,
        city: form.city || null,
      }),
    })
    applyUpdate(account, t('account.saved'))
  } catch (requestError) {
    error.value = requestError.message || t('account.error')
  } finally {
    busy.value = false
  }
}

async function addPlate() {
  if (!newPlate.value.trim()) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    const account = await accountRequest('/api/auth/me/license-plates', {
      method: 'POST',
      body: JSON.stringify({ plate_number: newPlate.value }),
    })
    newPlate.value = ''
    applyUpdate(account, t('account.plates.added'))
  } catch (requestError) {
    error.value = requestError.message || t('account.error')
  } finally {
    busy.value = false
  }
}

async function activatePlate(plateId) {
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    const account = await accountRequest(`/api/auth/me/license-plates/${plateId}/activate`, {
      method: 'PATCH',
    })
    applyUpdate(account, t('account.plates.selected'))
  } catch (requestError) {
    error.value = requestError.message || t('account.error')
  } finally {
    busy.value = false
  }
}

async function deletePlate(plate) {
  if (!window.confirm(t('account.plates.delete_confirm'))) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    const account = await accountRequest(`/api/auth/me/license-plates/${plate.id}`, {
      method: 'DELETE',
    })
    applyUpdate(account, t('account.plates.deleted'))
  } catch (requestError) {
    error.value = requestError.message || t('account.error')
  } finally {
    busy.value = false
  }
}

function handleKeydown(event) {
  if (event.key === 'Escape' && !busy.value) emit('close')
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <div class="modal-backdrop" @click="!busy && emit('close')">
    <div class="modal account-settings-modal" role="dialog" aria-modal="true" :aria-label="t('account.title')"
      @click.stop>
      <div class="modal-head">
        <div>
          <h3>{{ t('account.title') }}</h3>
          <div class="modal-sub">{{ t('account.subtitle') }}</div>
        </div>
        <button class="icon-btn" type="button" :aria-label="t('account.close')" :disabled="busy"
          @click="emit('close')">✕</button>
      </div>

      <form class="account-settings-form" @submit.prevent="saveAccount">
        <div class="modal-body account-settings-body">
          <section class="settings-section">
            <div class="field-group-title">{{ t('account.details') }}</div>
            <div class="field-row">
              <div class="field">
                <label for="account-name">{{ t('account.name') }}</label>
                <input id="account-name" v-model.trim="form.name" maxlength="200" required>
              </div>
              <div class="field">
                <label for="account-email">{{ t('account.email') }}</label>
                <input id="account-email" v-model.trim="form.email" type="email" maxlength="255" required>
              </div>
            </div>
            <div class="field-row">
              <div class="field">
                <label for="account-phone">{{ t('account.phone') }}</label>
                <input id="account-phone" v-model.trim="form.phone" type="tel" maxlength="30">
              </div>
              <div class="field">
                <label for="account-birth-date">{{ t('account.birth_date') }}</label>
                <input id="account-birth-date" v-model="form.birthDate" type="date" min="1900-01-01" :max="today">
              </div>
            </div>
            <div class="field">
              <label for="account-city">{{ t('account.city') }}</label>
              <input id="account-city" v-model.trim="form.city" maxlength="120" autocomplete="address-level2">
            </div>
          </section>

          <section class="settings-section">
            <div>
              <div class="field-group-title">{{ t('account.plates.title') }}</div>
              <p class="settings-hint">{{ t('account.plates.hint') }}</p>
            </div>

            <div class="plate-add-row">
              <input v-model="newPlate" maxlength="20" :placeholder="t('account.plates.placeholder')"
                :aria-label="t('account.plates.new')" @keydown.enter.prevent="addPlate">
              <button class="btn btn-primary" type="button" :disabled="busy || !newPlate.trim()" @click="addPlate">
                ＋ {{ t('account.plates.add') }}
              </button>
            </div>

            <div v-if="plates.length" class="plate-list">
              <div v-for="plate in plates" :key="plate.id" class="plate-row" :class="{ active: plate.is_active }">
                <div>
                  <strong class="plate-number">{{ plate.plate_number }}</strong>
                  <span v-if="plate.is_active" class="active-label">{{ t('account.plates.active') }}</span>
                </div>
                <div class="plate-actions">
                  <button v-if="!plate.is_active" class="btn" type="button" :disabled="busy"
                    @click="activatePlate(plate.id)">{{ t('account.plates.use') }}</button>
                  <button class="icon-btn delete-plate" type="button" :title="t('account.plates.delete')"
                    :aria-label="t('account.plates.delete')" :disabled="busy" @click="deletePlate(plate)">✕</button>
                </div>
              </div>
            </div>
            <div v-else class="empty-plates">{{ t('account.plates.empty') }}</div>
          </section>

          <div v-if="error" class="auth-error">⚠ {{ error }}</div>
          <div v-if="success" class="settings-success">✓ {{ success }}</div>
        </div>

        <div class="modal-foot">
          <button class="btn" type="button" :disabled="busy" @click="emit('close')">{{ t('account.close') }}</button>
          <button class="btn btn-primary" type="submit" :disabled="busy">{{ t('account.save') }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.account-settings-modal {
  width: 680px;
  max-height: calc(100vh - 56px);
  display: flex;
  flex-direction: column;
}

.account-settings-form {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.account-settings-body {
  overflow-y: auto;
}

.settings-section {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-2);
}

.settings-section :deep(.field input) {
  background: var(--surface);
}

.settings-hint {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.plate-add-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
}

.plate-add-row input {
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface);
  font-family: var(--font-mono);
  text-transform: uppercase;
  outline: none;
}

.plate-add-row input:focus {
  border-color: var(--bm-blue);
}

.plate-list {
  display: grid;
  gap: 7px;
}

.plate-row {
  min-height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.plate-row.active {
  border-color: var(--good);
}

.plate-number {
  font-family: var(--font-mono);
  font-size: 14px;
  letter-spacing: 0.04em;
}

.active-label {
  display: inline-flex;
  margin-left: 8px;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(22, 163, 74, 0.12);
  color: var(--good);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
}

.plate-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.delete-plate {
  width: 30px;
  height: 30px;
  color: var(--bad);
}

.empty-plates {
  padding: 14px;
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}

.settings-success {
  padding: 9px 11px;
  border-radius: 8px;
  background: rgba(22, 163, 74, 0.12);
  color: var(--good);
  font-size: 12px;
}

@media (max-width: 600px) {
  .account-settings-modal {
    max-height: calc(100vh - 24px);
  }

  .plate-add-row {
    grid-template-columns: 1fr;
  }

  .plate-row {
    align-items: flex-start;
  }
}
</style>
