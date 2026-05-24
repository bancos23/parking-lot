<script setup>
import { computed, onMounted, ref } from 'vue'
import { colorForOccupancy } from '@frontend/data/parkingData'
import { hasSpaceType, useParkingLots } from '@frontend/composables/parkingLots'
import { useT } from '@frontend/composables/i18n'
import LotForm from '@frontend/components/LotForm.vue'

const props = defineProps({ role: { type: String, default: 'guest' } })
const { t } = useT()
const { lots, loading, error, loadLots, saveLot: saveParkingLot, deleteLot: deleteParkingLot } = useParkingLots()
const search = ref('')
const spaceTypeFilter = ref('all')
const stateFilter = ref('all')
const editing = ref(null)
const confirmDelete = ref(null)
const saving = ref(false)
const canEdit = computed(() => props.role !== 'guest')

const filtered = computed(() => lots.value.filter(l => {
  if (spaceTypeFilter.value !== 'all' && !hasSpaceType(l, spaceTypeFilter.value)) return false
  if (stateFilter.value !== 'all' && l.state !== stateFilter.value) return false
  const q = search.value.toLowerCase()
  if (q && !l.name.toLowerCase().includes(q) && !l.id.toLowerCase().includes(q) && !l.address.toLowerCase().includes(q)) return false
  return true
}))

onMounted(() => {
  loadLots().catch(() => {})
})

async function toggleState(id) {
  if (!canEdit.value) return
  const lot = lots.value.find(l => l.id === id)
  if (!lot) return
  await saveParkingLot({ ...lot, state: lot.state === 'enabled' ? 'disabled' : 'enabled' })
}

async function saveLot(lot) {
  saving.value = true
  try {
    await saveParkingLot(lot)
    editing.value = null
  } finally {
    saving.value = false
  }
}

async function deleteLot(lot) {
  saving.value = true
  try {
    await deleteParkingLot(lot)
    confirmDelete.value = null
  } finally {
    saving.value = false
  }
}

function newLot() {
  editing.value = {
    _isNew: true,
    name: '',
    address: '',
    lat: 47.6597,
    lng: 23.5795,
    state: 'enabled',
    owner: '',
    rate: 2,
    hours: '24/7',
    paymentLink: '',
    cameras: [
      {
        name: 'Panoramic camera',
        camera_type: 'panoramic',
        stream_url: '',
        is_active: true,
        is_primary: true,
      },
    ],
  }
}
</script>

<template>
  <div class="lots-wrap">
    <div class="lots-toolbar">
      <h1>{{ t('lots.title') }}</h1>
      <span class="count">{{ filtered.length }} / {{ lots.length }}</span>
      <div class="spacer"></div>
      <div class="search-input"><span>⌕</span><input v-model="search" :placeholder="t('lots.search')"></div>
      <select v-model="spaceTypeFilter" class="btn">
        <option value="all">{{ t('lots.filter.types.all') }}</option>
        <option value="normal">{{ t('lots.filter.type.normal') }}</option>
        <option value="electric">{{ t('lots.filter.type.electric') }}</option>
        <option value="handicap">{{ t('lots.filter.type.handicap') }}</option>
      </select>
      <select v-model="stateFilter" class="btn">
        <option value="all">{{ t('lots.filter.states.all') }}</option>
        <option value="enabled">{{ t('lots.filter.state.enabled') }}</option>
        <option value="disabled">{{ t('lots.filter.state.disabled') }}</option>
      </select>
      <button v-if="canEdit" class="btn btn-primary" type="button" @click="newLot">＋ {{ t('lots.add') }}</button>
    </div>

    <div class="table-wrap">
      <table class="lots-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>{{ t('lots.col.name') }}</th>
            <th>{{ t('lots.col.address') }}</th>
            <th style="text-align:right">{{ t('lots.col.spots') }}</th>
            <th style="text-align:right">{{ t('lots.col.occupancy') }}</th>
            <th>{{ t('lots.col.rate') }}</th>
            <th>{{ t('lots.col.operator') }}</th>
            <th>{{ t('lots.col.coords') }}</th>
            <th>{{ t('lots.col.state') }}</th>
            <th v-if="canEdit" style="width:100px"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="lot in filtered" :key="lot.id">
            <td class="mono muted">{{ lot.id }}</td>
            <td style="font-weight:500">{{ lot.name }}</td>
            <td class="muted small">{{ lot.address }}</td>
            <td class="mono" style="text-align:right">{{ lot.total }}</td>
            <td style="text-align:right">
              <div class="occ-inline">
                <div class="mini-bar">
                  <div
                    :style="{ width: `${Math.round((lot.occupied / lot.total) * 100)}%`, background: colorForOccupancy(lot.occupied, lot.total) }">
                  </div>
                </div>
                <span class="mono small">{{ Math.round((lot.occupied / lot.total) * 100) }}%</span>
              </div>
            </td>
            <td class="mono small"><span v-if="lot.rate === 0" class="muted">{{ t('lot.free') }}</span><template
                v-else>{{ lot.rate }} {{ t('lot.lei_per_h') }}</template>
            </td>
            <td class="muted small">{{ lot.owner }}</td>
            <td class="mono faint">{{ lot.lat.toFixed(4) }}, {{ lot.lng.toFixed(4) }}</td>
            <td>
              <div class="state-toggle">
                <div class="switch" :class="{ on: lot.state === 'enabled' }" @click="toggleState(lot.id)"></div><span
                  class="muted">{{ lot.state === 'enabled' ? t('lots.state.active') : t('lots.state.inactive') }}</span>
              </div>
            </td>
            <td v-if="canEdit">
              <div class="row-actions"><button class="icon-btn" type="button" :title="t('lots.action.edit')"
                  @click="editing = { ...lot }">✎</button><button class="icon-btn" type="button"
                  :title="t('lots.action.delete')" @click="confirmDelete = lot">🗑</button></div>
            </td>
          </tr>
          <tr v-if="loading">
            <td :colspan="canEdit ? 10 : 9" class="empty-row">Se încarcă...</td>
          </tr>
          <tr v-else-if="error">
            <td :colspan="canEdit ? 10 : 9" class="empty-row">{{ error }}</td>
          </tr>
          <tr v-else-if="filtered.length === 0">
            <td :colspan="canEdit ? 10 : 9" class="empty-row">{{ t('lots.empty') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <LotForm v-if="editing" :lot="editing" @save="saveLot" @cancel="editing = null" />

    <div v-if="confirmDelete" class="modal-backdrop" @click="confirmDelete = null">
      <div class="modal" @click.stop>
        <div class="modal-head">
          <h3>{{ t('lots.delete.title') }}</h3><button class="icon-btn" type="button"
            @click="confirmDelete = null">✕</button>
        </div>
        <div class="modal-body">
          <p class="muted" style="margin:0">{{ t('lots.delete.body.1') }} <strong style="color:var(--text)">{{
              confirmDelete.name }}</strong> ({{ confirmDelete.id }}) {{ t('lots.delete.body.2') }}</p>
        </div>
        <div class="modal-foot"><button class="btn" type="button" @click="confirmDelete = null">{{ t('lots.cancel')
            }}</button><button class="btn btn-danger" type="button" :disabled="saving" @click="deleteLot(confirmDelete)">{{
              t('lots.delete.confirm') }}</button></div>
      </div>
    </div>
  </div>
</template>
