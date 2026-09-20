import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const apiTarget = mode === 'preview'
    ? 'http://127.0.0.1:11454'
    : process.env.NOVEL_API_TARGET || 'http://127.0.0.1:11452'

  return {
    plugins: [vue()],
    server: {
      port: 11451,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true
        }
      }
    }
  }
})
