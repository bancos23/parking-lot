import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

function normalizeBasePath(basePath) {
  const value = String(basePath || '/').trim()
  if (!value || value === '/') return '/'

  return `/${value.replace(/^\/+|\/+$/g, '')}/`
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const base = normalizeBasePath(env.VITE_BASE_PATH)

  return {
    base,
    plugins: [vue()],
    resolve: {
      alias: {
        '@frontend': fileURLToPath(new URL('./src', import.meta.url))
      }
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
          timeout: 300000,
          proxyTimeout: 300000,
        }
      }
    }
  }
})
