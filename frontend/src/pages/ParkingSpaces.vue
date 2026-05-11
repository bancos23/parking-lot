<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import DashboardSidebar from '../components/DashboardSidebar.vue'

const router = useRouter()

const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const account = ref(null)
const spaces = ref([])

const form = ref({
  code: '',
  zone: '',
  level: 'Ground',
  status: 'available',
})

const isLoggedIn = computed(() => Boolean(account.value))
const isAdmin = computed(() => account.value?.role === 'administrator')

const totalSpaces = computed(() => spaces.value.length)
const availableSpaces = computed(() => {
  return spaces.value.filter((space) => space.status === 'available').length
})
const occupiedSpaces = computed(() => {
  return spaces.value.filter((space) => space.status === 'occupied').length
})

function statusLabel(status) {
  return status.replaceAll('_', ' ')
}

async function logout() {
  await fetch('/api/auth/logout', {
    method: 'POST',
    credentials: 'include',
  }).catch(() => {})

  account.value = null
  router.push('/login')
}

async function loadSpaces() {
  loading.value = true
  error.value = ''

  try {
    const res = await fetch('/api/spaces', {
      credentials: 'include',
    })

    if (!res.ok) {
      throw new Error('Spaces request failed')
    }

    const data = await res.json()
    account.value = data.account
    spaces.value = data.spaces || []
  } catch (e) {
    error.value = 'Could not load parking spaces.'
  } finally {
    loading.value = false
  }
}

async function createSpace() {
  saving.value = true
  error.value = ''
  notice.value = ''

  try {
    const res = await fetch('/api/spaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(form.value),
    })

    const data = await res.json().catch(() => ({}))

    if (!res.ok) {
      error.value = data.detail || 'Could not create parking space'
      return
    }

    spaces.value = [...spaces.value, data].sort((a, b) => {
      return `${a.zone}-${a.code}`.localeCompare(`${b.zone}-${b.code}`)
    })
    form.value = {
      code: '',
      zone: '',
      level: 'Ground',
      status: 'available',
    }
    notice.value = 'Parking space created.'
  } catch (e) {
    error.value = 'Could not connect to server.'
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadSpaces()
})
</script>

<template>
  <section class="dashboard-page">
    <DashboardSidebar active-page="spaces" :is-logged-in="isLoggedIn" @logout="logout" />

    <main class="dashboard-main">
      <header class="dashboard-header">
        <div>
          <p class="eyebrow">Parking inventory</p>
          <h1>Parking spaces</h1>
          <span>View all configured spaces and manage availability.</span>
        </div>

        <RouterLink v-if="!isLoggedIn" class="primary-btn dashboard-action" to="/login">
          Login
        </RouterLink>
      </header>

      <p v-if="error" class="dashboard-warning">
        {{ error }}
      </p>

      <p v-if="notice" class="dashboard-success">
        {{ notice }}
      </p>

      <div v-if="loading" class="dashboard-loading">
        Loading parking spaces...
      </div>

      <template v-else>
        <section class="stats-grid spaces-stats">
          <article class="stat-card highlight-card">
            <span>Total spaces</span>
            <strong>{{ totalSpaces }}</strong>
            <p>Configured parking spots</p>
          </article>

          <article class="stat-card">
            <span>Available</span>
            <strong>{{ availableSpaces }}</strong>
            <p>Ready for incoming traffic</p>
          </article>

          <article class="stat-card">
            <span>Occupied</span>
            <strong>{{ occupiedSpaces }}</strong>
            <p>Currently in use</p>
          </article>
        </section>

        <section class="spaces-layout">
          <article class="panel large-panel">
            <div class="panel-header">
              <div>
                <h2>Space list</h2>
                <p>Guests can view spaces. Administrators can add new ones.</p>
              </div>
            </div>

            <div v-if="spaces.length === 0" class="empty-state">
              No parking spaces configured yet.
            </div>

            <div v-else class="space-grid">
              <article v-for="space in spaces" :key="space.id" class="space-tile">
                <div>
                  <strong>{{ space.code }}</strong>
                  <span>{{ space.zone }} · {{ space.level }}</span>
                </div>

                <span class="badge" :class="space.status === 'available' ? 'success' : 'warning'">
                  {{ statusLabel(space.status) }}
                </span>
              </article>
            </div>
          </article>

          <article v-if="isAdmin" class="panel create-space-panel">
            <div class="panel-header">
              <div>
                <h2>Create space</h2>
                <p>Only administrator accounts can add inventory.</p>
              </div>
            </div>

            <form class="space-form" @submit.prevent="createSpace">
              <div class="field">
                <label for="spaceCode">Space code</label>
                <input id="spaceCode" v-model="form.code" type="text" placeholder="A-01" required />
              </div>

              <div class="field">
                <label for="spaceZone">Zone</label>
                <input id="spaceZone" v-model="form.zone" type="text" placeholder="Zone A" required />
              </div>

              <div class="field">
                <label for="spaceLevel">Level</label>
                <input id="spaceLevel" v-model="form.level" type="text" placeholder="Ground" required />
              </div>

              <div class="field">
                <label for="spaceStatus">Status</label>
                <select id="spaceStatus" v-model="form.status">
                  <option value="available">Available</option>
                  <option value="occupied">Occupied</option>
                  <option value="reserved">Reserved</option>
                  <option value="out_of_service">Out of service</option>
                </select>
              </div>

              <button class="primary-btn" type="submit" :disabled="saving">
                {{ saving ? 'Creating...' : 'Create space' }}
              </button>
            </form>
          </article>
        </section>
      </template>
    </main>
  </section>
</template>
