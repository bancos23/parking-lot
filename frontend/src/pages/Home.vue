<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const loading = ref(true)
const error = ref('')
const isLoggedIn = ref(false)
const showLogoutNotice = ref(false)

const stats = ref({
  totalSpots: 128,
  occupiedSpots: 110,
  availableSpots: 18,
  todayRevenue: 1240,
  activeVehicles: 110,
  pendingPayments: 7,
})

const recentVehicles = ref([
  {
    plate: 'B 123 ABC',
    spot: 'A-14',
    entryTime: '09:24',
    status: 'Parked',
    payment: 'Paid',
  },
  {
    plate: 'CJ 88 KLM',
    spot: 'B-07',
    entryTime: '10:12',
    status: 'Parked',
    payment: 'Pending',
  },
  {
    plate: 'TM 45 RST',
    spot: 'C-22',
    entryTime: '11:03',
    status: 'Parked',
    payment: 'Paid',
  },
  {
    plate: 'BV 19 ZYX',
    spot: 'D-02',
    entryTime: '11:41',
    status: 'Parked',
    payment: 'Pending',
  },
])

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
      if (res.status === 401) {
        isLoggedIn.value = false
        router.push('/login')
        return
      }
      throw new Error('Dashboard request failed')
    }

    const data = await res.json()

    stats.value = data.stats || stats.value
    recentVehicles.value = data.recentVehicles || recentVehicles.value
    parkingZones.value = data.parkingZones || parkingZones.value
  } catch (e) {
    error.value = 'Using demo dashboard data. Could not connect to server.'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  isLoggedIn.value = true
  loadDashboard()
})
</script>

<template>
  <section class="dashboard-page">
    <div v-if="showLogoutNotice" class="logout-notice" role="status" aria-live="polite">
      <strong>You have been logged out</strong>
      <span>Redirecting to login...</span>
    </div>

    <aside class="dashboard-sidebar">
      <div class="logo">
        <div class="logo-icon">P</div>
        <span>ParkFlow</span>
      </div>

      <nav class="sidebar-nav">
        <RouterLink class="nav-link active" to="/">
          Dashboard
        </RouterLink>

        <RouterLink class="nav-link" to="/vehicles">
          Vehicles
        </RouterLink>

        <RouterLink class="nav-link" to="/spaces">
          Parking spaces
        </RouterLink>

        <RouterLink class="nav-link" to="/payments">
          Payments
        </RouterLink>

        <RouterLink class="nav-link" to="/reports">
          Reports
        </RouterLink>
      </nav>

      <button v-if="isLoggedIn" class="logout-btn" type="button" @click="logout">
        Logout
      </button>
    </aside>

    <main class="dashboard-main">
      <header class="dashboard-header">
        <div>
          <p class="eyebrow">Parking lot overview</p>
          <h1>Dashboard</h1>
          <span>Monitor occupancy, vehicles, and payments in real time.</span>
        </div>

        <button class="primary-btn dashboard-action" type="button">
          Add vehicle
        </button>
      </header>

      <p v-if="error" class="dashboard-warning">
        {{ error }}
      </p>

      <div v-if="loading" class="dashboard-loading">
        Loading dashboard...
      </div>

      <template v-else>
        <section class="stats-grid">
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
            <p>Ready for incoming vehicles</p>
          </article>

          <article class="stat-card">
            <span>Today revenue</span>
            <strong>${{ stats.todayRevenue }}</strong>
            <p>Payments collected today</p>
          </article>

          <article class="stat-card">
            <span>Pending payments</span>
            <strong>{{ stats.pendingPayments }}</strong>
            <p>Vehicles requiring payment</p>
          </article>
        </section>

        <section class="dashboard-grid">
          <article class="panel large-panel">
            <div class="panel-header">
              <div>
                <h2>Recent vehicles</h2>
                <p>Latest vehicles currently tracked by ParkFlow.</p>
              </div>

              <RouterLink class="link-btn" to="/vehicles">
                View all
              </RouterLink>
            </div>

            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Plate</th>
                    <th>Spot</th>
                    <th>Entry time</th>
                    <th>Status</th>
                    <th>Payment</th>
                  </tr>
                </thead>

                <tbody>
                  <tr v-for="vehicle in recentVehicles" :key="vehicle.plate">
                    <td>
                      <strong>{{ vehicle.plate }}</strong>
                    </td>
                    <td>{{ vehicle.spot }}</td>
                    <td>{{ vehicle.entryTime }}</td>
                    <td>
                      <span class="badge success">
                        {{ vehicle.status }}
                      </span>
                    </td>
                    <td>
                      <span
                        class="badge"
                        :class="vehicle.payment === 'Paid' ? 'success' : 'warning'"
                      >
                        {{ vehicle.payment }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>

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
