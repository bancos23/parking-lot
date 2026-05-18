<script setup>
import { computed, reactive, watch } from 'vue'
import { useT } from '@frontend/composables/i18n'

const props = defineProps({ lot: { type: Object, required: true } })
const emit = defineEmits(['save', 'cancel'])
const { t } = useT()
const form = reactive({ ...props.lot })

function defaultCamera() {
  return {
    name: 'Panoramic camera',
    camera_type: 'panoramic',
    stream_url: '',
    is_active: true,
    is_primary: true,
  }
}

function ensurePrimaryCamera() {
  if (!form._isNew) return
  if (!Array.isArray(form.cameras) || form.cameras.length === 0) {
    form.cameras = [defaultCamera()]
  }
  const camera = form.cameras[0]
  camera.camera_type = 'panoramic'
  camera.is_active = true
  camera.is_primary = true
  if (!camera.name) camera.name = 'Panoramic camera'
}

watch(() => props.lot, next => {
  Object.assign(form, next)
  ensurePrimaryCamera()
}, { deep: true, immediate: true })

const primaryCamera = computed(() => Array.isArray(form.cameras) ? form.cameras[0] : null)
const canSave = computed(() => {
  if (!form.name || !form.address) return false
  if (!form._isNew) return true
  return Boolean(primaryCamera.value?.stream_url)
})

function updateNumber(key, value, fallback = 0) {
  form[key] = Number.isFinite(Number(value)) ? Number(value) : fallback
}

function save() {
  ensurePrimaryCamera()
  emit('save', {
    ...form,
    cameras: Array.isArray(form.cameras) ? form.cameras.map(camera => ({ ...camera })) : [],
  })
}
</script>

<template>
  <div class="modal-backdrop" @click="emit('cancel')">
    <div class="modal" @click.stop>
      <div class="modal-head">
        <h3>{{ form._isNew ? t('form.new') : `${t('form.edit')} ${form.id}` }}</h3>
        <button class="icon-btn" type="button" @click="emit('cancel')">✕</button>
      </div>
      <div class="modal-body">
        <div class="field"><label>{{ t('form.name') }}</label><input v-model="form.name"
            :placeholder="t('form.name.placeholder')"></div>
        <div class="field"><label>{{ t('form.address') }}</label><input v-model="form.address"
            :placeholder="t('form.address.placeholder')"></div>
        <div class="field-row">
          <div class="field"><label>{{ t('form.lat') }}</label><input :value="form.lat" type="number" step="0.0001"
              @input="updateNumber('lat', $event.target.value)"></div>
          <div class="field"><label>{{ t('form.lng') }}</label><input :value="form.lng" type="number" step="0.0001"
              @input="updateNumber('lng', $event.target.value)"></div>
        </div>
        <div class="field-row">
          <div class="field">
            <label>{{ t('form.state') }}</label>
            <select v-model="form.state">
              <option value="enabled">{{ t('lots.state.active') }}</option>
              <option value="disabled">{{ t('lots.state.inactive') }}</option>
            </select>
          </div>
          <div class="field"><label>{{ t('form.operator') }}</label><input v-model="form.owner"
              :placeholder="t('form.operator.placeholder')"></div>
        </div>
        <div class="field-row">
          <div class="field"><label>{{ t('form.rate') }}</label><input :value="form.rate" type="number" min="0"
              step="0.5" @input="updateNumber('rate', parseFloat($event.target.value) || 0)"></div>
          <div class="field"><label>{{ t('form.hours') }}</label><input v-model="form.hours"
              :placeholder="t('form.hours.placeholder')"></div>
        </div>
        <div v-if="form._isNew && primaryCamera" class="field-group">
          <div class="field-group-title">{{ t('form.camera.title') }}</div>
          <div class="field-row">
            <div class="field"><label>{{ t('form.camera.name') }}</label><input v-model="primaryCamera.name"
                :placeholder="t('form.camera.name.placeholder')"></div>
            <div class="field">
              <label>{{ t('form.camera.type') }}</label>
              <select v-model="primaryCamera.camera_type" disabled>
                <option value="panoramic">{{ t('form.camera.type.panoramic') }}</option>
              </select>
            </div>
          </div>
          <div class="field"><label>{{ t('form.camera.stream') }}</label><input v-model="primaryCamera.stream_url"
              :placeholder="t('form.camera.stream.placeholder')"></div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn" type="button" @click="emit('cancel')">{{ t('lots.cancel') }}</button>
        <button class="btn btn-primary" type="button" :disabled="!canSave"
          @click="save">{{ form._isNew ? t('form.add') : t('form.save') }}</button>
      </div>
    </div>
  </div>
</template>
