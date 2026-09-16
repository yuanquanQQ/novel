<template>
  <div class="page">
    <header class="page-header">
      <div><div class="eyebrow">MANUSCRIPT</div><h1>章节</h1><p>{{ store.novel?.title || novelName }} 的正文编辑与风格复检</p></div>
      <el-button :loading="loading" :disabled="!novelName" @click="refresh"><el-icon><Refresh /></el-icon>刷新</el-button>
    </header>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="section-gap" />
    <div v-if="!novelName" class="empty-panel"><el-empty description="请先选择小说" /></div>
    <el-row v-else :gutter="14" v-loading="loading" class="chapter-layout">
      <el-col :span="6">
        <div class="card list-card">
          <div class="filters">
            <el-input v-model="filters.q" clearable placeholder="搜索章号或章名" />
            <el-select v-model="filters.volume" clearable placeholder="全部卷">
              <el-option v-for="volume in volumes" :key="volume.key" :label="`${volume.name}（${volume.lo}-${volume.hi}）`" :value="volume.key" />
            </el-select>
            <el-select v-model="filters.status" clearable placeholder="全部状态">
              <el-option label="已生成" value="generated" />
              <el-option label="知识待同步" value="knowledge_stale" />
            </el-select>
            <div class="range-row">
              <el-input-number v-model="filters.from" :min="1" :controls="false" placeholder="起始章" />
              <span>至</span>
              <el-input-number v-model="filters.to" :min="1" :controls="false" placeholder="结束章" />
            </div>
          </div>
          <div v-for="c in chapters" :key="c.num" class="ch-item" :class="{ active: current === c.num }" @click="open(c.num)">
            <div class="ch-title">第{{ c.num }}章 {{ c.title }} <el-tag v-if="c.knowledge_stale" size="small" type="warning">知识待同步</el-tag></div>
            <div class="ch-words mono">{{ c.words.toLocaleString() }} 字</div>
          </div>
          <div v-if="!chapters.length" class="muted">没有符合条件的章节</div>
          <el-pagination v-if="total > pageSize" v-model:current-page="page" small layout="prev, pager, next" :page-size="pageSize" :total="total" />
          <div class="result-count muted">共 {{ total }} 章</div>
        </div>
      </el-col>
      <el-col :span="18">
        <div class="card" v-if="current">
          <div class="row editor-heading">
            <b>第{{ current }}章 · {{ content.length.toLocaleString() }} 字 <el-tag v-if="dirty" size="small" type="warning">未保存</el-tag></b>
            <div class="row">
              <el-select v-model="scanFilter" size="small" style="width: 130px"><el-option label="全部" value="all" /><el-option label="仅未过" value="violation" /></el-select>
              <el-button size="small" @click="doScan">重扫</el-button>
              <el-button size="small" :type="editing ? 'primary' : 'default'" @click="toggleEdit">{{ editing ? '编辑中' : '编辑' }}</el-button>
              <el-button size="small" @click="saveContent" :loading="saving" :disabled="!editing || !dirty">保存并复检</el-button>
            </div>
          </div>
          <el-row :gutter="12">
            <el-col :span="16">
              <el-input v-if="editing" v-model="content" type="textarea" :autosize="{ minRows: 22 }" style="font-family: monospace; font-size: 14px" />
              <div v-else class="prose chapter-prose">{{ content }}</div>
            </el-col>
            <el-col :span="8">
              <div class="card scan-card">
                <div class="row scan-heading"><b>扫描报告</b><el-tag :type="scanData.passed ? 'success' : 'danger'" size="small">{{ scanData.passed ? '通过' : '未通过' }}</el-tag></div>
                <div class="muted mono scan-metrics">{{ JSON.stringify(scanData.metrics) }}</div>
                <div v-for="(v, i) in visibleViolations" :key="i" class="scan-line"><el-tag size="small" type="danger">{{ v.category }}</el-tag>&nbsp;{{ v.pattern }}<span class="mono">x{{ v.count }}</span> @{{ v.where }}<div class="muted">{{ v.hint }}</div></div>
                <div v-for="(w, i) in scanData.warnings" v-if="scanFilter !== 'violation'" :key="'w' + i" class="scan-line"><el-tag size="small" type="warning">{{ w.category }}</el-tag>&nbsp;{{ w.pattern }}<span class="mono">x{{ w.count }}</span></div>
              </div>
            </el-col>
          </el-row>
        </div>
        <div v-else class="card muted">请从左侧选择章节</div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, reactive, watch, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useNovelStore } from '../stores/novel'
import { api } from '../api'

const store = useNovelStore()
const route = useRoute()
const novelName = computed(() => route.params.name || store.current || '')
const chapters = ref([])
const volumes = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)
const error = ref('')
const current = ref(null)
const content = ref('')
const serverContent = ref('')
const scanData = ref({ passed: true, metrics: {}, violations: [], warnings: [] })
const editing = ref(false)
const saving = ref(false)
const scanFilter = ref('all')
const filters = reactive({ q: '', volume: '', status: '', from: null, to: null })
const visibleViolations = computed(() => scanData.value.violations)
const dirty = computed(() => current.value !== null && content.value !== serverContent.value)
let novelSeq = 0
let chapterRequestSeq = 0
let listRequestSeq = 0
let scanRequestSeq = 0
let saveRequestSeq = 0
let filterTimer = null
let loadingContent = false

const draftKey = (name, chapter) => `novel:chapter-draft:${name}:${chapter}`
function readDraft(name, chapter) {
  try { return localStorage.getItem(draftKey(name, chapter)) } catch { return null }
}
function clearDraft(name, chapter) {
  try { localStorage.removeItem(draftKey(name, chapter)) } catch { return }
}
function clearSavedDraft(name, chapter, savedContent) {
  if (readDraft(name, chapter) === savedContent) clearDraft(name, chapter)
}
function isCurrentNovel(name, seq) {
  return name === novelName.value && seq === novelSeq
}
async function confirmDiscard() {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('当前章节有未保存修改，切换后仍会保留本地草稿。确定继续吗？', '未保存修改', { type: 'warning', confirmButtonText: '继续', cancelButtonText: '留在本章' })
    return true
  } catch { return false }
}

async function open(n, force = false) {
  const name = novelName.value
  if (!name || !n || (n === current.value && !force)) return
  if (!force && !(await confirmDiscard())) return
  const contextSeq = novelSeq
  const seq = ++chapterRequestSeq
  try {
    const [chapter, serverScan] = await Promise.all([api.chapter(name, n), api.scanChapter(name, n)])
    if (seq !== chapterRequestSeq || !isCurrentNovel(name, contextSeq)) return
    const draft = readDraft(name, n)
    const restored = draft !== null && draft !== chapter.content
    const displayedContent = restored ? draft : chapter.content
    const scan = restored ? await api.scanPreview(displayedContent) : serverScan
    if (seq !== chapterRequestSeq || !isCurrentNovel(name, contextSeq)) return
    current.value = n
    serverContent.value = chapter.content
    loadingContent = true
    content.value = displayedContent
    loadingContent = false
    scanData.value = scan
    editing.value = restored
    if (restored) ElMessage.warning('已恢复本章未保存草稿')
  } catch (e) {
    if (seq === chapterRequestSeq && isCurrentNovel(name, contextSeq)) error.value = e.response?.data?.detail || '章节加载失败'
  }
}

function pageParams() {
  const volume = volumes.value.find(item => item.key === filters.volume)
  let from = filters.from ?? volume?.lo
  let to = filters.to ?? volume?.hi
  if (volume) {
    if (from != null) from = Math.min(volume.hi, Math.max(volume.lo, from))
    if (to != null) to = Math.min(volume.hi, Math.max(volume.lo, to))
  }
  if (from != null && to != null && from > to) [from, to] = [to, from]
  return {
    offset: (page.value - 1) * pageSize,
    limit: pageSize,
    q: filters.q || undefined,
    status: filters.status || undefined,
    chapter_from: from || undefined,
    chapter_to: to || undefined,
  }
}
async function loadChapters(name = novelName.value) {
  if (!name) return false
  const contextSeq = novelSeq
  const seq = ++listRequestSeq
  const result = await api.chaptersPage(name, pageParams())
  if (seq !== listRequestSeq || !isCurrentNovel(name, contextSeq)) return false
  const lastPage = Math.max(1, Math.ceil(result.total / pageSize))
  if (page.value > lastPage) {
    page.value = lastPage
    return false
  }
  chapters.value = result.items
  total.value = result.total
  return true
}
async function fetchVolumes(name) {
  const data = await api.titles(name)
  return Object.entries(data.volumes || {}).map(([key, value]) => ({ key, name: value.name || key, lo: value.range?.[0], hi: value.range?.[1] })).filter(item => item.lo && item.hi)
}
async function loadNovel() {
  const name = novelName.value
  const seq = ++novelSeq
  chapterRequestSeq++
  listRequestSeq++
  scanRequestSeq++
  current.value = null
  chapters.value = []
  volumes.value = []
  total.value = 0
  content.value = ''
  serverContent.value = ''
  error.value = ''
  editing.value = false
  page.value = 1
  Object.assign(filters, { q: '', volume: '', status: '', from: null, to: null })
  if (!name) return
  loading.value = true
  try {
    const loadedVolumes = await fetchVolumes(name)
    if (!isCurrentNovel(name, seq)) return
    volumes.value = loadedVolumes
    const loaded = await loadChapters(name)
    if (!loaded || !isCurrentNovel(name, seq)) return
    if (chapters.value.length) await open(chapters.value[chapters.value.length - 1].num, true)
  } catch (e) {
    if (isCurrentNovel(name, seq)) error.value = e.response?.data?.detail || '章节列表加载失败'
  } finally {
    if (isCurrentNovel(name, seq)) loading.value = false
  }
}
async function refresh() {
  if (!(await confirmDiscard())) return
  await loadNovel()
}
async function saveContent() {
  const name = novelName.value
  const chapter = current.value
  const savedContent = content.value
  if (!name || !chapter) return
  const seq = ++saveRequestSeq
  saving.value = true
  try {
    const res = await api.saveChapter(name, chapter, savedContent)
    clearSavedDraft(name, chapter, savedContent)
    const sameChapter = name === novelName.value && chapter === current.value
    if (sameChapter) {
      serverContent.value = savedContent
      if (content.value === savedContent) {
        scanData.value = res.scan
        editing.value = false
      }
    }
    if (res.knowledge_stale) ElMessage.warning('正文已保存；本章知识归档已标记为待同步')
    else if (res.scan.passed) ElMessage.success('保存成功，扫描通过')
    else ElMessage.warning(`已保存，但仍有 ${res.scan.violations.length} 处违规`)
    if (name === novelName.value) await loadChapters(name)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    if (seq === saveRequestSeq) saving.value = false
  }
}
async function doScan() {
  const name = novelName.value
  const chapter = current.value
  const scannedContent = content.value
  if (!name || !chapter) return
  const contextSeq = novelSeq
  const seq = ++scanRequestSeq
  try {
    const scan = scannedContent !== serverContent.value ? await api.scanPreview(scannedContent) : await api.scanChapter(name, chapter)
    if (seq === scanRequestSeq && isCurrentNovel(name, contextSeq) && chapter === current.value && scannedContent === content.value) scanData.value = scan
  } catch (e) {
    if (seq === scanRequestSeq && isCurrentNovel(name, contextSeq)) error.value = e.response?.data?.detail || '扫描失败'
  }
}
function toggleEdit() { editing.value = !editing.value }
function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }

watch(content, value => {
  if (loadingContent || !editing.value || !current.value || !novelName.value) return
  try { localStorage.setItem(draftKey(novelName.value, current.value), value) } catch { return }
})
watch(() => [filters.q, filters.volume, filters.status, filters.from, filters.to], () => {
  clearTimeout(filterTimer)
  const name = novelName.value
  const contextSeq = novelSeq
  filterTimer = window.setTimeout(async () => {
    if (!isCurrentNovel(name, contextSeq)) return
    page.value = 1
    try { await loadChapters(name) } catch (e) {
      if (isCurrentNovel(name, contextSeq)) error.value = e.response?.data?.detail || '章节筛选失败'
    }
  }, 250)
})
watch(page, () => {
  const name = novelName.value
  const contextSeq = novelSeq
  loadChapters(name).catch(e => {
    if (isCurrentNovel(name, contextSeq)) error.value = e.response?.data?.detail || '章节分页加载失败'
  })
})
watch(novelName, loadNovel, { immediate: true })
window.addEventListener('beforeunload', beforeUnload)
onBeforeUnmount(() => {
  novelSeq++
  clearTimeout(filterTimer)
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<style scoped>
.list-card { max-height: 76vh; overflow-y: auto; padding: 7px }
.filters { display: grid; gap: 7px; margin-bottom: 9px }
.range-row { display: flex; align-items: center; gap: 6px }
.range-row :deep(.el-input-number) { width: calc(50% - 13px) }
.ch-item { padding: 11px 12px; cursor: pointer; border: 1px solid transparent; border-radius: 8px; margin: 2px 0 }
.ch-item:hover { background: var(--surface-soft) }
.ch-item.active { color: var(--primary); background: var(--primary-soft); border-color: #dbe8e5 }
.ch-title { font-weight: 500; font-size: 14px; margin-bottom: 3px }
.ch-words { font-size: 12px; color: var(--muted) }
.list-card :deep(.el-pagination) { justify-content: center; margin-top: 10px }
.result-count { text-align: center; margin: 6px 0 }
.editor-heading, .scan-heading { justify-content: space-between; margin-bottom: 10px }
.chapter-prose { max-height: 72vh; overflow-y: auto }
.scan-card { background: #fafbfc }
.scan-metrics { margin-bottom: 8px }
.scan-line { margin: 4px 0 }
@media (max-width: 900px) { .chapter-layout :deep(.el-col-6), .chapter-layout :deep(.el-col-18) { max-width: 100%; flex: 0 0 100%; } .list-card { max-height: 360px; margin-bottom: 14px; } }
</style>
