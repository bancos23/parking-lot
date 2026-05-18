import { createRouter, createWebHistory } from 'vue-router'
import Home from '@frontend/pages/Home.vue'
import Login from '@frontend/pages/Login.vue'
import Privacy from '@frontend/pages/Privacy.vue'
import Support from '@frontend/pages/Support.vue'
import Terms from '@frontend/pages/Terms.vue'
import { useAuth } from '@frontend/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: Home, meta: { requiresAuth: true } },
    { path: '/login', name: 'login', component: Login },
    { path: '/terms', name: 'terms', component: Terms },
    { path: '/privacy', name: 'privacy', component: Privacy },
    { path: '/support', name: 'support', component: Support },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const { isLoggedIn, isLocalGuest, refreshSession } = useAuth()

  if (to.meta.requiresAuth) {
    if (!isLoggedIn.value) return { name: 'login' }
    if (!isLocalGuest.value && !(await refreshSession())) return { name: 'login' }
  }

  if (to.name === 'login' && isLoggedIn.value) {
    if (isLocalGuest.value || await refreshSession()) return { name: 'home' }
  }

  return true
})

export default router
