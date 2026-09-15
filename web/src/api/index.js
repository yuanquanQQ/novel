import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 30000 })

export const api = {
  novels: () => http.get('/novels').then(r => r.data),
  generateNovelThemes: (data) => http.post('/novel-themes/generate', data, { timeout: 90000 }).then(r => r.data),
  createNovel: (data) => http.post('/novels', data).then(r => r.data),
  exportNovel: (n) => http.get(`/novels/${n}/export`, { responseType: 'blob' }).then(r => r.data),
  deleteNovel: (n) => http.delete(`/novels/${n}`).then(r => r.data),
  status: (n) => http.get(`/novels/${n}/status`).then(r => r.data),

  outline: (n) => http.get(`/novels/${n}/outline`).then(r => r.data),
  saveOutline: (n, content) => http.put(`/novels/${n}/outline`, { content }).then(r => r.data),
  titles: (n) => http.get(`/novels/${n}/titles`).then(r => r.data),
  saveTitle: (n, chapter, title) => http.put(`/novels/${n}/titles`, { chapter, title }).then(r => r.data),

  chapters: (n) => http.get(`/novels/${n}/chapters`).then(r => r.data),
  chapter: (n, num) => http.get(`/novels/${n}/chapters/${num}`).then(r => r.data),
  saveChapter: (n, num, content) => http.put(`/novels/${n}/chapters/${num}`, { content }).then(r => r.data),
  scanChapter: (n, num) => http.get(`/novels/${n}/scan/${num}`).then(r => r.data),
  scanPreview: (text) => http.post('/scan-preview', { text }).then(r => r.data),

  bibleList: (n) => http.get(`/novels/${n}/bible`).then(r => r.data),
  bibleFile: (n, fn) => http.get(`/novels/${n}/bible/${fn}`, { responseType: 'text', transformResponse: [d => d] }).then(r => r.data),
  saveBibleFile: (n, fn, content) => http.put(`/novels/${n}/bible/${fn}`, { content }).then(r => r.data),
  knowledgeSync: (n) => http.post(`/novels/${n}/knowledge-base/sync`).then(r => r.data),

  dbCharacters: (n) => http.get(`/novels/${n}/db/characters`).then(r => r.data),
  saveCharacter: (n, id, data) => http.put(`/novels/${n}/db/characters/${encodeURIComponent(id)}`, data).then(r => r.data),
  dbClues: (n) => http.get(`/novels/${n}/db/clues`).then(r => r.data),
  saveClue: (n, id, data) => http.put(`/novels/${n}/db/clues/${encodeURIComponent(id)}`, data).then(r => r.data),
  dbMotifs: (n) => http.get(`/novels/${n}/db/motifs`).then(r => r.data),
  dbForeshadowUpdate: (n, id, data) => http.put(`/novels/${n}/db/foreshadowing/${encodeURIComponent(id)}`, data).then(r => r.data),
  dbForeshadow: (n, current) => http.get(`/novels/${n}/db/foreshadowing`, { params: { current } }).then(r => r.data),
  dbFacts: (n, params) => http.get(`/novels/${n}/db/facts`, { params }).then(r => r.data),
  dbStyleHits: (n) => http.get(`/novels/${n}/db/style-hits`).then(r => r.data),
  dbLessons: (n) => http.get(`/novels/${n}/db/lessons`).then(r => r.data),

  styleKit: () => http.get('/style-kit').then(r => r.data),
  saveStyleKit: (data) => http.put('/style-kit', data).then(r => r.data),
  styleDoc: (doc) => http.get(`/style-kit/docs/${doc}`, { responseType: 'text', transformResponse: [d => d] }).then(r => r.data),

  tasks: (n) => http.get(`/novels/${n}/tasks`).then(r => r.data),
  runTask: (n, action, body) => http.post(`/novels/${n}/tasks/${action}`, body).then(r => r.data),

  pipeline: (n) => http.get(`/novels/${n}/pipeline`).then(r => r.data),
  modelConfig: (n) => http.get(`/novels/${n}/model-config`).then(r => r.data),
  saveModelConfig: (n, body) => http.put(`/novels/${n}/model-config`, body).then(r => r.data),
  testModelConfig: (n, body) => http.post(`/novels/${n}/model-config/test`, body).then(r => r.data),
}

export function taskEventSource(tid) {
  return new EventSource(`/api/tasks/${tid}/events`)
}

export default api
