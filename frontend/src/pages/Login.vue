<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const email = ref('')
const password = ref('')
const error = ref('')

async function handleLogin() {
  error.value = ''
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email: email.value, password: password.value }),
    })
    if (!res.ok) {
      const data = await res.json()
      error.value = data.detail || 'Login failed'
      return
    }
    await res.json()
    router.push('/')
  } catch (e) {
    error.value = 'Could not connect to server'
  }
}
</script>

<template>
  <section class="login-page">
    <aside class="brand-panel">
      <div class="logo">
        <div class="logo-icon">P</div>
        <span>ParkFlow</span>
      </div>

      <div class="brand-copy">
        <h1>Smarter parking lot control.</h1>
        <p>
          Monitor occupancy, organize camera feeds,
          and manage parking spaces from one clean dashboard.
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

    <main class="login-content">
      <form class="login-card" @submit.prevent="handleLogin">
        <h2>Welcome back</h2>
        <p>Login to manage your parking lot operations.</p>

        <div class="field">
          <label for="email">Email address</label>
          <input id="email" v-model="email" type="email" placeholder="admin@parkflow.com" required />
        </div>

        <div class="field">
          <label for="password">Password</label>
          <input id="password" v-model="password" type="password" placeholder="Enter your password" required />
        </div>

        <button class="primary-btn" type="submit">
          Login
        </button>

        <div class="auth-switch">
          New to ParkFlow?
          <RouterLink class="link-btn" to="/register">
            Create account
          </RouterLink>
        </div>
      </form>
    </main>
  </section>
</template>

<style scoped>
.login-page {
  width: 100%;
  min-height: 100vh;
  min-height: 100dvh;
  padding: 3vh 2vw;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2vw;
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.13), transparent 34%),
    linear-gradient(135deg, #f8fbff, #eef3fb);
  color: #172033;
  overflow-x: hidden;
}

.brand-panel {
  min-height: 94vh;
  padding: 6vh 4vw;
  border-radius: 2vw;
  background: linear-gradient(145deg, #2563eb, #1e40af);
  color: white;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-shadow: 0 2vh 4vw rgba(15, 23, 42, 0.12);
  position: relative;
  overflow: hidden;
}

.brand-panel::after {
  content: "";
  position: absolute;
  width: 25vw;
  height: 25vw;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.12);
  right: -8vw;
  bottom: -10vh;
}

.logo {
  display: flex;
  align-items: center;
  gap: 1vw;
  font-size: clamp(1.4rem, 1.6vw, 2rem);
  font-weight: 800;
  letter-spacing: -0.04em;
  position: relative;
  z-index: 1;
}

.logo-icon {
  width: 3.4vw;
  height: 3.4vw;
  min-width: 44px;
  min-height: 44px;
  border-radius: 1vw;
  background: white;
  color: #2563eb;
  display: grid;
  place-items: center;
  font-weight: 900;
}

.brand-copy {
  position: relative;
  z-index: 1;
  max-width: 38vw;
}

.brand-copy h1 {
  font-size: clamp(2.6rem, 5vw, 5.6rem);
  line-height: 0.95;
  letter-spacing: -0.07em;
  margin-bottom: 2vh;
}

.brand-copy p {
  font-size: clamp(1rem, 1.1vw, 1.3rem);
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.82);
}

.mini-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1vw;
  position: relative;
  z-index: 1;
}

.mini-card {
  padding: 2vh 1vw;
  border-radius: 1.2vw;
  background: rgba(255, 255, 255, 0.13);
}

.mini-card strong {
  display: block;
  font-size: clamp(1.5rem, 2vw, 2.4rem);
  margin-bottom: 0.5vh;
}

.mini-card span {
  font-size: clamp(0.75rem, 0.85vw, 1rem);
  color: rgba(255, 255, 255, 0.75);
}

.login-content {
  min-height: 94vh;
  display: grid;
  place-items: center;
}

.login-card {
  width: 32vw;
  min-width: 360px;
  padding: 5vh 3vw;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #e5eaf3;
  border-radius: 2vw;
  box-shadow: 0 2vh 4vw rgba(15, 23, 42, 0.08);
}

.login-card h2 {
  font-size: clamp(2rem, 2.6vw, 3.2rem);
  letter-spacing: -0.05em;
  margin-bottom: 1vh;
}

.login-card>p {
  color: #7c8798;
  margin-bottom: 3vh;
  line-height: 1.5;
  font-size: clamp(0.95rem, 1vw, 1.1rem);
}

.field {
  margin-bottom: 2vh;
}

.field label {
  display: block;
  margin-bottom: 0.8vh;
  font-size: clamp(0.8rem, 0.85vw, 1rem);
  font-weight: 700;
  color: #344054;
}

.field input {
  width: 100%;
  padding: 1.8vh 1vw;
  border-radius: 1vw;
  border: 1px solid #e5eaf3;
  background: white;
  color: #172033;
  outline: none;
  transition: 0.2s ease;
}

.field input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 0.3vw rgba(37, 99, 235, 0.12);
}

.primary-btn {
  width: 100%;
  margin-top: 1vh;
  padding: 1.8vh 1vw;
  border: none;
  border-radius: 1vw;
  background: #2563eb;
  color: white;
  font-weight: 800;
  cursor: pointer;
  transition: 0.2s ease;
}

.primary-btn:hover {
  background: #1e40af;
  transform: translateY(-0.2vh);
}

.auth-switch {
  margin-top: 2.5vh;
  text-align: center;
  color: #7c8798;
  font-size: clamp(0.85rem, 0.9vw, 1rem);
}

.link-btn {
  color: #2563eb;
  font-weight: 800;
  text-decoration: none;
}

.link-btn:hover {
  text-decoration: underline;
}

@media (max-width: 1000px) {
  .login-page {
    grid-template-columns: 1fr;
    padding: 16px;
    gap: 16px;
  }

  .brand-panel {
    min-height: auto;
    padding: 32px 24px;
    border-radius: 16px;
  }

  .brand-copy {
    max-width: 100%;
  }

  .brand-copy h1 {
    font-size: 2rem;
  }

  .login-content {
    min-height: auto;
    padding: 0;
  }

  .login-card {
    width: 100%;
    min-width: unset;
    padding: 32px 24px;
    border-radius: 16px;
  }

  .logo {
    gap: 10px;
  }

  .logo-icon {
    width: 40px;
    height: 40px;
    min-width: 40px;
    min-height: 40px;
    border-radius: 10px;
  }

  .mini-stats {
    gap: 8px;
  }

  .mini-card {
    padding: 12px;
    border-radius: 10px;
  }

  .field input {
    padding: 14px 16px;
    border-radius: 10px;
    font-size: 16px;
  }

  .primary-btn {
    padding: 14px 16px;
    border-radius: 10px;
    font-size: 1rem;
  }

  .field input:focus {
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
  }
}

@media (max-width: 500px) {
  .login-page {
    padding: 12px 12px max(28px, calc(env(safe-area-inset-bottom) + 20px));
  }

  .brand-panel {
    padding: 24px 20px;
    border-radius: 14px;
    gap: 16px;
  }

  .brand-panel::after {
    display: none;
  }

  .brand-copy h1 {
    font-size: 1.45rem;
    margin-bottom: 8px;
  }

  .brand-copy p {
    font-size: 0.84rem;
    line-height: 1.45;
  }

  .mini-stats {
    display: none;
  }

  .login-card {
    padding: 18px 16px;
    border-radius: 14px;
    border: none;
    box-shadow: none;
    background: transparent;
  }

  .login-card h2 {
    font-size: 1.45rem;
  }

  .login-card>p {
    margin-bottom: 16px;
    font-size: 0.9rem;
  }

  .field {
    margin-bottom: 14px;
  }

  .field label {
    margin-bottom: 6px;
  }

  .field input {
    padding: 12px 14px;
  }

  .primary-btn {
    margin-top: 4px;
    padding: 12px 14px;
  }

  .auth-switch {
    font-size: 0.9rem;
    margin-top: 16px;
    margin-bottom: env(safe-area-inset-bottom);
  }
}
</style>
