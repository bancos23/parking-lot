<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

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
})

const stageRef = ref(null)
const mediaRef = ref(null)
const overlayCanvas = ref(null)
const videoFailed = ref(false)
const imageFailed = ref(false)

let resizeObserver

const normalizedUrl = computed(() => props.streamUrl.trim())
const lowerUrl = computed(() => normalizedUrl.value.toLowerCase())
const isImageFeed = computed(() => /\.(mjpeg|mjpg|jpg|jpeg|png|webp|gif)(\?.*)?(#.*)?$/.test(lowerUrl.value))
const isRtspFeed = computed(() => lowerUrl.value.startsWith('rtsp://') || lowerUrl.value.startsWith('rtsps://'))
const cameraTypeLabel = computed(() => props.cameraType.replace(/_/g, ' '))
const showFrameFallback = computed(() => {
  return !isRtspFeed.value && ((!isImageFeed.value && videoFailed.value) || (isImageFeed.value && imageFailed.value))
})

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
}

function resetFeedState() {
  videoFailed.value = false
  imageFailed.value = false
  nextTick(syncOverlaySize)
}

onMounted(() => {
  resizeObserver = new ResizeObserver(syncOverlaySize)

  if (stageRef.value) {
    resizeObserver.observe(stageRef.value)
  }

  window.addEventListener('resize', syncOverlaySize)
  nextTick(syncOverlaySize)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('resize', syncOverlaySize)
})

watch(() => props.streamUrl, resetFeedState)

defineExpose({
  mediaRef,
  overlayCanvas,
  syncOverlaySize,
})
</script>

<template>
  <div
    class="camera-feed-wrapper"
    :data-camera-id="cameraId"
    :data-camera-type="cameraType"
    data-yolo-wrapper="true"
  >
    <div class="feed-wrapper-toolbar">
      <strong>{{ cameraName }}</strong>
      <span>{{ cameraTypeLabel }}</span>
    </div>

    <div ref="stageRef" class="feed-stage">
      <img
        v-if="isImageFeed && !imageFailed"
        ref="mediaRef"
        class="feed-media"
        :src="normalizedUrl"
        :alt="cameraName"
        crossorigin="anonymous"
        @error="imageFailed = true"
        @load="syncOverlaySize"
      />

      <video
        v-else-if="!isRtspFeed && !videoFailed"
        ref="mediaRef"
        class="feed-media"
        :src="normalizedUrl"
        controls
        muted
        playsinline
        crossorigin="anonymous"
        @error="videoFailed = true"
        @loadedmetadata="syncOverlaySize"
      />

      <iframe
        v-else-if="showFrameFallback"
        class="feed-frame"
        :src="normalizedUrl"
        :title="cameraName"
        loading="lazy"
        referrerpolicy="no-referrer"
      />

      <div v-else class="feed-placeholder">
        Preview unavailable for this stream.
      </div>

      <canvas ref="overlayCanvas" class="feed-yolo-overlay" aria-hidden="true"></canvas>
    </div>
  </div>
</template>
