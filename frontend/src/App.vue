<script setup>
import { ref, onMounted } from 'vue'


const message = ref('Loading...')


onMounted(async () => {
	try {
		const res = await fetch('/api/test')
		const data = await res.json()
		message.value = data.message
	} catch (e) {
		message.value = 'Error connecting to backend'
		console.error(e)
	}
})
</script>

<template>
	<div style="padding: 2rem;">
	<h1>Parking Admin (Vue + FastAPI)</h1>
	<p>Backend says: <strong>{{ message }}</strong></p>
	</div>
</template>
