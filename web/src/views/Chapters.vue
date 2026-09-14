<template>
  <div class="page">
    <header class="page-header"><div><div class="eyebrow">MANUSCRIPT</div><h1>章节</h1><p>{{ store.novel?.title || novelName }} 的正文编辑与风格复检</p></div><el-button :loading="loading" :disabled="!novelName" @click="loadNovel"><el-icon><Refresh /></el-icon>刷新</el-button></header>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="section-gap" />
    <div v-if="!novelName" class="empty-panel"><el-empty description="请先选择小说" /></div>
    <el-row v-else :gutter="14" v-loading="loading" class="chapter-layout">
      <el-col :span="6">
        <div class="card list-card">
          <div v-for="c in chapters" :key="c.num" class="ch-item" :class="{ active: current === c.num }" @click="open(c.num)">
            <div class="ch-title">第{{ c.num }}章 {{ c.title }}</div>
            <div class="ch-words mono">{{ c.words.toLocaleString() }} 字</div>
          </div>
          <div v-if="!chapters.length" class="muted">暂无章节，去控制台生成</div>
        </div>
      </el-col>
      <el-col :span="18">
        <div class="card" v-if="current">
          <div class="row" style="justify-content: space-between; margin-bottom: 10px">
            <b>第{{ current }}章 · {{ content.length.toLocaleString() }} 字</b>
            <div class="row">
              <el-select v-model="scanFilter" size="small" style="width: 130px"><el-option label="全部" value="all" /><el-option label="仅未过" value="violation" /></el-select>
              <el-button size="small" @click="doScan">重扫</el-button>
              <el-button size="small" :type="editing ? 'primary' : 'default'" @click="toggleEdit">{{ editing ? '编辑中' : '编辑' }}</el-button>
              <el-button size="small" @click="saveContent" :loading="saving" :disabled="!editing">保存并复检</el-button>
            </div>
          </div>
          <el-row :gutter="12">
            <el-col :span="16">
              <el-input v-if="editing" v-model="content" type="textarea" :autosize="{ minRows: 22 }" style="font-family: monospace; font-size: 14px" />
              <div v-else class="prose" style="max-height: 72vh; overflow-y: auto">{{ content }}</div>
            </el-col>
            <el-col :span="8">
              <div class="card" style="background: #fafbfc">
                <div class="row" style="justify-content: space-between; margin-bottom: 8px">
                  <b>扫描报告</b>
                  <el-tag :type="scanData.passed ? 'success' : 'danger'" size="small">{{ scanData.passed ? '通过' : '未通过' }}</el-tag>
                </div>
                <div class="muted mono" style="margin-bottom: 8px">{{ JSON.stringify(scanData.metrics) }}</div>
                <div v-for="(v, i) in visibleViolations" :key="i" style="margin: 4px 0">
                  <el-tag size="small" type="danger">{{ v.category }}</el-tag>
                  &nbsp;{{ v.pattern }}<span class="mono">x{{ v.count }}</span> @{{ v.where }}
                  <div class="muted">{{ v.hint }}</div>
                </div>
                <div v-for="(w, i) in scanData.warnings" v-if="scanFilter !== 'violation'" :key="'w' + i" style="margin: 4px 0">
                  <el-tag size="small" type="warning">{{ w.category }}</el-tag>
                  &nbsp;{{ w.pattern }}<span class="mono">x{{ w.count }}</span>
                </div>
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
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '../stores/novel'
import { api } from '../api'

const store = useNovelStore()
const route = useRoute()
const novelName = computed(() => route.params.name || store.current || '')
const chapters = ref([])
const loading = ref(false)
const error = ref('')
const current = ref(null)
const content = ref('')
const scanData = ref({ passed: true, metrics: {}, violations: [], warnings: [] })
const editing = ref(false)
const saving = ref(false)
const scanFilter = ref('all')
const visibleViolations = computed(() => scanData.value.violations)
let requestSeq = 0

async function open(n) {
  const name = novelName.value
  if (!name || !n) return
  const seq = ++requestSeq
  current.value = n
  try {
    const [c, s] = await Promise.all([api.chapter(name, n), api.scanChapter(name, n)])
    if (seq !== requestSeq || name !== novelName.value) return
    content.value = c.content
    scanData.value = s
    editing.value = false
  } catch (e) { if (seq === requestSeq) error.value = e.response?.data?.detail || '章节加载失败' }
}

async function loadChapters(name = novelName.value) { if (name) chapters.value = await api.chapters(name) }

async function loadNovel() {
  const name = novelName.value
  const seq = ++requestSeq
  current.value = null
  chapters.value = []
  content.value = ''
  error.value = ''
  scanData.value = { passed: true, metrics: {}, violations: [], warnings: [] }
  editing.value = false
  scanFilter.value = 'all'
  if (!name) return
  loading.value = true
  try {
    const loadedChapters = await api.chapters(name)
    if (seq !== requestSeq || name !== novelName.value) return
    chapters.value = loadedChapters
    if (chapters.value.length) await open(chapters.value[chapters.value.length - 1].num)
  } catch (e) { if (seq === requestSeq) error.value = e.response?.data?.detail || '章节列表加载失败' }
  finally { if (name === novelName.value) loading.value = false }
}
async function saveContent() {
  if (!novelName.value || !current.value) return
  saving.value = true
  try {
    const res = await api.saveChapter(novelName.value, current.value, content.value)
    scanData.value = res.scan
    if (res.scan.passed) ElMessage.success('保存成功，扫描通过')
    else ElMessage.warning(`已保存，但仍有 ${res.scan.violations.length} 处违规`)
    editing.value = false
    loadChapters()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally { saving.value = false }
}
async function doScan() {
  const name = novelName.value
  if (!name || !current.value) return
  const seq = ++requestSeq
  try {
    const result = await api.scanChapter(name, current.value)
    if (seq === requestSeq && name === novelName.value) scanData.value = result
  } catch (e) { error.value = e.response?.data?.detail || '扫描失败' }
}
function toggleEdit() { editing.value = !editing.value }

watch(novelName, loadNovel, { immediate: true })
</script>

<style scoped>
.list-card { max-height: 76vh; overflow-y: auto; padding: 7px }
.ch-item { padding: 11px 12px; cursor: pointer; border: 1px solid transparent; border-radius: 8px; margin: 2px 0 }
.ch-item:hover { background: var(--surface-soft) }
.ch-item.active { color: var(--primary); background: var(--primary-soft); border-color: #dbe8e5 }
.ch-title { font-weight: 500; font-size: 14px; margin-bottom: 3px }
.ch-words { font-size: 12px; color: var(--muted) }
@media (max-width: 900px) { .chapter-layout :deep(.el-col-6), .chapter-layout :deep(.el-col-18) { max-width: 100%; flex: 0 0 100%; } .list-card { max-height: 240px; margin-bottom: 14px; } }
</style>
