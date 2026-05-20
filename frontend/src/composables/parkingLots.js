import { computed, ref } from 'vue'
import { useAuth } from '../stores/auth'

export const MAP_CENTER = [47.6579, 23.5806]

const lots = ref([])
const loading = ref(false)
const error = ref('')
let loaded = false
let pendingLoad = null

function formatLotId(id) {
  return `P${String(id).padStart(3, '0')}`
}

function normalizeSpaceType(type) {
  return type === 'charging_station' ? 'electric' : type
}

function normalizeSpaceTypeCounts(rawCounts, total) {
  const counts = { normal: 0, electric: 0, handicap: 0 }
  const entries = Object.entries(rawCounts || {})

  entries.forEach(([key, value]) => {
    const type = normalizeSpaceType(key)
    if (Object.hasOwn(counts, type)) counts[type] += Number(value || 0)
  })

  const configuredTotal = counts.normal + counts.electric + counts.handicap
  if (total > configuredTotal) counts.normal += total - configuredTotal
  return counts
}

export function hasSpaceType(lot, type) {
  return Number(lot.spaceTypeCounts?.[type] || 0) > 0
}

export function primarySpaceType(lot) {
  if (hasSpaceType(lot, 'electric')) return 'electric'
  if (hasSpaceType(lot, 'handicap')) return 'handicap'
  return 'normal'
}

function normalizeLot(raw) {
  const rate = raw.is_free ? 0 : Number(raw.hourly_rate ?? 0)
  const total = Number(raw.total_spots ?? 0)
  const spaceTypeCounts = normalizeSpaceTypeCounts(raw.space_type_counts, total)

  return {
    id: formatLotId(raw.id),
    dbId: raw.id,
    name: raw.name,
    address: raw.address,
    lat: Number(raw.latitude ?? MAP_CENTER[0]),
    lng: Number(raw.longitude ?? MAP_CENTER[1]),
    total,
    occupied: Number(raw.occupied_spots ?? 0),
    spaceTypeCounts,
    state: raw.state || 'enabled',
    owner: raw.owner_name || '',
    rate,
    hours: raw.open_hours || '24/7',
    paymentLink: raw.payment_link || '',
    cameras: Array.isArray(raw.cameras) ? raw.cameras : [],
    revenue: Number(raw.revenue ?? 0),
  }
}

function cameraPayload(camera, lot, isPrimary = false) {
  return {
    name: camera.name || `${lot.name || 'Parking'} panoramic camera`,
    camera_type: camera.camera_type || 'panoramic',
    stream_url: camera.stream_url || '',
    is_active: camera.is_active !== false,
    is_primary: isPrimary,
  }
}

function lotPayload(lot, { includeCameras = false } = {}) {
  const rate = Number(lot.rate || 0)
  const payload = {
    name: lot.name,
    address: lot.address,
    latitude: Number(lot.lat),
    longitude: Number(lot.lng),
    state: lot.state || 'enabled',
    owner_name: lot.owner || null,
    hourly_rate: rate,
    is_free: rate === 0,
    open_hours: lot.hours || '24/7',
    payment_link: lot.paymentLink || null,
  }

  if (includeCameras) {
    const cameras = Array.isArray(lot.cameras) ? lot.cameras : []
    payload.cameras = cameras.map((camera, index) => cameraPayload(camera, lot, index === 0))
  }

  return payload
}

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'include',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  const data = response.status === 204 ? null : await response.json().catch(() => null)

  if (!response.ok) {
    if (response.status === 401) {
      useAuth().expireSession()
    }

    const detail = typeof data?.detail === 'string'
      ? data.detail
      : Array.isArray(data?.detail)
        ? data.detail.map(item => item.msg || item.message || String(item)).join(' ')
        : data?.message
    throw new Error(detail || 'Parking request failed.')
  }

  return data
}

async function loadLots({ force = false } = {}) {
  if (loaded && !force) return lots.value
  if (pendingLoad) return pendingLoad

  loading.value = true
  error.value = ''
  pendingLoad = apiRequest('/api/lots')
    .then((data) => {
      lots.value = (data?.lots || []).map(normalizeLot)
      loaded = true
      return lots.value
    })
    .catch((err) => {
      error.value = err.message || 'Could not load parking lots.'
      throw err
    })
    .finally(() => {
      loading.value = false
      pendingLoad = null
    })

  return pendingLoad
}

async function saveLot(lot) {
  const isNew = lot._isNew || !lot.dbId
  const data = await apiRequest(isNew ? '/api/lots' : `/api/lots/${lot.dbId}`, {
    method: isNew ? 'POST' : 'PATCH',
    body: JSON.stringify(lotPayload(lot, { includeCameras: isNew })),
  })
  const saved = normalizeLot(data)

  if (isNew) {
    lots.value = [...lots.value, saved].sort((a, b) => a.name.localeCompare(b.name))
  } else {
    lots.value = lots.value.map(item => item.dbId === saved.dbId ? saved : item)
  }
  loaded = true
  return saved
}

async function deleteLot(lot) {
  const dbId = typeof lot === 'object' ? lot.dbId : lot
  await apiRequest(`/api/lots/${dbId}`, { method: 'DELETE' })
  lots.value = lots.value.filter(item => item.dbId !== dbId)
}

function applyOccupancySnapshot(snapshot) {
  const dbId = Number(snapshot?.parking_lot_id)
  if (!dbId) return

  lots.value = lots.value.map((lot) => {
    if (lot.dbId !== dbId) return lot

    const total = Number(snapshot.lot_total_spots ?? lot.total)
    return {
      ...lot,
      total,
      occupied: Number(snapshot.lot_occupied_spots ?? lot.occupied),
      spaceTypeCounts: normalizeSpaceTypeCounts(snapshot.lot_space_type_counts, total),
    }
  })
}

export function useParkingLots() {
  return {
    lots,
    loading,
    error,
    enabledLots: computed(() => lots.value.filter(lot => lot.state === 'enabled')),
    loadLots,
    saveLot,
    deleteLot,
    applyOccupancySnapshot,
  }
}
