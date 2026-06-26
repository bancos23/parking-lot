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
  forceRefreshOnMount: {
    type: Boolean,
    default: false,
  },
})
const emit = defineEmits(['occupancy'])
const { t } = useT()
const { expireSession } = useAuth()

const stageRef = ref(null)
const mediaRef = ref(null)
const overlayCanvas = ref(null)
const overlayStyle = ref({})
const videoFailed = ref(false)
const imageFailed = ref(false)
const occupancy = ref(null)
const occupancyLoading = ref(false)
const occupancyError = ref('')

let resizeObserver
let occupancyTimer
let snapshotAbortController
let forceRefreshAbortController
let snapshotInFlight = false
let forceRefreshInFlight = false
let occupancyRunId = 0

const YOUTUBE_REFERENCE_FRAME = { width: 1920, height: 1080 }

const normalizedUrl = computed(() => props.streamUrl.trim())
const lowerUrl = computed(() => normalizedUrl.value.toLowerCase())
const isImageFeed = computed(() => /\.(mjpeg|mjpg|jpg|jpeg|png|webp|gif)(\?.*)?(#.*)?$/.test(lowerUrl.value))
const isRtspFeed = computed(() => lowerUrl.value.startsWith('rtsp://') || lowerUrl.value.startsWith('rtsps://'))
const youtubeVideoId = computed(() => extractYouTubeVideoId(normalizedUrl.value))
const isYouTubeFeed = computed(() => Boolean(youtubeVideoId.value))
const iframeUrl = computed(() => {
  if (youtubeVideoId.value) {
    const params = new URLSearchParams({
      autoplay: '1',
      mute: '1',
      playsinline: '1',
      rel: '0',
    })

    if (typeof window !== 'undefined' && window.location?.origin)
      params.set('origin', window.location.origin)

    return `https://www.youtube.com/embed/${youtubeVideoId.value}?${params.toString()}`
  }

  return normalizedUrl.value
})
const iframeReferrerPolicy = computed(() => (isYouTubeFeed.value ? 'strict-origin-when-cross-origin' : 'no-referrer'))
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
  return isYouTubeFeed.value || (
    !isRtspFeed.value && ((!isImageFeed.value && videoFailed.value) || (isImageFeed.value && imageFailed.value))
  )
})

function extractYouTubeVideoId(rawUrl) {
  if (!rawUrl) return ''

  try {
    const url = parseFeedUrl(rawUrl)
    const host = url.hostname.replace(/^www\./, '').toLowerCase()
    const pathParts = url.pathname.split('/').filter(Boolean)

    if (host === 'youtu.be') {
      return sanitizeYouTubeVideoId(pathParts[0])
    }

    if (host === 'youtube.com' || host === 'm.youtube.com' || host === 'youtube-nocookie.com') {
      const byQuery = sanitizeYouTubeVideoId(url.searchParams.get('v'))
      if (byQuery) return byQuery

      const embedIndex = pathParts.findIndex(part => ['embed', 'live', 'shorts'].includes(part))
      if (embedIndex >= 0) {
        return sanitizeYouTubeVideoId(pathParts[embedIndex + 1])
      }
    }
  } catch {
    return ''
  }

  return ''
}

function parseFeedUrl(rawUrl) {
  try {
    return new URL(rawUrl)
  } catch {
    return new URL(`https://${rawUrl}`)
  }
}

function sanitizeYouTubeVideoId(value) {
  const match = String(value || '').match(/^[\w-]{11}$/)
  return match?.[0] || ''
}

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

function normalizeFrameSize(frame) {
  const width = Number(frame?.width || 0)
  const height = Number(frame?.height || 0)
  if (width > 0 && height > 0) {
    return { width, height }
  }
  return null
}

function frameSizeFromSpaces(spaces) {
  for (const space of spaces) {
    const frame = normalizeFrameSize(space.polygon?.frame) || normalizeFrameSize(space.bounding_box?.frame)
    if (frame) return frame
  }

  return null
}

function overlaySourceSize(spaces = occupancy.value?.spaces || []) {
  return frameSizeFromSpaces(spaces) || (isYouTubeFeed.value ? YOUTUBE_REFERENCE_FRAME : mediaIntrinsicSize())
}

function mediaIntrinsicSize() {
  const media = mediaRef.value
  const width = Number(media?.videoWidth || media?.naturalWidth || 0)
  const height = Number(media?.videoHeight || media?.naturalHeight || 0)
  if (width > 0 && height > 0) {
    return { width, height }
  }
  return null
}

function containedMediaRect(containerWidth, containerHeight, sourceSize) {
  if (!sourceSize || containerWidth <= 0 || containerHeight <= 0) {
    return { left: 0, top: 0, width: containerWidth, height: containerHeight }
  }

  const containerRatio = containerWidth / containerHeight
  const sourceRatio = sourceSize.width / sourceSize.height

  if (sourceRatio > containerRatio) {
    const height = containerWidth / sourceRatio
    return {
      left: 0,
      top: (containerHeight - height) / 2,
      width: containerWidth,
      height,
    }
  }

  const width = containerHeight * sourceRatio
  return {
    left: (containerWidth - width) / 2,
    top: 0,
    width,
    height: containerHeight,
  }
}

function overlayTransform(spaces) {
  const canvas = overlayCanvas.value
  if (!canvas) return null

  const { maxX, maxY } = collectSpaceExtents(spaces)
  const pixelRatio = window.devicePixelRatio || 1

  if (maxX <= 1 && maxY <= 1) {
    return {
      x: value => Number(value || 0) * canvas.width,
      y: value => Number(value || 0) * canvas.height,
    }
  }

  const sourceSize = overlaySourceSize(spaces)
  if (sourceSize) {
    return {
      x: value => Number(value || 0) * (canvas.width / sourceSize.width),
      y: value => Number(value || 0) * (canvas.height / sourceSize.height),
    }
  }

  const cssWidth = canvas.width / pixelRatio
  const cssHeight = canvas.height / pixelRatio
  if (maxX <= cssWidth && maxY <= cssHeight) {
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
  const scale = window.devicePixelRatio || 1
  const paddingX = 3 * scale
  const paddingY = 2 * scale
  const labelHeight = 14 * scale
  ctx.font = `600 ${9 * scale}px Inter, system-ui, sans-serif`
  ctx.textBaseline = 'top'
  const width = ctx.measureText(label).width + (paddingX * 2)
  ctx.fillStyle = 'rgba(5, 7, 13, 0.72)'
  ctx.fillRect(x, y, width, labelHeight)
  ctx.fillStyle = color
  ctx.fillText(label, x + paddingX, y + paddingY)
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
    ctx.lineWidth = 2 * (window.devicePixelRatio || 1)

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
  const mediaRect = containedMediaRect(rect.width, rect.height, overlaySourceSize())
  const width = Math.max(1, Math.round(mediaRect.width * pixelRatio))
  const height = Math.max(1, Math.round(mediaRect.height * pixelRatio))

  overlayStyle.value = {
    left: `${mediaRect.left}px`,
    top: `${mediaRect.top}px`,
    width: `${mediaRect.width}px`,
    height: `${mediaRect.height}px`,
  }

  if (canvas.width !== width) {
    canvas.width = width
  }

  if (canvas.height !== height) {
    canvas.height = height
  }

  drawOccupancyOverlay()
}

function tryAutoplayMedia() {
  const media = mediaRef.value
  if (typeof media?.play !== 'function') return

  media.muted = true
  const playPromise = media.play()
  if (typeof playPromise?.catch === 'function') {
    playPromise.catch(() => { })
  }
}

function handleVideoReady() {
  syncOverlaySize()
  tryAutoplayMedia()
}

function resetFeedState() {
  videoFailed.value = false
  imageFailed.value = false
  nextTick(handleVideoReady)
}

function spaceIsOccupied(space) {
  return space?.occupied === true || space?.status === 'occupied'
}

function spaceTypeCounts(spaces) {
  return spaces.reduce((counts, space) => {
    const type = space.space_type || 'normal'
    counts[type] = (counts[type] || 0) + 1
    return counts
  }, {})
}

function normalizeDetectionSnapshot(data) {
  const spaces = Array.isArray(data?.spaces) ? data.spaces : []
  const total = spaces.length
  const occupied = spaces.filter(spaceIsOccupied).length
  const available = Math.max(0, total - occupied)
  const previousSpaces = Array.isArray(occupancy.value?.spaces) ? occupancy.value.spaces : []
  const previousCameraOccupied = previousSpaces.filter(spaceIsOccupied).length
  const previousLotTotal = Number(occupancy.value?.lot_total_spots ?? total)
  const previousLotOccupied = Number(occupancy.value?.lot_occupied_spots ?? previousCameraOccupied)
  const lotOccupied = Math.max(0, Math.min(previousLotTotal, previousLotOccupied - previousCameraOccupied + occupied))

  return {
    event: 'camera_occupancy_snapshot',
    generated_at: data?.generated_at || new Date().toISOString(),
    parking_lot_id: data?.parking_lot_id,
    parking_lot_name: data?.parking_lot_name || '',
    camera_id: data?.camera_id ?? props.cameraId,
    camera_name: props.cameraName,
    camera_type: props.cameraType,
    lot_total_spots: previousLotTotal,
    lot_occupied_spots: lotOccupied,
    lot_available_spots: Math.max(0, previousLotTotal - lotOccupied),
    lot_space_type_counts: occupancy.value?.lot_space_type_counts || spaceTypeCounts(spaces),
    camera_total_spots: total,
    camera_occupied_spots: occupied,
    camera_available_spots: available,
    spaces,
  }
}

function isCurrentOccupancyRun(runId) {
  return runId === occupancyRunId
}

function updateOccupancyLoading() {
  occupancyLoading.value = forceRefreshInFlight || (!occupancy.value && snapshotInFlight)
}

function stopOccupancyPolling() {
  if (occupancyTimer) {
    clearInterval(occupancyTimer)
    occupancyTimer = null
  }
  occupancyRunId += 1
  snapshotAbortController?.abort()
  forceRefreshAbortController?.abort()
  snapshotAbortController = null
  forceRefreshAbortController = null
  snapshotInFlight = false
  forceRefreshInFlight = false
  updateOccupancyLoading()
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

async function applyOccupancyData(data, runId) {
  if (!isCurrentOccupancyRun(runId)) return

  occupancyError.value = ''
  occupancy.value = data
  emit('occupancy', data)
  await nextTick()
  drawOccupancyOverlay()
}

async function refreshOccupancy(runId = occupancyRunId) {
  if (!props.cameraId || snapshotInFlight) return

  const controller = new AbortController()
  snapshotAbortController = controller
  snapshotInFlight = true
  occupancyError.value = ''
  updateOccupancyLoading()

  try {
    const data = await fetchCameraJson(`/api/cameras/${props.cameraId}/occupancy`, {
      signal: controller.signal,
    })

    await applyOccupancyData(data, runId)
  } catch (error) {
    if (error?.name !== 'AbortError' && isCurrentOccupancyRun(runId)) {
      occupancyError.value = error.message || 'Could not load camera occupancy.'
    }
  } finally {
    if (snapshotAbortController === controller) {
      snapshotAbortController = null
      snapshotInFlight = false
      updateOccupancyLoading()
    }
  }
}

async function forceRefreshOccupancy(runId = occupancyRunId) {
  if (!props.cameraId || forceRefreshInFlight) return

  const controller = new AbortController()
  forceRefreshAbortController = controller
  forceRefreshInFlight = true
  occupancyError.value = ''
  updateOccupancyLoading()

  try {
    const data = await fetchCameraJson(`/api/cameras/${props.cameraId}/detect-occupancy`, {
      method: 'POST',
      body: JSON.stringify({ source: 'live-camera-open' }),
      signal: controller.signal,
    })

    await applyOccupancyData(normalizeDetectionSnapshot(data), runId)
  } catch (error) {
    if (error?.name !== 'AbortError' && isCurrentOccupancyRun(runId)) {
      occupancyError.value = error.message || 'Could not load camera occupancy.'
    }
  } finally {
    if (forceRefreshAbortController === controller) {
      forceRefreshAbortController = null
      forceRefreshInFlight = false
      updateOccupancyLoading()
    }
  }
}

function startOccupancyPolling() {
  stopOccupancyPolling()
  const runId = occupancyRunId
  refreshOccupancy(runId)
  if (props.forceRefreshOnMount) {
    forceRefreshOccupancy(runId)
  }
  occupancyTimer = setInterval(() => refreshOccupancy(runId), props.pollIntervalMs)
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
  overlayStyle,
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

      <video v-else-if="!isRtspFeed && !isYouTubeFeed && !videoFailed" ref="mediaRef" class="feed-media"
        :src="normalizedUrl" controls autoplay muted playsinline preload="auto" crossorigin="anonymous"
        @error="videoFailed = true" @loadedmetadata="handleVideoReady" @loadeddata="handleVideoReady"
        @canplay="handleVideoReady" />

      <iframe v-else-if="showFrameFallback" class="feed-frame" :src="iframeUrl" :title="cameraName" loading="lazy"
        :referrerpolicy="iframeReferrerPolicy" allowfullscreen
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" />

      <div v-else class="feed-placeholder">
        Preview unavailable for this stream.
      </div>

      <canvas ref="overlayCanvas" class="feed-yolo-overlay" :style="overlayStyle" aria-hidden="true"></canvas>
    </div>

    <div class="feed-status-bar">
      <span v-if="occupancyLoading">{{ t('camera.occupancy.loading') }}</span>
      <span v-else-if="occupancyError" class="feed-status-error">{{ occupancyError }}</span>
      <span v-else-if="updatedAtLabel">{{ t('camera.occupancy.updated') }} {{ updatedAtLabel }}</span>
    </div>
  </div>
</template>
