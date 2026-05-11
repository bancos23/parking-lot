<script setup>
defineProps({
  activePage: {
    type: String,
    required: true,
  },
  isLoggedIn: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['logout'])

const navItems = [
  { key: 'dashboard', label: 'Dashboard', to: '/' },
  { key: 'lots', label: 'Parking lots', to: '/lots' },
  { key: 'spaces', label: 'Parking spaces', to: '/spaces' },
]
</script>

<template>
  <aside class="dashboard-sidebar">
    <div class="logo">
      <div class="logo-icon">P</div>
      <span>ParkFlow</span>
    </div>

    <nav class="sidebar-nav">
      <RouterLink
        v-for="item in navItems"
        :key="item.key"
        class="nav-link"
        :class="{ active: activePage === item.key }"
        :to="item.to"
      >
        {{ item.label }}
      </RouterLink>
    </nav>

    <button v-if="isLoggedIn" class="logout-btn" type="button" @click="$emit('logout')">
      Logout
    </button>
  </aside>
</template>
