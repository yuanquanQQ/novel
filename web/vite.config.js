import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 11451,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:11452',
        changeOrigin: true
      }
    }
  }
})
