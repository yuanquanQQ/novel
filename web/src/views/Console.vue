<template>
  <div class="page">
    <h2>生成控制台 · {{ store.novel?.title }}</h2>
    <div class="card">
      <el-form :inline="true">
        <el-form-item label="动作">
          <el-select v-model="action" style="width: 140px">
            <el-option label="生成章节" value="generate" />
            <el-option label="修订章节" value="revise" />
            <el-option label="卷末总结" value="summary" />
            <el-option label="全书大纲" value="outline" />
            <el-option label="章名库" value="titles" />
            <el-option label="知识库导入" value="db" />
          </el-select>
        </el-form-item>
        <el-form-item label="章号" v-if="['generate', 'revise'].includes(action)">
          <el-input-number v-model="chapter" :min="1" :max="store.novel?.chapter_count || 999" />
        </el-form-item>
        <el-form-item label="卷号" v-if="action === 'summary'">
          <el-input-number v-model="volume" :min="1" :max="8" />
        </el-form-item>
        <el-form-item :label="action === 'revise' ? '修改要求' : '创作指令'" v-if="action !== 'db'">
          <el-input v-model="prompt" style="width: 320px" placeholder="例：这章要有打斗场面，对话多一些" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="running" @click="run">
            {{ running ? '运行中…' : '执行' }}
          </el-button>
          <el-button @click="clearLog">清屏</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="taskStatus === 'failed'" title="任务失败，见日志末尾" type="error" :closable="false" style="margin-bottom: 10px" />
      <el-alert v-else-if="taskStatus === 'done'" title="任务完成" type="success" :closable="false" style="margin-bottom: 10px" />
      <div class="log" ref="logBox"><span>{{ logText }}</span></div>
    </div>

    <div class="card" style="margin-top: 14px">
      <h3 style="margin: 0 0 10px">历史任务</h3>
      <el-table :data="history" size="small" max-height="220">
        <el-table-column prop="action" label="动作" width="110" />
        <el-table-column label="参数" width="160"><template #default="{ row }"><span class="mono">{{ row.args.join(' ').slice(0, 40) }}</span></template></el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="tagType(row.status)" size="small">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="开始时间"><template #default="{ row }">{{ new Date(row.started * 1000).toLocaleString() }}</template></el-table-column>
        <el-table-column label="行数" width="70"><template #default="{ row }">{{ row.n_lines }}</template></el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '../stores/novel'
import { api, taskEventSource } from '../api'

const store = useNovelStore()
const action = ref('generate')
const chapter = ref(((store.novel?.chapters_written || 0) + 1) || 1)
const volume = ref(1)
const prompt = ref('')
const logText = ref('')
const running = ref(false)
const taskStatus = ref('')
const history = ref([])
const logBox = ref(null)
let es = null

const tagType = (s) => ({ done: 'success', running: 'warning', failed: 'danger', error: 'danger' }[s] || 'info')

async function run() {
  if (running.value) return
  try {
    const r = await api.runTask(store.current, action.value, {
      chapter: chapter.value || null, volume: volume.value || null, prompt: prompt.value,
    })
    startStream(r.task_id)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '启动失败')
  }
}

function startStream(tid) {
  running.value = true
  taskStatus.value = ''
  logText.value = ''
  es = taskEventSource(tid)
  es.onmessage = (ev) => {
    const data = JSON.parse(ev.data)
    logText.value += data
    if (data.startsWith('__TASK_END__')) {
      taskStatus.value = data.split(' ')[1]
      running.value = false
      es.close()
      refreshHistory()
      store.load?.()
    }
    nextTick(() => { if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight })
  }
  es.onerror = () => { es.close(); running.value = false; refreshHistory() }
}

function clearLog() { logText.value = '' }
async function refreshHistory() { history.value = await api.tasks(store.current) }

onMounted(async () => { await store.load(); chapter.value = (store.novel?.chapters_written || 0) + 1; refreshHistory() })
onBeforeUnmount(() => es && es.close())
</script>
