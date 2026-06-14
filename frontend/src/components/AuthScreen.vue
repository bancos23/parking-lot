<script setup>
import { computed, ref } from 'vue'
import LangSwitcher from '@frontend/components/LangSwitcher.vue'
import { useT } from '@frontend/composables/i18n'

const emit = defineEmits(['login'])
const props = defineProps({
  busy: { type: Boolean, default: false },
  serverError: { type: String, default: '' },
})
const { t } = useT()

const mode = ref('login')
const showPass = ref(false)
const email = ref('')
const password = ref('')
const name = ref('')
const phone = ref('')
const role = ref('guest')
const orgName = ref('')
const agree = ref(false)
const remember = ref(true)
const error = ref('')

const passStrength = computed(() => {
  if (!password.value) return 0
  let score = 0
  if (password.value.length >= 8) score++
  if (password.value.length >= 12) score++
  if (/[A-Z]/.test(password.value) && /[a-z]/.test(password.value)) score++
  if (/\d/.test(password.value)) score++
  if (/[^A-Za-z0-9]/.test(password.value)) score++
  return Math.min(score, 4)
})

function switchMode(next) {
  mode.value = next
  error.value = ''
}

function submit() {
  error.value = ''
  if (props.busy) return

  if (mode.value === 'login') {
    if (!email.value || !password.value) {
      error.value = t('auth.err.empty')
      return
    }
    emit('login', {
      action: 'login',
      email: email.value,
      password: password.value,
    })
    return
  }

  if (!email.value || !password.value || !name.value) {
    error.value = t('auth.err.empty_reg')
    return
  }
  if (password.value.length < 8) {
    error.value = t('auth.err.password_short')
    return
  }
  if (!agree.value) {
    error.value = t('auth.err.agree')
    return
  }
  if (role.value === 'private' && !orgName.value.trim()) {
    error.value = t('auth.err.org_required')
    return
  }
  emit('login', {
    action: 'register',
    email: email.value,
    password: password.value,
    name: name.value,
    phone: phone.value || null,
    role: role.value,
    organisationName: role.value === 'private' ? orgName.value.trim() : null,
  })
}
</script>

<template>
  <div class="auth-screen">
    <div class="auth-lang">
      <LangSwitcher />
    </div>

    <div class="auth-side">
      <div class="auth-brand">
        <div class="brand-mark big">P</div>
        <div>
          <div class="auth-brand-name">Parking App</div>
          <div class="auth-brand-sub">{{ t('brand.sub') }}</div>
        </div>
      </div>

      <div class="auth-hero">
        <h1>{{ t('auth.hero.title.1') }}<br><span>{{ t('auth.hero.title.2') }}</span></h1>
        <p>{{ t('auth.hero.sub') }}</p>

        <div class="auth-features">
          <div class="auth-feat">
            <div class="auth-feat-icon" style="background:var(--bm-blue)">⌖</div>
            <div>
              <div class="auth-feat-title">{{ t('auth.feat.map.title') }}</div>
              <div class="auth-feat-sub">{{ t('auth.feat.map.sub') }}</div>
            </div>
          </div>
          <div class="auth-feat">
            <div class="auth-feat-icon" style="background:#16a34a">⚡</div>
            <div>
              <div class="auth-feat-title">{{ t('auth.feat.ev.title') }}</div>
              <div class="auth-feat-sub">{{ t('auth.feat.ev.sub') }}</div>
            </div>
          </div>
          <div class="auth-feat">
            <div class="auth-feat-icon" style="background:var(--bm-red)">↗</div>
            <div>
              <div class="auth-feat-title">{{ t('auth.feat.stats.title') }}</div>
              <div class="auth-feat-sub">{{ t('auth.feat.stats.sub') }}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="auth-foot">
        <span>© 2026 Parking App</span><span>·</span>
        <RouterLink :to="{ name: 'terms' }">{{ t('auth.foot.terms') }}</RouterLink>
        <RouterLink :to="{ name: 'privacy' }">{{ t('auth.foot.privacy') }}</RouterLink>
        <RouterLink :to="{ name: 'support' }">{{ t('auth.foot.support') }}</RouterLink>
      </div>

      <div class="auth-deco" aria-hidden="true">
        <div class="deco-circle deco-1"></div>
        <div class="deco-circle deco-2"></div>
        <div class="deco-grid"></div>
      </div>
    </div>

    <div class="auth-form-wrap">
      <div class="auth-card">
        <div class="auth-tabs">
          <button type="button" :class="{ active: mode === 'login' }" @click="switchMode('login')">{{
            t('auth.tab.login') }}</button>
          <button type="button" :class="{ active: mode === 'register' }" @click="switchMode('register')">{{
            t('auth.tab.register') }}</button>
          <div class="auth-tabs-ind" :class="mode"></div>
        </div>

        <div class="auth-card-body">
          <h2>{{ mode === 'login' ? t('auth.login.title') : t('auth.register.title') }}</h2>
          <p class="auth-card-sub">{{ mode === 'login' ? t('auth.login.sub') : t('auth.register.sub') }}</p>

          <form @submit.prevent="submit">
            <div v-if="mode === 'register'" class="field">
              <label>{{ t('auth.name') }}</label>
              <div class="input-wrap"><span class="input-ic">👤</span><input v-model="name" type="text"
                  :placeholder="t('auth.name.placeholder')" autofocus></div>
            </div>

            <div class="field">
              <label>{{ t('auth.email') }}</label>
              <div class="input-wrap"><span class="input-ic">✉</span><input v-model="email" type="email"
                  :placeholder="t('auth.email.placeholder')" :autofocus="mode === 'login'"></div>
            </div>

            <div class="field">
              <div class="label-row">
                <label>{{ t('auth.password') }}</label>
                <a v-if="mode === 'login'" class="auth-link" href="#" @click.prevent>{{ t('auth.forgot') }}</a>
              </div>
              <div class="input-wrap">
                <span class="input-ic">🔒</span>
                <input v-model="password" :type="showPass ? 'text' : 'password'" placeholder="••••••••">
                <button type="button" class="input-trail" tabindex="-1" @click="showPass = !showPass">{{ showPass ? '🙈'
                  : '👁' }}</button>
              </div>
              <div v-if="mode === 'register' && password" class="pass-strength">
                <div class="pass-bars">
                  <span v-for="i in [0, 1, 2, 3]" :key="i" class="pb"
                    :class="i < passStrength ? `s${passStrength}` : ''"></span>
                </div>
                <span class="pass-label">{{ [t('auth.pass.weak'), t('auth.pass.weak'), t('auth.pass.medium'),
                t('auth.pass.good'), t('auth.pass.strong')][passStrength] }}</span>
              </div>
            </div>

            <template v-if="mode === 'register'">
              <div class="field">
                <label>{{ t('auth.phone') }} <span class="optional">{{ t('auth.optional') }}</span></label>
                <div class="input-wrap"><span class="input-ic">☎</span><input v-model="phone" type="tel"
                    placeholder="+40 7XX XXX XXX"></div>
              </div>

              <div class="field">
                <label>{{ t('auth.account_type') }}</label>
                <div class="role-cards">
                  <label class="role-card" :class="{ active: role === 'guest' }">
                    <input v-model="role" type="radio" name="role" value="guest">
                    <div class="role-card-ic">👤</div>
                    <div class="role-card-text">
                      <div class="role-card-title">{{ t('auth.role.driver') }}</div>
                      <div class="role-card-sub">{{ t('auth.role.driver.sub') }}</div>
                    </div>
                  </label>
                  <label class="role-card" :class="{ active: role === 'private' }">
                    <input v-model="role" type="radio" name="role" value="private">
                    <div class="role-card-ic">▦</div>
                    <div class="role-card-text">
                      <div class="role-card-title">{{ t('auth.role.admin') }}</div>
                      <div class="role-card-sub">{{ t('auth.role.admin.sub') }}</div>
                    </div>
                  </label>
                </div>
              </div>

              <div v-if="role === 'private'" class="field">
                <label>{{ t('auth.org') }}</label>
                <div class="input-wrap"><span class="input-ic">🏢</span><input v-model="orgName" type="text"
                    :placeholder="t('auth.org.placeholder')"></div>
              </div>

              <label class="checkbox-row">
                <input v-model="agree" type="checkbox">
                <span>{{ t('auth.agree') }} <RouterLink class="auth-link" :to="{ name: 'terms' }">{{ t('auth.terms') }}
                  </RouterLink> {{
                    t('auth.and') }} <RouterLink class="auth-link" :to="{ name: 'privacy' }">{{ t('auth.privacy') }}
                  </RouterLink>.</span>
              </label>
            </template>

            <label v-if="mode === 'login'" class="checkbox-row">
              <input v-model="remember" type="checkbox">
              <span>{{ t('auth.remember') }}</span>
            </label>

            <div v-if="error || props.serverError" class="auth-error">⚠ {{ error || props.serverError }}</div>

            <button type="submit" class="btn btn-primary auth-submit" :disabled="props.busy">
              {{ mode === 'login' ? t('auth.submit.login') : t('auth.submit.register') }}
            </button>
          </form>

          <div class="auth-divider"><span>{{ t('auth.or') }}</span></div>

          <div class="auth-oauth">
            <button type="button" class="btn oauth-btn"
              :disabled="props.busy"
              @click="emit('login', { action: 'guest', email: 'invitat@local', name: 'Vizitator', role: 'guest' })">{{
                t('auth.guest') }}</button>
          </div>

          <div class="auth-switch">
            <template v-if="mode === 'login'">
              {{ t('auth.switch.to_register') }} <a class="auth-link" href="#"
                @click.prevent="switchMode('register')">{{ t('auth.switch.register_link') }}</a>
            </template>
            <template v-else>
              {{ t('auth.switch.to_login') }} <a class="auth-link" href="#" @click.prevent="switchMode('login')">{{
                t('auth.switch.login_link') }}</a>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
