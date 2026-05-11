<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import CameraFeedWrapper from '../components/CameraFeedWrapper.vue'
import DashboardSidebar from '../components/DashboardSidebar.vue'

const router = useRouter()

const loading = ref(true)
const saving = ref(false)
const savingCamera = ref(false)
const error = ref('')
const notice = ref('')
const account = ref(null)
const lots = ref([])
const activeOperation = ref('lot')
const expandedCameraId = ref(null)

const lotForm = ref({
  name: '',
  address: '',
  total_spots: 0,
  panoramic_name: 'Panoramic feed',
  panoramic_url: '',
  number_plate_url: '',
  thermal_url: '',
})

const cameraForm = ref({
  parking_lot_id: '',
  name: '',
  camera_type: 'panoramic',
  stream_url: '',
})

const isLoggedIn = computed(() => Boolean(account.value))
const isAdmin = computed(() => account.value?.role === 'administrator')
const canManage = computed(() => isLoggedIn.value && isAdmin.value)
const totalLots = computed(() => lots.value.length)
const totalCameras = computed(() => {
  return lots.value.reduce((count, lot) => count + lot.cameras.length, 0)
})
const panoramicCameras = computed(() => {
  return lots.value.reduce((count, lot) => {
    return count + lot.cameras.filter((camera) => camera.camera_type === 'panoramic').length
  }, 0)
})

function cameraTypeLabel(type) {
  return type.replaceAll('_', ' ')
}

function toggleFeedPreview(cameraId) {
  expandedCameraId.value = expandedCameraId.value === cameraId ? null : cameraId
}

function buildCameraPayload() {
  const cameras = [
    {
      name: lotForm.value.panoramic_name || 'Panoramic feed',
      camera_type: 'panoramic',
      stream_url: lotForm.value.panoramic_url,
    },
  ]

  if (lotForm.value.number_plate_url.trim()) {
    cameras.push({
      name: 'Entrance number plate camera',
      camera_type: 'number_plate',
      stream_url: lotForm.value.number_plate_url,
    })
  }

  if (lotForm.value.thermal_url.trim()) {
    cameras.push({
      name: 'EV thermal camera',
      camera_type: 'thermal',
      stream_url: lotForm.value.thermal_url,
    })
  }

  return cameras
}

async function logout() {
  await fetch('/api/auth/logout', {
    method: 'POST',
    credentials: 'include',
  }).catch(() => {})

  account.value = null
  router.push('/login')
}

async function loadLots() {
  loading.value = true
  error.value = ''

  try {
    const res = await fetch('/api/lots', {
      credentials: 'include',
    })

    if (!res.ok) {
      throw new Error('Lots request failed')
    }

    const data = await res.json()
    account.value = data.account
    lots.value = data.lots || []
  } catch (e) {
    error.value = 'Could not load parking lots.'
  } finally {
    loading.value = false
  }
}

async function createLot() {
  saving.value = true
  error.value = ''
  notice.value = ''

  try {
    const res = await fetch('/api/lots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        name: lotForm.value.name,
        address: lotForm.value.address,
        total_spots: Number(lotForm.value.total_spots) || 0,
        cameras: buildCameraPayload(),
      }),
    })

    const data = await res.json().catch(() => ({}))

    if (!res.ok) {
      error.value = data.detail || 'Could not create parking lot'
      return
    }

    lots.value = [...lots.value, data].sort((a, b) => a.name.localeCompare(b.name))
    lotForm.value = {
      name: '',
      address: '',
      total_spots: 0,
      panoramic_name: 'Panoramic feed',
      panoramic_url: '',
      number_plate_url: '',
      thermal_url: '',
    }
    notice.value = 'Parking lot created with camera allocation.'
  } catch (e) {
    error.value = 'Could not connect to server.'
  } finally {
    saving.value = false
  }
}

async function createCamera() {
  savingCamera.value = true
  error.value = ''
  notice.value = ''

  try {
    const lotId = Number(cameraForm.value.parking_lot_id)
    const res = await fetch(`/api/lots/${lotId}/cameras`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        name: cameraForm.value.name,
        camera_type: cameraForm.value.camera_type,
        stream_url: cameraForm.value.stream_url,
      }),
    })

    const data = await res.json().catch(() => ({}))

    if (!res.ok) {
      error.value = data.detail || 'Could not create camera'
      return
    }

    lots.value = lots.value.map((lot) => {
      if (lot.id !== lotId) {
        return lot
      }

      return {
        ...lot,
        cameras: [...lot.cameras, data],
      }
    })

    cameraForm.value = {
      parking_lot_id: '',
      name: '',
      camera_type: 'panoramic',
      stream_url: '',
    }
    notice.value = 'Camera allocated to parking lot.'
  } catch (e) {
    error.value = 'Could not connect to server.'
  } finally {
    savingCamera.value = false
  }
}

onMounted(() => {
  loadLots()
})
</script>

<template>
  <section class="dashboard-page">
    <DashboardSidebar active-page="lots" :is-logged-in="isLoggedIn" @logout="logout" />

    <main class="dashboard-main">
      <header class="dashboard-header">
        <div>
          <p class="eyebrow">Camera allocation</p>
          <h1>Parking lots</h1>
          <span>Assign live feed, number plate, and thermal cameras to each parking lot.</span>
        </div>

        <div class="header-actions">
          <button
            v-if="canManage"
            class="primary-btn dashboard-action"
            type="button"
            @click="activeOperation = 'lot'"
          >
            Create parking lot
          </button>

          <button
            v-if="canManage"
            class="secondary-btn dashboard-action"
            type="button"
            @click="activeOperation = 'camera'"
          >
            Allocate camera
          </button>

          <RouterLink v-if="!isLoggedIn" class="primary-btn dashboard-action" to="/login">
            Login
          </RouterLink>
        </div>
      </header>

      <p v-if="error" class="dashboard-warning">
        {{ error }}
      </p>

      <p v-if="notice" class="dashboard-success">
        {{ notice }}
      </p>

      <div v-if="loading" class="dashboard-loading">
        Loading parking lots...
      </div>

      <template v-else>
        <section class="stats-grid lots-stats">
          <article class="stat-card highlight-card">
            <span>Parking lots</span>
            <strong>{{ totalLots }}</strong>
            <p>Configured locations</p>
          </article>

          <article class="stat-card">
            <span>Allocated cameras</span>
            <strong>{{ totalCameras }}</strong>
            <p>Feeds attached to lots</p>
          </article>

          <article class="stat-card">
            <span>Panoramic feeds</span>
            <strong>{{ panoramicCameras }}</strong>
            <p>Required occupancy cameras</p>
          </article>
        </section>

        <section class="spaces-layout">
          <article class="panel large-panel">
            <div class="panel-header">
              <div>
                <h2>Camera allocation table</h2>
                <p>Each parking lot must have at least one panoramic live feed.</p>
              </div>
            </div>

            <div v-if="lots.length === 0" class="empty-state">
              No parking lots configured yet.
            </div>

            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Parking lot</th>
                    <th>Address</th>
                    <th>Spots</th>
                    <th>Camera</th>
                    <th>Type</th>
                    <th>Feed</th>
                  </tr>
                </thead>

                <tbody>
                  <template v-for="lot in lots" :key="lot.id">
                    <template v-for="camera in lot.cameras" :key="camera.id">
                      <tr>
                        <td>
                          <strong>{{ lot.name }}</strong>
                        </td>
                        <td>{{ lot.address }}</td>
                        <td>{{ lot.total_spots }}</td>
                        <td>{{ camera.name }}</td>
                        <td>
                          <span class="badge" :class="camera.camera_type === 'panoramic' ? 'success' : 'warning'">
                            {{ cameraTypeLabel(camera.camera_type) }}
                          </span>
                        </td>
                        <td>
                          <button class="link-btn feed-preview-btn" type="button" @click="toggleFeedPreview(camera.id)">
                            {{ expandedCameraId === camera.id ? 'Hide feed' : 'Preview feed' }}
                          </button>
                        </td>
                      </tr>

                      <tr v-if="expandedCameraId === camera.id" class="feed-preview-row">
                        <td colspan="6">
                          <CameraFeedWrapper
                            :camera-id="camera.id"
                            :camera-name="`${lot.name} - ${camera.name}`"
                            :camera-type="camera.camera_type"
                            :stream-url="camera.stream_url"
                          />
                        </td>
                      </tr>
                    </template>
                  </template>
                </tbody>
              </table>
            </div>
          </article>

          <article v-if="!isLoggedIn" class="panel create-space-panel">
            <div class="panel-header">
              <div>
                <h2>CRUD operations</h2>
                <p>Login with an administrator account to create parking lots and allocate cameras.</p>
              </div>
            </div>

            <RouterLink class="primary-btn" to="/login">
              Login
            </RouterLink>
          </article>

          <article v-else-if="!isAdmin" class="panel create-space-panel">
            <div class="panel-header">
              <div>
                <h2>CRUD operations</h2>
                <p>Your account can view camera allocations. Administrator access is required to create them.</p>
              </div>
            </div>
          </article>

          <article v-else class="panel create-space-panel">
            <div class="operation-tabs">
              <button
                class="operation-tab"
                :class="{ active: activeOperation === 'lot' }"
                type="button"
                @click="activeOperation = 'lot'"
              >
                Create parking lot
              </button>

              <button
                class="operation-tab"
                :class="{ active: activeOperation === 'camera' }"
                type="button"
                @click="activeOperation = 'camera'"
              >
                Allocate camera
              </button>
            </div>

            <div class="panel-header">
              <div>
                <h2>{{ activeOperation === 'lot' ? 'Create parking lot' : 'Allocate camera' }}</h2>
                <p>
                  {{
                    activeOperation === 'lot'
                      ? 'Add the required panoramic feed and optional cameras.'
                      : 'Attach another panoramic, number plate, or thermal camera to an existing lot.'
                  }}
                </p>
              </div>
            </div>

            <form v-if="activeOperation === 'lot'" class="space-form" @submit.prevent="createLot">
              <div class="field">
                <label for="lotName">Parking lot name</label>
                <input id="lotName" v-model="lotForm.name" type="text" placeholder="Central Garage" required />
              </div>

              <div class="field">
                <label for="lotAddress">Address</label>
                <input id="lotAddress" v-model="lotForm.address" type="text" placeholder="21 Main Street" required />
              </div>

              <div class="field">
                <label for="lotSpots">Total spots</label>
                <input id="lotSpots" v-model="lotForm.total_spots" type="number" min="0" required />
              </div>

              <div class="field">
                <label for="panoramicName">Panoramic camera name</label>
                <input id="panoramicName" v-model="lotForm.panoramic_name" type="text" required />
              </div>

              <div class="field">
                <label for="panoramicUrl">Panoramic live feed URL</label>
                <input id="panoramicUrl" v-model="lotForm.panoramic_url" type="url" placeholder="https://example.com/live" required />
              </div>

              <div class="field">
                <label for="plateUrl">Number plate camera URL</label>
                <input id="plateUrl" v-model="lotForm.number_plate_url" type="url" placeholder="Optional entrance feed" />
              </div>

              <div class="field">
                <label for="thermalUrl">Thermal camera URL</label>
                <input id="thermalUrl" v-model="lotForm.thermal_url" type="url" placeholder="Optional EV thermal feed" />
              </div>

              <button class="primary-btn" type="submit" :disabled="saving">
                {{ saving ? 'Creating...' : 'Create lot' }}
              </button>
            </form>

            <form v-else class="space-form" @submit.prevent="createCamera">
              <div class="field">
                <label for="cameraLot">Parking lot</label>
                <select id="cameraLot" v-model="cameraForm.parking_lot_id" required>
                  <option disabled value="">Select parking lot</option>
                  <option v-for="lot in lots" :key="lot.id" :value="lot.id">
                    {{ lot.name }}
                  </option>
                </select>
              </div>

              <div class="field">
                <label for="cameraName">Camera name</label>
                <input id="cameraName" v-model="cameraForm.name" type="text" placeholder="Entrance camera" required />
              </div>

              <div class="field">
                <label for="cameraType">Camera type</label>
                <select id="cameraType" v-model="cameraForm.camera_type" required>
                  <option value="panoramic">Panoramic</option>
                  <option value="number_plate">Number plate</option>
                  <option value="thermal">Thermal</option>
                </select>
              </div>

              <div class="field">
                <label for="cameraUrl">Camera feed URL</label>
                <input id="cameraUrl" v-model="cameraForm.stream_url" type="url" placeholder="https://example.com/live" required />
              </div>

              <button class="primary-btn" type="submit" :disabled="savingCamera || lots.length === 0">
                {{ savingCamera ? 'Allocating...' : 'Create camera' }}
              </button>
            </form>
          </article>
        </section>
      </template>
    </main>
  </section>
</template>
