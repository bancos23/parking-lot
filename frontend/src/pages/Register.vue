<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const firstName = ref('')
const lastName = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const error = ref('')
const loading = ref(false)

async function handleRegister() {
  error.value = ''

  if (password.value !== confirmPassword.value) {
    error.value = 'Passwords do not match'
    return
  }

  loading.value = true

  try {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        first_name: firstName.value,
        last_name: lastName.value,
        email: email.value,
        password: password.value,
      }),
    })

    const data = await res.json().catch(() => ({}))

    if (!res.ok) {
      error.value = data.detail || data.message || 'Registration failed'
      return
    }

    router.push('/login')
  } catch (e) {
    error.value = 'Could not connect to server'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="auth-page register-page">
    <aside class="brand-panel">
      <div class="logo">
        <div class="logo-icon">P</div>
        <span>ParkFlow</span>
      </div>

      <div class="brand-copy">
        <h1>Start managing parking smarter.</h1>
        <p>
          Create your ParkFlow account and get access to occupancy tracking,
          camera allocation, parking lot setup, and space management.
        </p>
      </div>

      <div class="mini-stats">
        <div class="mini-card">
          <strong>128</strong>
          <span>Total spots</span>
        </div>

        <div class="mini-card">
          <strong>86%</strong>
          <span>Today occupancy</span>
        </div>

        <div class="mini-card">
          <strong>24/7</strong>
          <span>Live monitoring</span>
        </div>
      </div>
    </aside>

    <main class="auth-content">
      <form class="auth-card register-card" @submit.prevent="handleRegister">
        <h2>Create account</h2>
        <p>Register to start managing your parking lot operations.</p>

        <div class="field">
          <label for="firstName">First name</label>
          <input
            id="firstName"
            v-model="firstName"
            type="text"
            placeholder="Admin"
            required
          />
        </div>

        <div class="field">
          <label for="lastName">Last name</label>
          <input
            id="lastName"
            v-model="lastName"
            type="text"
            placeholder="User"
            required
          />
        </div>

        <div class="field">
          <label for="email">Email address</label>
          <input
            id="email"
            v-model="email"
            type="email"
            placeholder="admin@parkflow.com"
            required
          />
        </div>

        <div class="field">
          <label for="password">Password</label>
          <input
            id="password"
            v-model="password"
            type="password"
            placeholder="Create a password"
            required
          />
        </div>

        <div class="field">
          <label for="confirmPassword">Confirm password</label>
          <input
            id="confirmPassword"
            v-model="confirmPassword"
            type="password"
            placeholder="Repeat your password"
            required
          />
        </div>

        <p v-if="error" class="auth-error">
          {{ error }}
        </p>

        <button class="primary-btn" type="submit" :disabled="loading">
          {{ loading ? 'Creating account...' : 'Create account' }}
        </button>

        <div class="auth-switch">
          Already have an account?
          <RouterLink class="link-btn" to="/login">
            Login
          </RouterLink>
        </div>
      </form>
    </main>
  </section>
</template>
