<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AuthScreen from '../components/AuthScreen.vue'
import { useAuth } from '../stores/auth'

const router = useRouter()
const { login } = useAuth()
const busy = ref(false)
const authError = ref('')

function formatApiError(payload) {
    if (!payload) return ''
    if (typeof payload.detail === 'string') return payload.detail
    if (Array.isArray(payload.detail)) {
        return payload.detail.map((item) => item.msg || item.message || String(item)).join(' ')
    }
    if (payload.message) return payload.message
    return ''
}

function normalizeUser(user) {
    return {
        ...user,
        name: user.name || [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email?.split('@')[0],
        role: user.role || 'guest',
    }
}

async function handleLogin(payload) {
    authError.value = ''

    if (payload.action === 'guest') {
        login(normalizeUser({ ...payload, localOnly: true }))
        router.push('/')
        return
    }

    busy.value = true
    try {
        const isRegister = payload.action === 'register'
        const body = isRegister
            ? {
                email: payload.email,
                password: payload.password,
                name: payload.name,
                phone: payload.phone,
                role: payload.role,
                organisationName: payload.organisationName,
            }
            : {
                email: payload.email,
                password: payload.password,
            }

        const response = await fetch(isRegister ? '/api/auth/register' : '/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify(body),
        })
        const data = await response.json().catch(() => null)

        if (!response.ok) {
            throw new Error(formatApiError(data) || 'Authentication failed.')
        }

        login(normalizeUser(data))
        router.push('/')
    } catch (error) {
        authError.value = error.message || 'Authentication failed.'
    } finally {
        busy.value = false
    }
}
</script>

<template>
    <AuthScreen :busy="busy" :server-error="authError" @login="handleLogin" />
</template>
