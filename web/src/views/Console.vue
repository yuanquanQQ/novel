<template>
  <div class="page">
    <header class="page-header"><div><div class="eyebrow">GENERATION</div><h1>生成控制台</h1><p>{{ store.novel?.title || novelName }} 的生成任务与实时日志</p></div><el-button :loading="historyLoading" :disabled="!novelName" @click="refreshHistory"><el-icon><Refresh /></el-icon>刷新历史</el-button></header>
    <div v-if="!novelName" class="empty-panel"><el-empty description="请先选择小说" /></div>
    <template v-else>
      <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="section-gap" />
      <section class="content-card console-card">
        <el-form class="task-form" label-position="top">
          <el-form-item label="动作"><el-select v-model="action"><el-option label="生成章节" value="generate" /><el-option label="修订章节" value="revise" /><el-option label="卷末总结" value="summary" /><el-option label="全书大纲" value="outline" /><el-option label="章名库" value="titles" /><el-option label="知识库导入" value="db" /></el-select></el-form-item>
          <el-form-item v-if="['generate', 'revise'].includes(action)" label="章号"><el-input-number v-model="chapter" :min="1" :max="store.novel?.chapter_count || 999" controls-position="right" /></el-form-item>
          <el-form-item v-if="action === 'summary'" label="卷号"><el-input-number v-model="volume" :min="1" :max="8" controls-position="right" /></el-form-item>
          <el-form-item v-if="action !== 'db'" class="prompt-field" :label="action === 'revise' ? '修改要求' : '创作指令'"><el-input v-model="prompt" placeholder="补充本次任务的具体要求" /></el-form-item>
          <el-form-item label="操作"><div class="toolbar-group"><el-button type="primary" :loading="running" @click="run"><el-icon><VideoPlay /></el-icon>{{ running ? '运行中' : '执行' }}</el-button><el-button @click="clearLog"><el-icon><Delete /></el-icon>清屏</el-button></div></el-form-item>
        </el-form>
        <el-alert v-if="taskStatus === 'failed'" title="任务失败，请查看日志末尾" type="error" :closable="false" class="log-alert" /><el-alert v-else-if="taskStatus === 'done'" title="任务已完成" type="success" :closable="false" class="log-alert" />
        <div ref="logBox" class="log"><span v-if="logText">{{ logText }}</span><span v-else class="log-placeholder">任务输出会显示在这里</span></div>
      </section>
      <section class="content-card section-gap">
        <div class="card-heading"><div><h2>历史任务</h2><p>当前小说最近执行的任务</p></div></div>
        <el-table v-if="history.length" :data="history" v-loading="historyLoading" max-height="280"><el-table-column prop="action" label="动作" width="110" /><el-table-column label="参数" min-width="170"><template #default="{ row }"><span class="mono">{{ (row.args || []).join(' ').slice(0, 70) || '—' }}</span></template></el-table-column><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="tagType(row.status)" effect="plain">{{ row.status }}</el-tag></template></el-table-column><el-table-column label="开始时间" min-width="180"><template #default="{ row }">{{ row.started ? new Date(row.started * 1000).toLocaleString() : '—' }}</template></el-table-column><el-table-column prop="n_lines" label="日志行" width="80" /></el-table>
        <el-empty v-else :image-size="72" description="暂无历史任务" />
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '../stores/novel'
import { api, taskEventSource } from '../api'

const store = useNovelStore(); const route = useRoute(); const novelName = computed(() => route.params.name || store.current || '')
const action = ref('generate'); const chapter = ref(1); const volume = ref(1); const prompt = ref(''); const logText = ref(''); const running = ref(false); const taskStatus = ref(''); const history = ref([]); const historyLoading = ref(false); const error = ref(''); const logBox = ref(null)
let es = null; let requestSeq = 0
const tagType = (status) => ({ done: 'success', running: 'warning', failed: 'danger', error: 'danger' }[status] || 'info')

async function run() {
  const name = novelName.value
  if (!name || running.value) return
  try { const result = await api.runTask(name, action.value, { chapter: chapter.value || null, volume: volume.value || null, prompt: prompt.value }); startStream(result.task_id) }
  catch (e) { ElMessage.error(e.response?.data?.detail || '任务启动失败') }
}
function startStream(id) {
  running.value = true; taskStatus.value = ''; logText.value = ''; es?.close(); es = taskEventSource(id)
  es.onmessage = event => { const data = JSON.parse(event.data); logText.value += data; if (data.startsWith('__TASK_END__')) { taskStatus.value = data.split(' ')[1]; running.value = false; es.close(); refreshHistory(); store.reload(store.current).catch(() => {}) } nextTick(() => { if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight }) }
  es.onerror = () => { es?.close(); running.value = false; refreshHistory() }
}
function clearLog() { logText.value = '' }
async function refreshHistory() {
  const name = novelName.value; const seq = ++requestSeq
  history.value = []; error.value = ''
  if (!name) return
  historyLoading.value = true
  try { const rows = await api.tasks(name); if (seq === requestSeq && name === novelName.value) history.value = rows }
  catch (e) { if (seq === requestSeq) error.value = e.response?.data?.detail || '任务历史加载失败' }
  finally { if (seq === requestSeq) historyLoading.value = false }
}
watch(novelName, name => { es?.close(); running.value = false; taskStatus.value = ''; logText.value = ''; chapter.value = (store.novels.find(item => item.id === name)?.chapters_written || 0) + 1; refreshHistory() }, { immediate: true })
onBeforeUnmount(() => es?.close())
</script>

<style scoped>
.task-form { display: flex; align-items: end; gap: 12px; flex-wrap: wrap; }.task-form :deep(.el-form-item) { margin: 0 0 16px; }.task-form :deep(.el-select) { width: 150px; }.task-form :deep(.el-input-number) { width: 120px; }.prompt-field { flex: 1; min-width: 260px; }.prompt-field :deep(.el-input) { width: 100%; }.log-alert { margin-bottom: 12px; }.log-placeholder { color: #83918e; }
@media (max-width: 620px) { .task-form { display: block; }.task-form :deep(.el-form-item), .task-form :deep(.el-select), .task-form :deep(.el-input-number) { width: 100%; }.prompt-field { min-width: 0; } }
</style>
