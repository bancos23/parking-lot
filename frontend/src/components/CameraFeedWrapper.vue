<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useT } from '@frontend/composables/i18n'
import { useAuth } from '@frontend/stores/auth'

const props = defineProps({
  cameraId: {
    type: [Number, String],
    default: '',
  },
  cameraName: {
    type: String,
    required: true,
  },
  cameraType: {
    type: String,
    default: '',
  },
  streamUrl: {
    type: String,
    required: true,
  },
  pollIntervalMs: {
    type: Number,
    default: 60000,
  },
})
const emit = defineEmits(['occupancy'])
const { t } = useT()
const { expireSession } = useAuth()

const stageRef = ref(null)
const mediaRef = ref(null)
const overlayCanvas = ref(null)
const videoFailed = ref(false)
const imageFailed = ref(false)
const occupancy = ref(null)
const occupancyLoading = ref(false)
const occupancyError = ref('')

let resizeObserver
let occupancyTimer
let occupancyAbortController
let occupancyInFlight = false

const normalizedUrl = computed(() => props.streamUrl.trim())
const lowerUrl = computed(() => normalizedUrl.value.toLowerCase())
const isImageFeed = computed(() => /\.(mjpeg|mjpg|jpg|jpeg|png|webp|gif)(\?.*)?(#.*)?$/.test(lowerUrl.value))
const isRtspFeed = computed(() => lowerUrl.value.startsWith('rtsp://') || lowerUrl.value.startsWith('rtsps://'))
const cameraTypeLabel = computed(() => props.cameraType.replace(/_/g, ' '))
const cameraTotalSpaces = computed(() => Number(occupancy.value?.camera_total_spots ?? 0))
const cameraOccupiedSpaces = computed(() => Number(occupancy.value?.camera_occupied_spots ?? 0))
const occupancyPercent = computed(() => {
  if (!cameraTotalSpaces.value) return 0
  return Math.round((cameraOccupiedSpaces.value / cameraTotalSpaces.value) * 100)
})
const updatedAtLabel = computed(() => {
  if (!occupancy.value?.generated_at) return ''
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(occupancy.value.generated_at))
})
const showFrameFallback = computed(() => {
  return !isRtspFeed.value && ((!isImageFeed.value && videoFailed.value) || (isImageFeed.value && imageFailed.value))
})

function statusColor(space) {
  if (!space.is_active || space.status === 'out_of_service') return '#9ca3af'
  if (space.occupied || space.status === 'occupied') return '#dc2626'
  if (space.status === 'reserved') return '#d97706'
  return '#16a34a'
}

function collectSpaceExtents(spaces) {
  let maxX = 0
  let maxY = 0

  spaces.forEach((space) => {
    if (space.bounding_box) {
      maxX = Math.max(maxX, Number(space.bounding_box.x || 0) + Number(space.bounding_box.width || 0))
      maxY = Math.max(maxY, Number(space.bounding_box.y || 0) + Number(space.bounding_box.height || 0))
    }
    if (space.polygon?.points) {
      space.polygon.points.forEach(([x, y]) => {
        maxX = Math.max(maxX, Number(x || 0))
        maxY = Math.max(maxY, Number(y || 0))
      })
    }
  })

  return { maxX, maxY }
}

function overlayTransform(spaces) {
  const canvas = overlayCanvas.value
  const stage = stageRef.value
  if (!canvas || !stage) return null

  const { maxX, maxY } = collectSpaceExtents(spaces)
  const rect = stage.getBoundingClientRect()
  const pixelRatio = window.devicePixelRatio || 1

  if (maxX <= 1 && maxY <= 1) {
    return {
      x: value => Number(value || 0) * canvas.width,
      y: value => Number(value || 0) * canvas.height,
    }
  }

  if (maxX <= rect.width && maxY <= rect.height) {
    return {
      x: value => Number(value || 0) * pixelRatio,
      y: value => Number(value || 0) * pixelRatio,
    }
  }

  return {
    x: value => Number(value || 0) * (maxX ? canvas.width / maxX : 1),
    y: value => Number(value || 0) * (maxY ? canvas.height / maxY : 1),
  }
}

function drawSpaceLabel(ctx, label, x, y, color) {
  ctx.font = '600 12px Inter, system-ui, sans-serif'
  ctx.textBaseline = 'top'
  const width = ctx.measureText(label).width + 10
  ctx.fillStyle = 'rgba(5, 7, 13, 0.78)'
  ctx.fillRect(x, y, width, 22)
  ctx.fillStyle = color
  ctx.fillText(label, x + 5, y + 5)
}

function drawOccupancyOverlay() {
  const canvas = overlayCanvas.value
  const ctx = canvas?.getContext('2d')
  if (!canvas || !ctx) return

  ctx.clearRect(0, 0, canvas.width, canvas.height)

  const spaces = (occupancy.value?.spaces || []).filter(space => space.bounding_box || space.polygon?.points?.length)
  if (!spaces.length) return

  const transform = overlayTransform(spaces)
  if (!transform) return

  spaces.forEach((space) => {
    const color = statusColor(space)
    ctx.strokeStyle = color
    ctx.fillStyle = `${color}33`
    ctx.lineWidth = 3

    if (space.polygon?.points?.length) {
      const points = space.polygon.points
      ctx.beginPath()
      ctx.moveTo(transform.x(points[0][0]), transform.y(points[0][1]))
      points.slice(1).forEach(([x, y]) => ctx.lineTo(transform.x(x), transform.y(y)))
      ctx.closePath()
      ctx.fill()
      ctx.stroke()
      drawSpaceLabel(ctx, space.code, transform.x(points[0][0]), transform.y(points[0][1]), color)
      return
    }

    const box = space.bounding_box
    const x = transform.x(box.x)
    const y = transform.y(box.y)
    const width = transform.x(box.width)
    const height = transform.y(box.height)
    ctx.fillRect(x, y, width, height)
    ctx.strokeRect(x, y, width, height)
    drawSpaceLabel(ctx, space.code, x, y, color)
  })
}

function syncOverlaySize() {
  const stage = stageRef.value
  const canvas = overlayCanvas.value

  if (!stage || !canvas) {
    return
  }

  const rect = stage.getBoundingClientRect()
  const pixelRatio = window.devicePixelRatio || 1
  const width = Math.max(1, Math.round(rect.width * pixelRatio))
  const height = Math.max(1, Math.round(rect.height * pixelRatio))

  if (canvas.width !== width) {
    canvas.width = width
  }

  if (canvas.height !== height) {
    canvas.height = height
  }

  drawOccupancyOverlay()
}

function resetFeedState() {
  videoFailed.value = false
  imageFailed.value = false
  nextTick(syncOverlaySize)
}

function stopOccupancyPolling() {
  if (occupancyTimer) {
    clearInterval(occupancyTimer)
    occupancyTimer = null
  }
  occupancyAbortController?.abort()
  occupancyAbortController = null
  occupancyInFlight = false
}

async function fetchCameraJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'include',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  })
  const data = await response.json().catch(() => null)

  if (!response.ok) {
    if (response.status === 401) {
      expireSession()
    }

    throw new Error(data?.detail || 'Could not load camera occupancy.')
  }

  return data
}

async function refreshOccupancy() {
  if (!props.cameraId || occupancyInFlight) return

  const controller = new AbortController()
  occupancyAbortController = controller
  occupancyInFlight = true
  occupancyLoading.value = !occupancy.value
  occupancyError.value = ''

  try {
    const data = await fetchCameraJson(`/api/cameras/${props.cameraId}/occupancy`, {
      signal: controller.signal,
    })

    occupancy.value = data
    emit('occupancy', data)
    await nextTick()
    drawOccupancyOverlay()
  } catch (error) {
    if (error?.name !== 'AbortError') {
      occupancyError.value = error.message || 'Could not load camera occupancy.'
    }
  } finally {
    if (occupancyAbortController === controller) {
      occupancyAbortController = null
      occupancyInFlight = false
      occupancyLoading.value = false
    }
  }
}

function startOccupancyPolling() {
  stopOccupancyPolling()
  refreshOccupancy()
  occupancyTimer = setInterval(refreshOccupancy, props.pollIntervalMs)
}

onMounted(() => {
  resizeObserver = new ResizeObserver(syncOverlaySize)

  if (stageRef.value) {
    resizeObserver.observe(stageRef.value)
  }

  window.addEventListener('resize', syncOverlaySize)
  nextTick(syncOverlaySize)
  startOccupancyPolling()
})

onBeforeUnmount(() => {
  stopOccupancyPolling()
  resizeObserver?.disconnect()
  window.removeEventListener('resize', syncOverlaySize)
})

watch(() => props.streamUrl, resetFeedState)
watch(() => props.cameraId, startOccupancyPolling)
watch(() => props.pollIntervalMs, startOccupancyPolling)
watch(occupancy, () => nextTick(drawOccupancyOverlay), { deep: true })

defineExpose({
  mediaRef,
  overlayCanvas,
  syncOverlaySize,
})
</script>

<template>
  <div class="camera-feed-wrapper" :data-camera-id="cameraId" :data-camera-type="cameraType" data-yolo-wrapper="true">
    <div class="feed-wrapper-toolbar">
      <div>
        <strong>{{ cameraName }}</strong>
        <span>{{ cameraTypeLabel }}</span>
      </div>
      <div v-if="occupancy" class="feed-occupancy-summary">
        <strong>{{ cameraOccupiedSpaces }}</strong>
        <span>/ {{ cameraTotalSpaces }} {{ t('lot.spots_occupied') }}</span>
        <small>{{ occupancyPercent }}% {{ t('stats.kpi.occupancy') }}</small>
      </div>
    </div>

    <div ref="stageRef" class="feed-stage">
      <img v-if="isImageFeed && !imageFailed" ref="mediaRef" class="feed-media" :src="normalizedUrl" :alt="cameraName"
        crossorigin="anonymous" @error="imageFailed = true" @load="syncOverlaySize" />

      <video v-else-if="!isRtspFeed && !videoFailed" ref="mediaRef" class="feed-media" :src="normalizedUrl" controls
        muted playsinline crossorigin="anonymous" @error="videoFailed = true" @loadedmetadata="syncOverlaySize" />

      <iframe v-else-if="showFrameFallback" class="feed-frame" :src="normalizedUrl" :title="cameraName" loading="lazy"
        referrerpolicy="no-referrer" />

      <div v-else class="feed-placeholder">
        Preview unavailable for this stream.
      </div>

      <canvas ref="overlayCanvas" class="feed-yolo-overlay" aria-hidden="true"></canvas>
    </div>

    <div class="feed-status-bar">
      <span v-if="occupancyLoading">{{ t('camera.occupancy.loading') }}</span>
      <span v-else-if="occupancyError" class="feed-status-error">{{ occupancyError }}</span>
      <span v-else-if="updatedAtLabel">{{ t('camera.occupancy.updated') }} {{ updatedAtLabel }}</span>
    </div>
  </div>
</template>
