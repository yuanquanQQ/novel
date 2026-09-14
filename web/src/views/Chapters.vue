<template>
  <div class="page">
    <h2>章节 · {{ novelName }}</h2>
    <el-row :gutter="14">
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
const novelName = computed(() => route.params.name || store.current)
const chapters = ref([])
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
  const seq = ++requestSeq
  current.value = n
  const [c, s] = await Promise.all([api.chapter(name, n), api.scanChapter(name, n)])
  if (seq !== requestSeq || name !== novelName.value) return
  content.value = c.content
  scanData.value = s
  editing.value = false
}

async function loadChapters(name = novelName.value) { chapters.value = await api.chapters(name) }

async function loadNovel() {
  const name = novelName.value
  const seq = ++requestSeq
  current.value = null
  content.value = ''
  scanData.value = { passed: true, metrics: {}, violations: [], warnings: [] }
  editing.value = false
  scanFilter.value = 'all'
  await store.load()
  const loadedChapters = await api.chapters(name)
  if (seq !== requestSeq || name !== novelName.value) return
  chapters.value = loadedChapters
  if (chapters.value.length) open(chapters.value[chapters.value.length - 1].num)
}
async function saveContent() {
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
  const seq = ++requestSeq
  const result = await api.scanChapter(name, current.value)
  if (seq === requestSeq && name === novelName.value) scanData.value = result
}
function toggleEdit() { editing.value = !editing.value }

watch(() => route.params.name, loadNovel, { immediate: true })
</script>

<style scoped>
.list-card { max-height: 84vh; overflow-y: auto; padding: 6px }
.ch-item { padding: 10px 12px; cursor: pointer; border-radius: 8px; margin: 2px 0 }
.ch-item:hover { background: #f2f5fa }
.ch-item.active { background: #eaf3ff; color: #409eff }
.ch-title { font-weight: 500; font-size: 14px; margin-bottom: 2px }
.ch-words { font-size: 12px; color: #909399 }
</style>
