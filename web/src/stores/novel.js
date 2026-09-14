import { defineStore } from 'pinia'
import { api } from '../api'

export const useNovelStore = defineStore('novel', {
  state: () => ({
    novels: [],
    current: localStorage.getItem('currentNovel') || '',
    loaded: false,
    loading: false,
    error: '',
  }),
  getters: {
    novel: (s) => s.novels.find(n => n.id === s.current),
    hasNovels: (s) => s.novels.length > 0,
  },
  actions: {
    async load() {
      if (this.loaded) return this.novels
      return this.reload()
    },
    async reload(preferred = this.current) {
      this.loading = true
      this.error = ''
      try {
        this.novels = await api.novels()
        const next = this.novels.find(n => n.id === preferred)?.id || this.novels[0]?.id || ''
        this.setNovel(next)
        this.loaded = true
        return this.novels
      } catch (error) {
        this.error = error.response?.data?.detail || '小说列表加载失败'
        this.loaded = true
        throw error
      } finally {
        this.loading = false
      }
    },
    reset() {
      this.novels = []
      this.current = ''
      this.loaded = false
      this.loading = false
      this.error = ''
      localStorage.removeItem('currentNovel')
    },
    setNovel(name = '') {
      this.current = name
      if (name) localStorage.setItem('currentNovel', name)
      else localStorage.removeItem('currentNovel')
    },
  },
})
