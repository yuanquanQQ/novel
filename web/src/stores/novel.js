import { defineStore } from 'pinia'
import { api } from '../api'

export const useNovelStore = defineStore('novel', {
  state: () => ({
    novels: [],
    current: localStorage.getItem('currentNovel') || 'mirror-city',
    loaded: false,
  }),
  getters: {
    novel: (s) => s.novels.find(n => n.id === s.current),
  },
  actions: {
    async load() {
      if (this.loaded) return
      this.novels = await api.novels()
      if (!this.novels.find(n => n.id === this.current) && this.novels.length) {
        this.current = this.novels[0].id
      }
      this.loaded = true
    },
    setNovel(name) {
      this.current = name
      localStorage.setItem('currentNovel', name)
    },
  },
})
