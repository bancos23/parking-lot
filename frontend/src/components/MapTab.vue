<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { colorForOccupancy, spaceTypeGlyph } from '@frontend/data/parkingData'
import { useT } from '@frontend/composables/i18n'
import { MAP_CENTER, hasSpaceType, primarySpaceType, useParkingLots } from '@frontend/composables/parkingLots'
import { openDirections } from '@frontend/utils/maps'
import CameraFeedWrapper from '@frontend/components/CameraFeedWrapper.vue'

const props = defineProps({ role: { type: String, default: 'guest' } })
const { t, lang } = useT()
const { lots, loading, error, loadLots, applyOccupancySnapshot } = useParkingLots()
const mapRef = ref(null)
const mapInstance = ref(null)
let markersLayer = null
let layerRefreshFrame = null
let lotsRefreshTimer = null
let isUnmounting = false

const selectedId = ref(null)
const search = ref('')
const filter = ref('all')
const sidebarOpen = ref(false)
const cameraPreviewOpen = ref(false)

const filteredLots = computed(() => lots.value.filter(lot => {
  if (lot.state === 'disabled') return false
  if (filter.value === 'electric' && !hasSpaceType(lot, 'electric')) return false
  if (filter.value === 'handicap' && !hasSpaceType(lot, 'handicap')) return false
  if (filter.value === 'normal' && !hasSpaceType(lot, 'normal')) return false
  if (filter.value === 'available' && lot.total > 0 && lot.occupied / lot.total > 0.85) return false
  const q = search.value.toLowerCase()
  if (q && !lot.name.toLowerCase().includes(q) && !lot.address.toLowerCase().includes(q)) return false
  return true
}))
const selected = computed(() => lots.value.find(l => l.id === selectedId.value))
const canViewCamera = computed(() => props.role !== 'guest')
const selectedCamera = computed(() => {
  const cameras = Array.isArray(selected.value?.cameras) ? selected.value.cameras : []
  return cameras.find(camera => camera.is_active !== false && camera.is_primary && camera.stream_url)
    || cameras.find(camera => camera.is_active !== false && camera.stream_url)
    || null
})

function lotSpaceTypes(lot) {
  return ['normal', 'electric', 'handicap']
    .filter(type => hasSpaceType(lot, type))
    .map(type => ({ type, count: lot.spaceTypeCounts[type] }))
}

function typeBadgeClass(type) {
  return type === 'electric' ? 'badge-good' : type === 'handicap' ? 'badge-bad' : 'badge-info'
}

function typeLabel(type) {
  return type === 'electric'
    ? t('spot.type.electric')
    : type === 'handicap'
      ? t('spot.type.handicap')
      : t('spot.type.normal')
}

function ensureLeaflet() {
  if (!window.L) throw new Error('Leaflet is not loaded. Keep the Leaflet CDN scripts in index.html or install/import Leaflet.')
  return window.L
}

function refreshMapLayers() {
  const map = mapInstance.value
  if (!map) return

  map.invalidateSize({ pan: false, debounceMoveend: true })
  markersLayer?.eachLayer?.((layer) => layer.update?.())
}

function scheduleLayerRefresh() {
  if (isUnmounting) return
  if (layerRefreshFrame) cancelAnimationFrame(layerRefreshFrame)

  layerRefreshFrame = requestAnimationFrame(() => {
    layerRefreshFrame = null
    refreshMapLayers()
  })
}

function clearMarkersLayer() {
  const layer = markersLayer
  markersLayer = null
  if (!layer) return

  const map = mapInstance.value
  if (map?.hasLayer?.(layer)) map.removeLayer(layer)
  layer.clearLayers?.()
}

function renderMarkers() {
  const L = ensureLeaflet()
  const map = mapInstance.value
  if (!map || isUnmounting) return

  map.closePopup()
  clearMarkersLayer()

  const group = L.layerGroup()

  filteredLots.value.forEach(lot => {
    const color = colorForOccupancy(lot.occupied, lot.total)
    const free = lot.occupied
    const markerType = primarySpaceType(lot)
    const icon = L.divIcon({
      className: '',
      iconSize: [32, 40],
      iconAnchor: [16, 40],
      popupAnchor: [0, -36],
      html: `<div class="leaflet-marker-pin"><div class="pin-body" style="background:${color}"><div class="label">${spaceTypeGlyph(markerType)}</div></div></div>`,
    })
    const marker = L.marker([lot.lat, lot.lng], { icon })
    marker.bindPopup(`
      <div style="font-family: var(--font-sans); min-width:160px;">
        <div style="font-weight:600; font-size:13px; margin-bottom:2px;">${lot.name}</div>
        <div style="font-size:11px; color: var(--text-muted); margin-bottom:6px;">${lot.address}</div>
        <div style="font-family: var(--font-mono); font-size:12px;"><strong style="color:${color}">${free}</strong> / ${lot.total} ${t('lot.spots_free')}</div>
      </div>
    `)
    marker.on('click', () => { selectedId.value = lot.id })
    group.addLayer(marker)
  })

  group.addTo(map)
  markersLayer = group
  scheduleLayerRefresh()
}

function focusMap(location, zoom) {
  const map = mapInstance.value
  if (!map) return

  map.stop()
  map.setView(location, zoom, { animate: false })
  refreshMapLayers()
}

function zoomBy(delta) {
  const map = mapInstance.value
  if (!map) return

  map.stop()
  map.setZoom(map.getZoom() + delta, { animate: false })
  refreshMapLayers()
}

function openPaymentLink(lot) {
  if (!lot?.paymentLink) return
  window.open(lot.paymentLink, '_blank')
}

onMounted(async () => {
  await nextTick()
  isUnmounting = false
  loadLots().catch(() => {})
  lotsRefreshTimer = setInterval(() => {
    loadLots({ force: true }).catch(() => {})
  }, 60000)
  const L = ensureLeaflet()
  if (!mapRef.value) return
  const map = L.map(mapRef.value, {
    center: MAP_CENTER,
    zoom: 14,
    maxZoom: 19,
    zoomAnimation: false,
    markerZoomAnimation: false,
    zoomControl: false,
    attributionControl: false,
  })
  L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', { subdomains: 'abcd', maxZoom: 19 }).addTo(map)
  L.control.attribution({ position: 'bottomright', prefix: false }).addAttribution('© OpenStreetMap, © CARTO').addTo(map)
  mapInstance.value = map
  map.on('zoomend moveend viewreset resize', scheduleLayerRefresh)
  renderMarkers()
})

onBeforeUnmount(() => {
  isUnmounting = true
  if (lotsRefreshTimer) {
    clearInterval(lotsRefreshTimer)
    lotsRefreshTimer = null
  }
  if (layerRefreshFrame) cancelAnimationFrame(layerRefreshFrame)
  layerRefreshFrame = null

  const map = mapInstance.value
  mapInstance.value = null

  if (!map) return

  map.off('zoomend moveend viewreset resize', scheduleLayerRefresh)

  if (markersLayer) {
    const layer = markersLayer
    markersLayer = null
    if (map.hasLayer?.(layer)) map.removeLayer(layer)
    layer.clearLayers?.()
  }

  map.remove()
})
watch([filteredLots, lang], renderMarkers)
watch(selected, (lot) => {
  if (!lot) return
  focusMap([lot.lat, lot.lng], 16)
})
watch(selectedId, () => {
  cameraPreviewOpen.value = false
})
</script>

<template>
  <div class="map-wrap">
    <button class="sidebar-toggle mobile-only" type="button" aria-label="List" @click="sidebarOpen = !sidebarOpen">☰
      <span>{{ filteredLots.length }} {{ t('map.lots_count') }}</span></button>

    <aside class="map-sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-handle mobile-only" @click="sidebarOpen = !sidebarOpen"></div>
      <div class="search-bar">
        <div class="search-input">
          <span class="search-ico">⌕</span>
          <input v-model="search" :placeholder="t('map.search.placeholder')">
          <button v-if="search" class="btn-ghost" type="button"
            style="padding:0;background:none;border:0;color:var(--text-faint)" @click="search = ''">✕</button>
        </div>
        <div class="filter-chips">
          <button v-for="item in [
            { v: 'all', l: t('map.filter.all') },
            { v: 'available', l: t('map.filter.available') },
            { v: 'normal', l: t('map.filter.normal') },
            { v: 'electric', l: t('map.filter.electric') },
            { v: 'handicap', l: t('map.filter.handicap') },
          ]" :key="item.v" class="chip" :class="{ active: filter === item.v }" type="button"
            @click="filter = item.v">{{ item.l }}</button>
        </div>
      </div>

      <div class="lot-list">
        <div v-for="lot in filteredLots" :key="lot.id" class="lot-row" :class="{ active: selectedId === lot.id }"
          @click="selectedId = lot.id; sidebarOpen = false">
          <div class="lot-icon" :style="{ background: colorForOccupancy(lot.occupied, lot.total) }">{{
            spaceTypeGlyph(primarySpaceType(lot)) }}</div>
          <div>
            <div class="lot-name">{{ lot.name }}</div>
            <div class="lot-addr">{{ lot.address }}</div>
          </div>
          <div class="lot-meta"><strong :style="{ color: colorForOccupancy(lot.occupied, lot.total) }">{{ lot.occupied }}</strong>
            <div>/ {{ lot.total }}</div>
          </div>
        </div>
        <div v-if="loading" class="empty-state"><span class="spinner"></span></div>
        <div v-else-if="error" class="empty-state">{{ error }}</div>
        <div v-else-if="filteredLots.length === 0" class="empty-state">
          <div class="empty-state-icon">🅿️</div>
          <div class="empty-state-text">{{ t('map.empty') }}</div>
        </div>
      </div>

      <div class="legend">
        <div class="li"><span class="dot" style="background:#16a34a"></span> {{ t('map.legend.free') }}</div>
        <div class="li"><span class="dot" style="background:#d97706"></span> {{ t('map.legend.partial') }}</div>
        <div class="li"><span class="dot" style="background:#dc2626"></span> {{ t('map.legend.full') }}</div>
      </div>
    </aside>

    <div class="map-area">
      <div id="leaflet-map" ref="mapRef"></div>

      <div class="map-controls">
        <button class="ctrl" type="button" title="Mărește" @click="zoomBy(1)">＋</button>
        <button class="ctrl" type="button" title="Micșorează" @click="zoomBy(-1)">−</button>
      </div>

      <div v-if="selected" class="lot-detail">
        <div class="lot-detail-head">
          <div style="flex:1">
            <h3>{{ selected.name }}</h3>
            <div class="addr">{{ selected.address }}</div>
            <div style="display:flex;gap:6px;margin-top:8px">
              <span v-for="item in lotSpaceTypes(selected)" :key="item.type" class="badge"
                :class="typeBadgeClass(item.type)">
                {{ typeLabel(item.type) }} - {{ item.count }}
              </span>
              <span class="badge badge-muted">{{ selected.hours }}</span>
            </div>
          </div>
          <button class="close-btn" type="button" @click="selectedId = null">✕</button>
        </div>

        <div class="lot-detail-body">
          <div style="display:flex;justify-content:space-between;align-items:baseline">
            <div class="section-label">{{ t('lot.occupancy.live') }}</div>
            <div style="font-family:var(--font-mono);font-size:13px"><strong
                :style="{ color: colorForOccupancy(selected.occupied, selected.total) }">{{ selected.occupied }}</strong><span
                style="color:var(--text-muted)"> / {{ selected.total }}</span></div>
          </div>
          <div class="occ-bar">
            <div class="fill"
              :style="{ width: `${(selected.occupied / selected.total) * 100}%`, background: colorForOccupancy(selected.occupied, selected.total) }">
            </div>
          </div>
          <div class="kv-grid">
            <div class="kv">
              <div class="k">{{ t('lot.rate') }}</div>
              <div class="v">{{ selected.rate === 0 ? t('lot.free') : `${selected.rate} ${t('lot.lei_per_h')}` }}</div>
            </div>
            <div class="kv">
              <div class="k">{{ t('lot.hours') }}</div>
              <div class="v">{{ selected.hours }}</div>
            </div>
            <div class="kv">
              <div class="k">{{ t('lot.operator') }}</div>
              <div class="v">{{ selected.owner }}</div>
            </div>
            <div class="kv">
              <div class="k">{{ t('lot.coords') }}</div>
              <div class="v mono">{{ selected.lat.toFixed(4) }}, {{ selected.lng.toFixed(4) }}</div>
            </div>
          </div>
        </div>

        <div class="lot-detail-actions">
          <button class="btn" type="button" @click="openDirections(selected.lat, selected.lng)">{{ t('lot.navigate') }}</button>
          <a class="btn btn-primary" :href="selected.paymentLink" target="_blank" rel="noopener noreferrer">{{ t('lot.pay_now') }}</a>
          <button v-if="canViewCamera && selectedCamera" class="btn btn-primary btn-live-camera" type="button"
            @click="cameraPreviewOpen = true">
            {{ t('lot.live_camera') }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="cameraPreviewOpen && selectedCamera" class="modal-backdrop" @click="cameraPreviewOpen = false">
      <div class="modal camera-preview-modal" @click.stop>
        <div class="modal-head">
          <h3>{{ selected.name }} - {{ t('lot.live_camera') }}</h3>
          <button class="icon-btn" type="button" @click="cameraPreviewOpen = false">✕</button>
        </div>
        <div class="modal-body">
          <CameraFeedWrapper
            :camera-id="selectedCamera.id"
            :camera-name="selectedCamera.name"
            :camera-type="selectedCamera.camera_type"
            :stream-url="selectedCamera.stream_url"
            @occupancy="applyOccupancySnapshot"
          />
        </div>
      </div>
    </div>
  </div>
</template>
