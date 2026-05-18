import { computed, reactive } from 'vue'

export const SESSION_EXPIRED_EVENT = 'parkflow:session-expired'

function loadUser() {
    try {
        const raw = localStorage.getItem('parkingUser')
        return raw ? JSON.parse(raw) : null
    } catch {
        return null
    }
}

const state = reactive({
    user: loadUser(),
})

function isLocalGuestUser(user) {
    return Boolean(user?.localOnly || user?.email === 'invitat@local')
}

function persistUser(user) {
    try {
        localStorage.setItem('parkingUser', JSON.stringify(user))
    } catch { }
}

function clearStoredUser() {
    try {
        localStorage.removeItem('parkingUser')
    } catch { }
}

function notifySessionExpired() {
    window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT))
}

function normalizeUser(nextUser) {
    return {
        ...nextUser,
        role: nextUser?.role || 'guest',
    }
}

export function useAuth() {
    const user = computed(() => state.user)
    const isLoggedIn = computed(() => Boolean(state.user))
    const role = computed(() => state.user?.role || 'guest')
    const isLocalGuest = computed(() => isLocalGuestUser(state.user))

    function login(nextUser) {
        state.user = normalizeUser(nextUser)
        persistUser(state.user)
    }

    function setRole(nextRole) {
        if (!state.user) return

        state.user = {
            ...state.user,
            role: nextRole,
        }

        persistUser(state.user)
    }

    function clearSession({ expired = false } = {}) {
        state.user = null
        clearStoredUser()

        if (expired) notifySessionExpired()
    }

    function expireSession() {
        if (isLocalGuestUser(state.user)) return
        clearSession({ expired: true })
    }

    async function refreshSession() {
        if (!state.user || isLocalGuestUser(state.user)) return Boolean(state.user)

        try {
            const response = await fetch('/api/auth/me', {
                credentials: 'include',
            })

            if (response.status === 401) {
                expireSession()
                return false
            }

            if (!response.ok) return true

            const data = await response.json().catch(() => null)
            if (data) login(data)
            return true
        } catch {
            return Boolean(state.user)
        }
    }

    async function logout({ remote = false } = {}) {
        if (remote) {
            await fetch('/api/auth/logout', {
                method: 'POST',
                credentials: 'include',
            }).catch(() => null)
        }

        clearSession()
    }

    return {
        user,
        isLoggedIn,
        role,
        isLocalGuest,
        login,
        setRole,
        clearSession,
        expireSession,
        refreshSession,
        logout,
    }
}
