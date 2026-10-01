<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useT } from '@frontend/composables/i18n'
import { useAuth } from '@frontend/stores/auth'

const props = defineProps({ user: { type: Object, required: true } })
const emit = defineEmits(['close', 'updated', 'deleted', 'password-changed'])
const { t } = useT()
const { clearSession, expireSession } = useAuth()

const now = new Date()
const today = new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
const form = reactive({ name: '', email: '', phone: '', birthDate: '', city: '' })
const plates = ref([])
const newPlate = ref('')
const passwordForm = reactive({ current: '', next: '', confirmation: '' })
const passwordEditorOpen = ref(false)
const currentPasswordVerified = ref(false)
const passwordError = ref('')
const deletePassword = ref('')
const deleteEditorOpen = ref(false)
const deleteConfirmationOpen = ref(false)
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

const hasAccountChanges = computed(() =>
  form.name !== (props.user?.name || '')
  || form.email !== (props.user?.email || '')
  || form.phone !== (props.user?.phone || '')
  || form.birthDate !== (props.user?.birth_date || '')
  || form.city !== (props.user?.city || '')
)

function apiError(data) {
  if (data?.detail === 'Incorrect password') return t('account.delete.incorrect_password')
  if (data?.detail === 'Incorrect current password') return t('account.password.incorrect_current')
  if (data?.detail === 'New password must be different') return t('account.password.same')
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
  if (!hasAccountChanges.value || busy.value) return
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

function closePasswordEditor() {
  passwordEditorOpen.value = false
  currentPasswordVerified.value = false
  passwordForm.current = ''
  passwordForm.next = ''
  passwordForm.confirmation = ''
  passwordError.value = ''
}

function openPasswordEditor() {
  closeDeleteEditor()
  passwordEditorOpen.value = true
}

async function verifyCurrentPassword() {
  passwordError.value = ''
  if (!passwordForm.current) {
    passwordError.value = t('account.password.current_required')
    return
  }

  busy.value = true
  try {
    await accountRequest('/api/auth/me/password/verify', {
      method: 'POST',
      body: JSON.stringify({ password: passwordForm.current }),
    })
    currentPasswordVerified.value = true
  } catch (requestError) {
    passwordError.value = requestError.message || t('account.error')
  } finally {
    busy.value = false
  }
}

async function changePassword() {
  passwordError.value = ''
  if (!passwordForm.next || !passwordForm.confirmation) {
    passwordError.value = t('account.password.new_required')
    return
  }
  if (passwordForm.next.length < 8) {
    passwordError.value = t('account.password.too_short')
    return
  }
  if (passwordForm.next !== passwordForm.confirmation) {
    passwordError.value = t('account.password.mismatch')
    return
  }
  if (passwordForm.current === passwordForm.next) {
    passwordError.value = t('account.password.same')
    return
  }

  busy.value = true
  try {
    await accountRequest('/api/auth/me/password', {
      method: 'PATCH',
      body: JSON.stringify({
        current_password: passwordForm.current,
        new_password: passwordForm.next,
      }),
    })
    clearSession()
    emit('password-changed')
  } catch (requestError) {
    passwordError.value = requestError.message || t('account.error')
  } finally {
    busy.value = false
  }
}

function closeDeleteEditor() {
  deleteEditorOpen.value = false
  deletePassword.value = ''
  error.value = ''
}

function openDeleteEditor() {
  closePasswordEditor()
  deleteEditorOpen.value = true
  error.value = ''
  success.value = ''
}

async function requestAccountDeletion() {
  if (!deletePassword.value) {
    error.value = t('account.delete.password_required')
    success.value = ''
    return
  }

  busy.value = true
  error.value = ''
  try {
    await accountRequest('/api/auth/me/password/verify', {
      method: 'POST',
      body: JSON.stringify({ password: deletePassword.value }),
    })
    deleteConfirmationOpen.value = true
  } catch (requestError) {
    error.value = requestError.message || t('account.error')
  } finally {
    busy.value = false
  }
}

async function deleteAccount() {
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    await accountRequest('/api/auth/me', {
      method: 'DELETE',
      body: JSON.stringify({ password: deletePassword.value }),
    })
    clearSession()
    emit('deleted')
  } catch (requestError) {
    deleteConfirmationOpen.value = false
    error.value = requestError.message || t('account.error')
  } finally {
    busy.value = false
  }
}

function handleKeydown(event) {
  if (event.key !== 'Escape' || busy.value) return
  if (deleteConfirmationOpen.value) deleteConfirmationOpen.value = false
  else if (passwordEditorOpen.value) closePasswordEditor()
  else if (deleteEditorOpen.value) closeDeleteEditor()
  else emit('close')
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

          <section class="settings-section">
            <div>
              <div class="field-group-title">{{ t('account.password.title') }}</div>
              <p class="settings-hint">{{ t('account.password.hint') }}</p>
            </div>
            <button v-if="!passwordEditorOpen" class="btn btn-primary password-action" type="button"
              :disabled="busy" @click="openPasswordEditor">
              {{ t('account.password.button') }}
            </button>

            <template v-else-if="!currentPasswordVerified">
              <div class="field">
                <label for="current-password">{{ t('account.password.current') }}</label>
                <input id="current-password" v-model="passwordForm.current" type="password" maxlength="128"
                  autocomplete="current-password" @input="passwordError = ''"
                  @keydown.enter.prevent="verifyCurrentPassword">
              </div>
              <div v-if="passwordError" class="auth-error">⚠ {{ passwordError }}</div>
              <div class="password-actions">
                <button class="btn" type="button" :disabled="busy" @click="closePasswordEditor">
                  {{ t('account.password.cancel') }}
                </button>
                <button class="btn btn-primary" type="button" :disabled="busy" @click="verifyCurrentPassword">
                  {{ t('account.password.verify') }}
                </button>
              </div>
            </template>

            <template v-else>
              <div class="settings-success">✓ {{ t('account.password.verified') }}</div>
              <div class="field-row">
                <div class="field">
                  <label for="new-password">{{ t('account.password.new') }}</label>
                  <input id="new-password" v-model="passwordForm.next" type="password" maxlength="128"
                    autocomplete="new-password" @input="passwordError = ''" @keydown.enter.prevent="changePassword">
                </div>
                <div class="field">
                  <label for="confirm-new-password">{{ t('account.password.confirm') }}</label>
                  <input id="confirm-new-password" v-model="passwordForm.confirmation" type="password" maxlength="128"
                    autocomplete="new-password" @input="passwordError = ''" @keydown.enter.prevent="changePassword">
                </div>
              </div>
              <div v-if="passwordError" class="auth-error">⚠ {{ passwordError }}</div>
              <div class="password-actions">
                <button class="btn" type="button" :disabled="busy" @click="closePasswordEditor">
                  {{ t('account.password.cancel') }}
                </button>
                <button class="btn btn-primary" type="button" :disabled="busy" @click="changePassword">
                  {{ t('account.password.save') }}
                </button>
              </div>
            </template>
          </section>

          <section class="settings-section danger-zone">
            <div>
              <div class="field-group-title">{{ t('account.delete.title') }}</div>
              <p class="settings-hint">{{ t('account.delete.hint') }}</p>
            </div>
            <button v-if="!deleteEditorOpen" class="btn delete-account" type="button" :disabled="busy"
              @click="openDeleteEditor">{{ t('account.delete.open') }}</button>
            <template v-else>
              <div class="field">
                <label for="delete-account-password">{{ t('account.delete.password') }}</label>
                <input id="delete-account-password" v-model="deletePassword" type="password" maxlength="128"
                  autocomplete="current-password" @input="error = ''" @keydown.enter.prevent="requestAccountDeletion">
              </div>
              <div class="password-actions">
                <button class="btn" type="button" :disabled="busy" @click="closeDeleteEditor">
                  {{ t('account.delete.cancel') }}
                </button>
                <button class="btn btn-danger" type="button" :disabled="busy" @click="requestAccountDeletion">
                  {{ t('account.delete.verify') }}
                </button>
              </div>
            </template>
          </section>

          <div v-if="error" class="auth-error">⚠ {{ error }}</div>
          <div v-if="success" class="settings-success">✓ {{ success }}</div>
        </div>

        <div class="modal-foot">
          <button class="btn" type="button" :disabled="busy" @click="emit('close')">{{ t('account.close') }}</button>
          <button v-if="hasAccountChanges" class="btn btn-primary" type="submit" :disabled="busy">
            {{ t('account.save') }}
          </button>
        </div>
      </form>
    </div>
  </div>

  <div v-if="deleteConfirmationOpen" class="modal-backdrop" @click="!busy && (deleteConfirmationOpen = false)">
    <div class="modal delete-confirmation-modal" role="alertdialog" aria-modal="true"
      aria-labelledby="delete-account-confirmation-title" @click.stop>
      <div class="modal-head">
        <div class="delete-confirmation-heading">
          <span class="delete-confirmation-icon" aria-hidden="true">!</span>
          <h3 id="delete-account-confirmation-title">{{ t('account.delete.confirm_title') }}</h3>
        </div>
        <button class="icon-btn" type="button" :aria-label="t('account.delete.cancel')" :disabled="busy"
          @click="deleteConfirmationOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="delete-confirmation-notice">
          <p class="delete-confirmation-text">{{ t('account.delete.confirm') }}</p>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn" type="button" :disabled="busy" @click="deleteConfirmationOpen = false">
          {{ t('account.delete.cancel') }}
        </button>
        <button class="btn btn-danger" type="button" :disabled="busy" @click="deleteAccount">
          {{ t('account.delete.button') }}
        </button>
      </div>
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

.danger-zone {
  border-color: rgba(220, 38, 38, 0.35);
}

.delete-account {
  justify-self: start;
  border-color: var(--bad);
  color: var(--bad);
}

.password-action {
  justify-self: start;
}

.password-actions {
  display: flex;
  gap: 8px;
}

.delete-confirmation-modal {
  width: 380px;
  border: 1px solid var(--border);
  font-family: var(--font-sans);
}

.delete-confirmation-modal .modal-head {
  padding: 12px 14px;
}

.delete-confirmation-heading {
  display: flex;
  align-items: center;
  gap: 9px;
}

.delete-confirmation-icon {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 7px;
  background: rgba(220, 38, 38, 0.12);
  color: var(--bad);
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 700;
}

.delete-confirmation-modal .icon-btn {
  width: 28px;
  height: 28px;
}

.delete-confirmation-modal .modal-body {
  padding: 14px;
}

.delete-confirmation-notice {
  padding: 10px 12px;
  border: 1px solid rgba(220, 38, 38, 0.25);
  border-radius: 8px;
  background: rgba(220, 38, 38, 0.06);
}

.delete-confirmation-text {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.delete-confirmation-modal .modal-foot {
  padding: 10px 14px;
}

.delete-confirmation-modal .btn {
  padding: 6px 11px;
  border-radius: 7px;
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
