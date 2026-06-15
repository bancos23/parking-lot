<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useT } from '@frontend/composables/i18n'
import { useAuth } from '@frontend/stores/auth'

const props = defineProps({
  role: { type: String, default: 'guest' },
  embedded: { type: Boolean, default: false },
  lot: { type: Object, default: null },
})
const { t } = useT()
const { expireSession } = useAuth()

const imageFile = ref(null)
const imageUrl = ref(null)
const isDragging = ref(false)
const isDetecting = ref(false)
const error = ref('')
const detections = ref([])
const history = ref([])
const isLoadingHistory = ref(false)
const historyPage = ref(1)
const historyPageSize = ref(10)
const historyTotal = ref(0)
const historyTotalPages = ref(1)
const historyLoadedRows = ref(0)
const historyPageSizeOptions = [5, 10]
const searchQuery = ref('')
const fileInput = ref(null)
let historyRequestId = 0
let historySearchTimer = null

const filteredHistory = computed(() => history.value)

const historyRange = computed(() => {
  if (!historyTotal.value) return ''
  const start = (historyPage.value - 1) * historyPageSize.value + 1
  const end = Math.min(historyTotal.value, start + historyLoadedRows.value - 1)
  return `${start}-${end} / ${historyTotal.value}`
})

function historyRowPlate(row) {
  if (!row.plate && !row.raw_ocr && !row.compact) return null
  return {
    plate: row.plate,
    raw_ocr: row.raw_ocr,
    compact: row.compact,
    confidence: row.confidence,
    county_name: row.county_name,
    country_name: row.country_name,
    bbox: row.bounding_box,
  }
}

function groupHistoryRows(rows) {
  const grouped = new Map()

  for (const row of rows) {
    const timestamp = row.detected_at || row.created_at
    const key = [
      timestamp,
      row.source_file || '',
      row.image_width || '',
      row.image_height || '',
    ].join('|')

    if (!grouped.has(key)) {
      grouped.set(key, {
        id: key,
        fileName: row.source_file || 'Uploaded image',
        plates: [],
        timestamp: timestamp ? new Date(timestamp) : new Date(),
        imageWidth: row.image_width,
        imageHeight: row.image_height,
        totalDetections: row.total_detections || 0,
        parsedPlates: row.parsed_plates || 0,
      })
    }

    const plate = historyRowPlate(row)
    if (plate) grouped.get(key).plates.push(plate)
  }

  return [...grouped.values()].sort((a, b) => b.timestamp - a.timestamp)
}

async function loadHistory(page = historyPage.value) {
  const requestId = ++historyRequestId
  isLoadingHistory.value = true
  const requestedPage = Math.max(1, page)

  try {
    const params = new URLSearchParams({
      page: String(requestedPage),
      limit: String(historyPageSize.value),
    })
    const query = searchQuery.value.trim()
    if (query) params.set('plate', query)

    const response = await fetch(`/api/plates/history?${params}`, {
      credentials: 'include',
    })

    if (!response.ok) {
      if (response.status === 401) expireSession()
      throw new Error('Could not load plate history')
    }

    const data = await response.json()
    if (requestId !== historyRequestId) return
    const rows = data.detections || []
    history.value = groupHistoryRows(rows)
    historyLoadedRows.value = rows.length
    historyPage.value = data.page || requestedPage
    historyTotal.value = data.total || 0
    historyTotalPages.value = data.total_pages || 1
  } catch (err) {
    if (requestId === historyRequestId) console.warn(err)
  } finally {
    if (requestId === historyRequestId) isLoadingHistory.value = false
  }
}

function goToHistoryPage(page) {
  if (page < 1 || page > historyTotalPages.value || page === historyPage.value) return
  loadHistory(page)
}

function onHistoryPageSizeChange() {
  historyPage.value = 1
  loadHistory(1)
}

function scheduleHistoryLoad() {
  if (historySearchTimer) clearTimeout(historySearchTimer)
  historySearchTimer = setTimeout(() => {
    historyPage.value = 1
    loadHistory(1)
  }, 250)
}

function onDragOver(e) {
  e.preventDefault()
  isDragging.value = true
}

function onDragLeave() {
  isDragging.value = false
}

function onDrop(e) {
  e.preventDefault()
  isDragging.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file && file.type.startsWith('image/')) {
    loadImage(file)
  }
}

function onFileSelect(e) {
  const file = e.target.files?.[0]
  if (file) loadImage(file)
}

function loadImage(file) {
  if (file.size > 25 * 1024 * 1024) {
    error.value = t('plates.upload.too_large')
    return
  }
  imageFile.value = file
  imageUrl.value = URL.createObjectURL(file)
  detections.value = []
  error.value = ''
}

function clearImage() {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageFile.value = null
  imageUrl.value = null
  detections.value = []
  error.value = ''
}

function triggerFileInput() {
  fileInput.value?.click()
}

async function detect() {
  if (!imageFile.value || isDetecting.value) return
  isDetecting.value = true
  error.value = ''

  try {
    const formData = new FormData()
    formData.append('file', imageFile.value)

    const response = await fetch('/api/plates/detect', {
      method: 'POST',
      credentials: 'include',
      body: formData,
    })

    if (!response.ok) {
      if (response.status === 401) expireSession()
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Detection failed')
    }

    const result = await response.json()
    detections.value = result.plates || []

    historyPage.value = 1
    await loadHistory(1)
  } catch (err) {
    error.value = err.message || 'Detection failed'
  } finally {
    isDetecting.value = false
  }
}

function clearHistory() {
  if (!searchQuery.value) {
    historyPage.value = 1
    loadHistory(1)
    return
  }
  searchQuery.value = ''
}

function formatTime(date) {
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

function confidenceColor(conf) {
  if (conf >= 0.9) return 'var(--good)'
  if (conf >= 0.75) return 'var(--warn)'
  return 'var(--bad)'
}

onMounted(() => {
  loadHistory()
})

onBeforeUnmount(() => {
  if (historySearchTimer) clearTimeout(historySearchTimer)
})

watch(searchQuery, scheduleHistoryLoad)
</script>

<template>
  <div class="plates-wrap" :class="{ embedded }">
    <div v-if="!embedded" class="plates-head">
      <div>
        <h1>{{ t('plates.title') }}</h1>
        <div class="sub">{{ t('plates.sub') }}</div>
      </div>
    </div>

    <div class="plates-body">
      <div class="plates-upload-section">
        <div
          class="drop-zone"
          :class="{ dragging: isDragging, 'has-image': imageUrl }"
          @dragover="onDragOver"
          @dragleave="onDragLeave"
          @drop="onDrop"
          @click="triggerFileInput"
        >
          <input
            ref="fileInput"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            style="display: none"
            @change="onFileSelect"
          />

          <template v-if="!imageUrl">
            <div class="drop-icon">📷</div>
            <div class="drop-title">{{ t('plates.upload.title') }}</div>
            <div class="drop-hint">{{ t('plates.upload.hint') }}</div>
            <div class="drop-formats">{{ t('plates.upload.formats') }}</div>
          </template>

          <template v-else>
            <img :src="imageUrl" class="preview-img" alt="Uploaded" />
            <button class="clear-img-btn" @click.stop="clearImage">✕</button>
          </template>
        </div>

        <button
          v-if="imageUrl"
          class="btn btn-primary detect-btn"
          :disabled="isDetecting"
          @click="detect"
        >
          {{ isDetecting ? t('plates.detecting') : t('plates.detect') }}
        </button>

        <div v-if="error" class="plates-error">{{ error }}</div>
      </div>

      <div v-if="detections.length > 0 || (imageUrl && !isDetecting && detections.length === 0)" class="plates-results">
        <div class="results-header">
          <h2>{{ t('plates.results.title') }}</h2>
          <span class="results-count">
            {{ detections.length }} {{ t('plates.results.count') }}
          </span>
        </div>

        <div v-if="detections.length === 0" class="results-none">
          {{ t('plates.results.none') }}
        </div>

        <div v-else class="results-list">
          <div v-for="(det, i) in detections" :key="i" class="result-card">
            <div class="result-plate">{{ det.plate || det.raw_ocr || '—' }}</div>
            <div v-if="det.county_name" class="result-county">{{ det.county_name }}</div>
            <div class="result-meta">
              <div class="result-field">
                <span class="field-label">{{ t('plates.results.confidence') }}</span>
                <span class="field-value" :style="{ color: confidenceColor(det.confidence) }">
                  {{ (det.confidence * 100).toFixed(0) }}%
                </span>
              </div>
              <div class="result-field">
                <span class="field-label">{{ t('plates.results.bbox') }}</span>
                <span class="field-value mono">
                  {{ det.bbox.x }},{{ det.bbox.y }} {{ det.bbox.width }}×{{ det.bbox.height }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="plates-history">
        <div class="history-header">
          <h2>{{ t('plates.history.title') }}</h2>
          <div class="history-actions">
            <div class="search-box">
              <span class="search-icon">🔍</span>
              <input v-model="searchQuery" type="text" :placeholder="t('plates.search')" />
            </div>
            <select
              v-model.number="historyPageSize"
              class="history-page-size"
              :aria-label="t('plates.history.page_size')"
              @change="onHistoryPageSizeChange"
            >
              <option v-for="size in historyPageSizeOptions" :key="size" :value="size">
                {{ size }}
              </option>
            </select>
            <button class="btn-ghost" @click="loadHistory(historyPage)">
              {{ t('plates.history.refresh') }}
            </button>
            <button v-if="searchQuery" class="btn-ghost" @click="clearHistory">
              {{ t('plates.history.clear') }}
            </button>
          </div>
        </div>

        <div v-if="isLoadingHistory" class="history-empty">
          {{ t('plates.history.loading') }}
        </div>

        <div v-else-if="filteredHistory.length === 0" class="history-empty">
          {{ t('plates.history.empty') }}
        </div>

        <div v-else class="history-list">
          <div v-for="entry in filteredHistory" :key="entry.id" class="history-entry">
            <div class="he-info">
              <div class="he-name">{{ entry.fileName }}</div>
              <div class="he-time">{{ formatTime(entry.timestamp) }}</div>
            </div>
            <div class="he-plates">
              <span v-for="p in entry.plates" :key="p.plate || p.raw_ocr" class="he-plate-chip">
                {{ p.plate || p.raw_ocr || '—' }}
              </span>
              <span v-if="entry.plates.length === 0" class="he-plate-empty">—</span>
            </div>
          </div>
        </div>

        <div v-if="historyTotal > 0" class="history-pagination">
          <div class="history-page-info">{{ historyRange }}</div>
          <div class="history-page-controls">
            <button
              class="icon-btn"
              type="button"
              :disabled="historyPage <= 1 || isLoadingHistory"
              @click="goToHistoryPage(historyPage - 1)"
            >
              ‹
            </button>
            <span>{{ t('plates.history.page') }} {{ historyPage }} / {{ historyTotalPages }}</span>
            <button
              class="icon-btn"
              type="button"
              :disabled="historyPage >= historyTotalPages || isLoadingHistory"
              @click="goToHistoryPage(historyPage + 1)"
            >
              ›
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
