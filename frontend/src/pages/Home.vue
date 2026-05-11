<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import DashboardSidebar from '../components/DashboardSidebar.vue'

const router = useRouter()

const loading = ref(true)
const error = ref('')
const isLoggedIn = ref(false)
const showLogoutNotice = ref(false)

const stats = ref({
  totalSpots: 128,
  occupiedSpots: 110,
  availableSpots: 18,
})

const parkingZones = ref([
  {
    name: 'Zone A',
    total: 32,
    occupied: 28,
  },
  {
    name: 'Zone B',
    total: 40,
    occupied: 35,
  },
  {
    name: 'Zone C',
    total: 36,
    occupied: 29,
  },
  {
    name: 'Zone D',
    total: 20,
    occupied: 18,
  },
])

const occupancyPercent = computed(() => {
  return Math.round((stats.value.occupiedSpots / stats.value.totalSpots) * 100)
})

const totalZones = computed(() => parkingZones.value.length)

async function logout() {
  await fetch('/api/auth/logout', {
    method: 'POST',
    credentials: 'include',
  }).catch(() => {})

  isLoggedIn.value = false
  showLogoutNotice.value = true

  window.setTimeout(() => {
    router.push('/login')
  }, 2200)
}

async function loadDashboard() {
  loading.value = true
  error.value = ''

  try {
    const res = await fetch('/api/dashboard', {
      credentials: 'include',
    })

    if (!res.ok) {
      throw new Error('Dashboard request failed')
    }

    const data = await res.json()

    isLoggedIn.value = Boolean(data.account)
    stats.value = data.stats || stats.value
    parkingZones.value = data.parkingZones || parkingZones.value
  } catch (e) {
    error.value = 'Using demo dashboard data. Could not connect to server.'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadDashboard()
})
</script>

<template>
  <section class="dashboard-page">
    <div v-if="showLogoutNotice" class="logout-notice" role="status" aria-live="polite">
      <strong>You have been logged out</strong>
      <span>Redirecting to login...</span>
    </div>

    <DashboardSidebar active-page="dashboard" :is-logged-in="isLoggedIn" @logout="logout" />

    <main class="dashboard-main">
      <header class="dashboard-header">
        <div>
          <p class="eyebrow">Parking lot overview</p>
          <h1>Dashboard</h1>
          <span>Monitor occupancy and parking zones in real time.</span>
        </div>

        <div v-if="!isLoggedIn" class="header-actions">
          <RouterLink class="primary-btn dashboard-action" to="/login">
            Login
          </RouterLink>
        </div>
      </header>

      <p v-if="error" class="dashboard-warning">
        {{ error }}
      </p>

      <div v-if="loading" class="dashboard-loading">
        Loading dashboard...
      </div>

      <template v-else>
        <section class="stats-grid dashboard-stats">
          <article class="stat-card highlight-card">
            <span>Occupancy</span>
            <strong>{{ occupancyPercent }}%</strong>
            <p>{{ stats.occupiedSpots }} of {{ stats.totalSpots }} spots occupied</p>

            <div class="progress-track">
              <div
                class="progress-fill"
                :style="{ width: `${occupancyPercent}%` }"
              ></div>
            </div>
          </article>

          <article class="stat-card">
            <span>Available spots</span>
            <strong>{{ stats.availableSpots }}</strong>
            <p>Ready for incoming traffic</p>
          </article>

          <article class="stat-card">
            <span>Parking zones</span>
            <strong>{{ totalZones }}</strong>
            <p>Active monitored areas</p>
          </article>
        </section>

        <section class="dashboard-grid single-panel">
          <article class="panel">
            <div class="panel-header">
              <div>
                <h2>Parking zones</h2>
                <p>Occupancy by zone.</p>
              </div>
            </div>

            <div class="zone-list">
              <div
                v-for="zone in parkingZones"
                :key="zone.name"
                class="zone-item"
              >
                <div class="zone-info">
                  <strong>{{ zone.name }}</strong>
                  <span>{{ zone.occupied }} / {{ zone.total }} occupied</span>
                </div>

                <div class="progress-track small">
                  <div
                    class="progress-fill"
                    :style="{ width: `${Math.round((zone.occupied / zone.total) * 100)}%` }"
                  ></div>
                </div>
              </div>
            </div>
          </article>
        </section>
      </template>
    </main>
  </section>
</template>
