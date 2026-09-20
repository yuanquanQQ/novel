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
              <el-option label="待修订" value="pending" />
            </el-select>
            <div class="range-row">
              <el-input-number v-model="filters.from" :min="1" :controls="false" placeholder="起始章" />
              <span>至</span>
              <el-input-number v-model="filters.to" :min="1" :controls="false" placeholder="结束章" />
            </div>
          </div>
          <div v-for="c in chapters" :key="c.num" class="ch-item" :class="{ active: current === c.num }" @click="open(c.num)">
            <div class="ch-title">第{{ c.num }}章 {{ c.title }} <el-tag v-if="c.pending" size="small" type="danger">待修订</el-tag><el-tag v-if="c.knowledge_stale" size="small" type="warning">知识待同步</el-tag></div>
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
            <b>第{{ current }}章 · {{ content.length.toLocaleString() }} 字 <el-tag v-if="pendingMode" size="small" type="danger">待修订</el-tag><el-tag v-if="dirty" size="small" type="warning">未保存</el-tag></b>
            <div class="row">
              <el-select v-model="scanFilter" size="small" style="width: 130px"><el-option label="全部" value="all" /><el-option label="仅未过" value="violation" /></el-select>
              <el-button size="small" @click="doScan">重扫</el-button>
              <el-button size="small" :type="editing ? 'primary' : 'default'" @click="toggleEdit">{{ editing ? '编辑中' : '编辑' }}</el-button>
              <template v-if="pendingMode">
                <el-button size="small" @click="savePendingContent" :loading="saving" :disabled="publishing || !editing || !dirty">保存到待修订</el-button>
                <el-button size="small" type="primary" @click="publishPending" :loading="publishing" :disabled="saving || !content.trim()">发布</el-button>
                <el-button size="small" type="danger" plain @click="discardPending" :disabled="publishing || saving">丢弃</el-button>
              </template>
              <el-button v-else size="small" @click="saveContent" :loading="saving" :disabled="!editing || !dirty">保存并复检</el-button>
            </div>
          </div>
          <el-row :gutter="12">
            <el-col :span="16">
              <el-input v-if="editing" v-model="content" :disabled="publishing || saving" type="textarea" :autosize="{ minRows: 22 }" style="font-family: monospace; font-size: 14px" />
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
          <div v-if="pendingMode" class="card scan-card diag-card">
            <div v-for="review in diagData?.reasons?.chapter_review || []" :key="review.attempt">
              <b>整章审阅 · 第 {{ review.attempt }} 轮</b>
              <p v-for="issue in review.issues" :key="issue">{{ issue }}</p>
            </div>
            <p v-if="diagData?.edited_after_review" class="muted">正文已修改，以上为修改前诊断。</p>
            <div class="row scan-heading"><b>质量诊断</b><span class="muted mono">revision/chapter_{{ String(current).padStart(2, '0') }}.json</span></div>
            <template v-if="diagData?.reasons?.scene_failures?.length">
              <div class="diag-group-title">场景失败（重试耗尽）</div>
              <div v-for="(sf, i) in diagData.reasons.scene_failures" :key="i" class="diag-block">
                <div>场景 {{ sf.scene_id }} · {{ sf.attempts }} 次尝试 · 最佳分 {{ sf.best_score }}</div>
                <div class="row">
                  <el-tag v-for="(val, key) in sf.gates" :key="key" size="small" :type="val ? 'success' : 'danger'" class="gate-tag">{{ key }}: {{ val ? '通过' : '未过' }}</el-tag>
                </div>
              </div>
            </template>
            <template v-if="diagData?.reasons?.final_scan?.length">
              <div class="diag-group-title">最终扫描（{{ diagData.reasons.final_scan.length }} 条）</div>
              <div v-for="(f, i) in diagData.reasons.final_scan" :key="i" class="scan-line">
                <el-tag size="small" type="danger">{{ f.category }}</el-tag>&nbsp;{{ f.pattern }}<span class="mono">x{{ f.count }}</span> @{{ f.where }}
                <div class="muted">{{ f.hint }}</div>
              </div>
            </template>
            <div v-if="!diagData?.reasons?.scene_failures?.length && !diagData?.reasons?.final_scan?.length" class="muted">无诊断信息</div>
          </div>
          <div v-if="publishing || publishLog.length" class="card scan-card diag-card">
            <div class="diag-group-title">发布任务日志</div>
            <div v-for="(line, i) in publishLog" :key="i" class="mono log-line">{{ line }}</div>
          </div>
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
import { api, taskEventSource } from '../api'
import { saveThenPublish } from '../lib/publishPending'

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
const pendingMode = ref(false)
const diagData = ref(null)
const publishing = ref(false)
const publishLog = ref([])
const visibleViolations = computed(() => scanData.value.violations)
const dirty = computed(() => current.value !== null && content.value !== serverContent.value)
let novelSeq = 0
let chapterRequestSeq = 0
let listRequestSeq = 0
let scanRequestSeq = 0
let saveRequestSeq = 0
let filterTimer = null
let loadingContent = false
let publishSource = null

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
  if (publishing.value || saving.value) return
  const name = novelName.value
  if (!name || !n || (n === current.value && !force)) return
  if (!force && !(await confirmDiscard())) return
  const contextSeq = novelSeq
  const seq = ++chapterRequestSeq
  try {
    const item = chapters.value.find(c => c.num === n)
    if (item?.pending) {
      // 待修订章节：正文与诊断来自 revision/，扫描用预览接口
      const data = await api.pendingChapter(name, n)
      if (seq !== chapterRequestSeq || !isCurrentNovel(name, contextSeq)) return
      const draft = readDraft(name, n)
      const restored = draft !== null && draft !== data.content
      const displayedContent = restored ? draft : data.content
      const scan = await api.scanPreview(displayedContent)
      if (seq !== chapterRequestSeq || !isCurrentNovel(name, contextSeq)) return
      current.value = n
      serverContent.value = data.content
      loadingContent = true
      content.value = displayedContent
      loadingContent = false
      scanData.value = scan
      diagData.value = data.diagnostics || null
      pendingMode.value = true
      editing.value = restored
      if (restored) ElMessage.warning('已恢复本章未保存草稿')
    } else {
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
      pendingMode.value = false
      diagData.value = null
      editing.value = restored
      if (restored) ElMessage.warning('已恢复本章未保存草稿')
    }
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
  publishSource?.close()
  publishSource = null
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
  pendingMode.value = false
  diagData.value = null
  publishing.value = false
  publishLog.value = []
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
async function savePendingContent() {
  const name = novelName.value
  const chapter = current.value
  const savedContent = content.value
  if (!name || !chapter) return
  saving.value = true
  try {
    const res = await api.savePendingChapter(name, chapter, savedContent)
    clearSavedDraft(name, chapter, savedContent)
    if (name === novelName.value && chapter === current.value) {
      serverContent.value = savedContent
      if (content.value === savedContent) {
        scanData.value = res.scan
        editing.value = false
      }
    }
    if (res.scan.passed) ElMessage.success('待修订稿已保存，扫描通过')
    else ElMessage.warning(`已保存到待修订，仍余 ${res.scan.violations.length} 处违规`)
    if (name === novelName.value) await loadChapters(name)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function publishPending() {
  const name = novelName.value
  const chapter = current.value
  if (!name || !chapter || saving.value || publishing.value) return
  const contextSeq = novelSeq
  try {
    await ElMessageBox.confirm(`确认发布第 ${chapter} 章？将跑完整归档管线并移出待修订队列。`, '发布章节', { type: 'warning', confirmButtonText: '发布', cancelButtonText: '取消' })
  } catch { return }
  if (!isCurrentNovel(name, contextSeq) || chapter !== current.value) return
  const publishedContent = content.value
  publishing.value = true
  publishLog.value = []
  let taskDone = false
  try {
    const res = await saveThenPublish({
      api, name, chapter, content: publishedContent,
      isCurrent: () => isCurrentNovel(name, contextSeq) && chapter === current.value,
      onSaved: () => { serverContent.value = publishedContent },
    })
    if (!res) return
    if (!isCurrentNovel(name, contextSeq)) return
    const source = taskEventSource(res.task_id)
    publishSource = source
    source.onmessage = (event) => {
      if (!isCurrentNovel(name, contextSeq) || source !== publishSource) return
      let data
      try { data = JSON.parse(event.data) } catch { return }
      // 任务流事件是 JSON 字符串（如 "第 1 章已发布\n" / "__TASK_END__ done"），
      // 结束标记只能按字符串前缀识别，不能当对象属性取。
      if (typeof data === 'string' && data.startsWith('__TASK_END__')) {
        taskDone = true
        source.close()
        publishing.value = false
        const status = data.split(' ')[1]
        if (status === 'done') {
          ElMessage.success(`第 ${chapter} 章发布成功`)
          clearSavedDraft(name, chapter, publishedContent)
          loadNovel()
        } else {
          ElMessage.error(`发布失败：任务异常退出（${status}）`)
          error.value = `发布失败：任务异常退出（${status}）`
        }
        return
      }
      const line = data.message || data.line || (typeof data === 'string' ? data : JSON.stringify(data))
      if (line) publishLog.value.push(String(line))
    }
    source.onerror = () => {
      if (!isCurrentNovel(name, contextSeq) || source !== publishSource) return
      if (!taskDone) {
        source.close()
        publishing.value = false
        ElMessage.error('发布任务连接中断')
      }
    }
  } catch (e) {
    if (isCurrentNovel(name, contextSeq)) publishing.value = false
    ElMessage.error(e.response?.data?.detail || '发布任务启动失败')
  }
}

async function discardPending() {
  const name = novelName.value
  const chapter = current.value
  if (!name || !chapter) return
  try {
    await ElMessageBox.confirm(`丢弃第 ${chapter} 章待修订稿？此操作不可恢复。`, '丢弃待修订', { type: 'warning', confirmButtonText: '丢弃', cancelButtonText: '取消' })
  } catch { return }
  try {
    await api.discardPending(name, chapter)
    clearDraft(name, chapter)
    ElMessage.success(`第 ${chapter} 章待修订稿已丢弃`)
    current.value = null
    content.value = ''
    serverContent.value = ''
    scanData.value = { passed: true, metrics: {}, violations: [], warnings: [] }
    pendingMode.value = false
    diagData.value = null
    await loadChapters(name)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '丢弃失败')
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
    const scan = pendingMode.value || scannedContent !== serverContent.value ? await api.scanPreview(scannedContent) : await api.scanChapter(name, chapter)
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
  publishSource?.close()
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
.diag-card { margin-top: 12px }
.diag-group-title { font-weight: 600; margin: 8px 0 4px; font-size: 13px }
.diag-block { margin: 6px 0 10px }
.gate-tag { margin-right: 4px }
.log-line { font-size: 12px; line-height: 1.6; word-break: break-all }
@media (max-width: 900px) { .chapter-layout :deep(.el-col-6), .chapter-layout :deep(.el-col-18) { max-width: 100%; flex: 0 0 100%; } .list-card { max-height: 360px; margin-bottom: 14px; } }
</style>
