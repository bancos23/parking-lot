import { createRouter, createWebHistory } from 'vue-router'
import Login from './pages/Login.vue'
import Register from './pages/Register.vue'
import Home from './pages/Home.vue'
import ParkingLots from './pages/ParkingLots.vue'
import ParkingSpaces from './pages/ParkingSpaces.vue'

const routes = [
  { path: '/', component: Home },
  { path: '/login', component: Login },
  { path: '/register', component: Register },
  { path: '/lots', component: ParkingLots },
  { path: '/spaces', component: ParkingSpaces },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
