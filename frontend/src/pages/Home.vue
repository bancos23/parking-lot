<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import LangSwitcher from '../components/LangSwitcher.vue'
import MapTab from '../components/MapTab.vue'
import StatsTab from '../components/StatsTab.vue'
import LotsTab from '../components/LotsTab.vue'
import { useT } from '../composables/i18n'
import { SESSION_EXPIRED_EVENT, useAuth } from '../stores/auth'

const router = useRouter()
const { t } = useT()
const { user, role, setRole, logout: logoutUser } = useAuth()

const tab = ref('map')
const tweaksOpen = ref(false)
const menuOpen = ref(false)
const tweaks = reactive(loadTweaks())

const tabs = computed(() => [
    { v: 'map', l: t('tab.map'), icon: '⌖' },
    { v: 'stats', l: t('tab.stats'), icon: '↗' },
    { v: 'lots', l: t('tab.lots'), icon: '☷' },
])

function loadTweaks() {
    try {
        return {
            theme: 'light',
            accent: 'red-blue',
            density: 'comfortable',
            ...JSON.parse(localStorage.getItem('tweaks') || '{}'),
        }
    } catch {
        return {
            theme: 'light',
            accent: 'red-blue',
            density: 'comfortable',
        }
    }
}

function persistTweaks() {
    try {
        localStorage.setItem('tweaks', JSON.stringify(tweaks))
    } catch { }
}

function applyAccent() {
    const palettes = {
        'red-blue': {
            red: '#c8102e',
            redDark: '#a30d25',
            blue: '#003da5',
            blueDark: '#002d7a',
        },
        sunset: {
            red: '#e63946',
            redDark: '#c0202f',
            blue: '#1d3557',
            blueDark: '#12233d',
        },
        mono: {
            red: '#1c1f2a',
            redDark: '#0e1018',
            blue: '#5b6479',
            blueDark: '#444a5a',
        },
        electric: {
            red: '#ff2d55',
            redDark: '#d8204a',
            blue: '#0a84ff',
            blueDark: '#0a6cd6',
        },
    }

    const p = palettes[tweaks.accent] || palettes['red-blue']
    const root = document.documentElement

    root.style.setProperty('--bm-red', p.red)
    root.style.setProperty('--bm-red-dark', p.redDark)
    root.style.setProperty('--bm-blue', p.blue)
    root.style.setProperty('--bm-blue-dark', p.blueDark)
}

async function logout() {
    await logoutUser({ remote: true })
    menuOpen.value = false
    router.push('/login')
}

function handleSessionExpired() {
    menuOpen.value = false
    router.push('/login')
}

function closeTweaks() {
    tweaksOpen.value = false
    window.parent?.postMessage?.({ type: '__edit_mode_dismissed' }, '*')
}

function messageHandler(e) {
    if (e.data?.type === '__activate_edit_mode') tweaksOpen.value = true
    if (e.data?.type === '__deactivate_edit_mode') tweaksOpen.value = false
}

watch(
    () => tweaks.theme,
    () => {
        document.documentElement.dataset.theme = tweaks.theme
        persistTweaks()
    },
    { immediate: true },
)

watch(
    () => tweaks.accent,
    () => {
        applyAccent()
        persistTweaks()
    },
    { immediate: true },
)

onMounted(() => {
    window.addEventListener('message', messageHandler)
    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired)
    window.parent?.postMessage?.({ type: '__edit_mode_available' }, '*')
})

onBeforeUnmount(() => {
    window.removeEventListener('message', messageHandler)
    window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired)
})
</script>

<template>
    <div class="app">
        <header class="header">
            <div class="brand">
                <div class="brand-mark">P</div>
                <div>
                    Parking App
                    <span class="brand-sub"> · {{ t('brand.sub') }}</span>
                </div>
            </div>

            <div class="tabs desktop-only" role="tablist">
                <button v-for="item in tabs" :key="item.v" class="tab" :class="{ active: tab === item.v }" type="button"
                    @click="tab = item.v">
                    <span>{{ item.icon }}</span>
                    {{ item.l }}
                </button>
            </div>

            <div class="header-spacer"></div>

            <div class="desktop-only">
                <LangSwitcher />
            </div>

            <div class="role-switch desktop-only" title="Switch role (demo)">
                <button type="button" :class="{ active: role === 'municipal' }" @click="setRole('municipal')">
                    {{ t('role.municipal') }}
                </button>
                <button type="button" :class="{ active: role === 'private' }" @click="setRole('private')">
                    {{ t('role.private') }}
                </button>
                <button type="button" :class="{ active: role === 'guest' }" @click="setRole('guest')">
                    {{ t('role.guest') }}
                </button>
            </div>

            <div class="user-chip" :title="user?.email" @click="menuOpen = !menuOpen">
                <div class="avatar">
                    {{ (user?.name || user?.email || '').slice(0, 2).toUpperCase() }}
                </div>
                <span class="name desktop-only">
                    {{ user?.name || user?.email?.split('@')[0] }}
                </span>
                <button class="icon-btn desktop-only logout-mini" type="button" title="Ieșire" @click.stop="logout">
                    ↪
                </button>
            </div>

            <template v-if="menuOpen">
                <div class="mobile-menu-backdrop" @click="menuOpen = false"></div>

                <div class="mobile-menu">
                    <div class="mm-section">
                        <div class="mm-user">
                            <div class="avatar big">
                                {{ (user?.name || user?.email || '').slice(0, 2).toUpperCase() }}
                            </div>
                            <div>
                                <div class="mm-name">{{ user?.name || user?.email?.split('@')[0] }}</div>
                                <div class="mm-email">{{ user?.email }}</div>
                            </div>
                        </div>
                    </div>

                    <div class="mm-section">
                        <div class="mm-label">{{ t('lang.label') }}</div>
                        <LangSwitcher />
                    </div>

                    <div class="mm-section">
                        <div class="mm-label">{{ t('role.title') }}</div>

                        <button v-for="item in [
                            { v: 'municipal', l: t('role.municipal.full'), sub: t('role.municipal.sub') },
                            { v: 'private', l: t('role.private.full'), sub: t('role.private.sub') },
                            { v: 'guest', l: t('role.guest.full'), sub: t('role.guest.sub') },
                        ]" :key="item.v" class="mm-item" :class="{ active: role === item.v }" type="button"
                            @click="setRole(item.v); menuOpen = false">
                            <div>
                                <div class="mm-item-l">{{ item.l }}</div>
                                <div class="mm-item-s">{{ item.sub }}</div>
                            </div>
                            <span v-if="role === item.v">✓</span>
                        </button>
                    </div>

                    <div class="mm-section">
                        <button class="mm-item danger" type="button" @click="logout">
                            <div class="mm-item-l">{{ t('menu.logout') }}</div>
                            <span>↪</span>
                        </button>
                    </div>
                </div>
            </template>
        </header>

        <nav class="mobile-tabs">
            <button v-for="item in tabs" :key="item.v" :class="{ active: tab === item.v }" type="button"
                @click="tab = item.v">
                <span>{{ item.icon }}</span>
                <span>{{ item.l }}</span>
            </button>
        </nav>

        <main class="tab-content">
            <MapTab v-if="tab === 'map'" :role="role" />
            <StatsTab v-if="tab === 'stats'" :role="role" />
            <LotsTab v-if="tab === 'lots'" :role="role" />
        </main>

        <div v-if="tweaksOpen" class="tweaks-panel-host">
            <div class="tweaks-panel">
                <div class="tweaks-head">
                    <h3>{{ t('tweaks.title') }}</h3>
                    <button class="icon-btn" type="button" @click="closeTweaks">✕</button>
                </div>

                <div class="tweaks-body">
                    <section>
                        <h4>{{ t('tweaks.section.appearance') }}</h4>

                        <label>{{ t('tweaks.theme') }}</label>
                        <div class="tweak-options">
                            <button class="btn" :class="{ 'btn-primary': tweaks.theme === 'light' }" type="button"
                                @click="tweaks.theme = 'light'">
                                {{ t('tweaks.theme.light') }}
                            </button>
                            <button class="btn" :class="{ 'btn-primary': tweaks.theme === 'dark' }" type="button"
                                @click="tweaks.theme = 'dark'">
                                {{ t('tweaks.theme.dark') }}
                            </button>
                        </div>

                        <label>{{ t('tweaks.accent') }}</label>
                        <select v-model="tweaks.accent">
                            <option value="red-blue">{{ t('tweaks.accent.baia_mare') }}</option>
                            <option value="sunset">{{ t('tweaks.accent.sunset') }}</option>
                            <option value="mono">{{ t('tweaks.accent.mono') }}</option>
                            <option value="electric">{{ t('tweaks.accent.electric') }}</option>
                        </select>
                    </section>
                </div>
            </div>
        </div>
    </div>
</template>
