<template>
  <div class="page">
    <header class="page-header">
      <div>
        <div class="eyebrow">PIPELINE</div>
        <h1>生成控制台</h1>
        <p>{{ store.novel?.title || novelName }} · 按固定顺序推进：大纲 → 章名 → 逐章写作 → 卷末总结 → 发布</p>
      </div>
      <div class="page-actions">
        <el-tag v-if="pipe" effect="plain" size="large" :type="pipe.stage === 'publish' ? 'success' : 'warning'">{{ stageHint }}</el-tag>
        <el-button :loading="historyLoading || pipeLoading" @click="refreshAll"><el-icon><Refresh /></el-icon>刷新</el-button>
      </div>
    </header>

    <div v-if="!novelName" class="empty-panel"><el-empty description="请先选择小说" /></div>
    <template v-else>
      <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="section-gap" />

      <div class="pipeline" v-loading="pipeLoading">
        <!-- ① 大纲 -->
        <section class="step-card" :class="cardClass(0)">
          <div class="step-head">
            <span class="step-no">1</span>
            <div class="grow"><strong>全书大纲</strong><span class="muted"> bible/outline.md，决定每章写什么；生成后可去「大纲/章名」页人工修改</span></div>
            <el-tag v-if="s0?.done" type="success" size="small">已完成 · {{ s0.detected }} 章条目</el-tag>
            <el-tag v-else size="small">未生成</el-tag>
          </div>
          <div class="step-actions">
            <el-button :disabled="busy" type="primary" plain @click="run('outline', { prompt, force: !!s0?.done })" size="small">{{ s0?.done ? '重新生成' : '生成大纲' }}</el-button>
            <el-input v-model="prompt" size="small" class="grow" placeholder="可选：给策划编辑的修改要求（重生成时生效）" :disabled="busy" />
            <el-button link type="primary" @click="goto('outline')">去审阅 →</el-button>
          </div>
        </section>

        <!-- ② 章名 -->
        <section class="step-card" :class="cardClass(1)">
          <div class="step-head">
            <span class="step-no">2</span>
            <div class="grow"><strong>章名库</strong><span class="muted"> bible/chapter_titles.json，章名从此锁定；自动补全的名字建议改为带钩子的章节名</span></div>
            <el-tag v-if="s1?.done" :type="s1.auto_named ? 'warning' : 'success'" size="small">{{ s1.detected }} 个章名<template v-if="s1.auto_named">（{{ s1.auto_named }} 个待改名）</template></el-tag>
            <el-tag v-else size="small" :type="s1?.available ? 'info' : 'info'">{{ s1?.available ? '可提取' : '待上一步' }}</el-tag>
          </div>
          <div class="step-actions">
            <el-button :disabled="busy || !s1?.available" @click="run('titles', { prompt })" size="small">{{ s1?.done ? '补全/重生成' : '提取章名' }}</el-button>
          </div>
        </section>

        <!-- ③ 逐章写作 -->
        <section class="step-card writing" :class="cardClass(2)">
          <div class="step-head">
            <span class="step-no">3</span>
            <div class="grow">
              <strong>逐章写作 · {{ w?.detail?.volume }}</strong>
              <span class="muted">{{ w?.detected || 0 }}/{{ pipe?.chapter_count }} 章 · 本章走「三道闸」：风格扫描 → 语义审 → 声纹审计</span>
            </div>
            <el-tag :type="s2?.done ? 'success' : 'primary'" size="small">{{ s2?.done ? '全部完成' : `下一批 · 第 ${w?.detail?.next_chapter} 章` }}</el-tag>
          </div>
          <div class="vol-progress">
            <span class="muted mono">本卷 第{{ w?.detail?.range?.[0] }}–{{ w?.detail?.range?.[1] }}章</span>
            <el-progress :percentage="w?.detail?.volume_total ? Math.round(w.detail.volume_done * 100 / w.detail.volume_total) : 0" :stroke-width="8" style="flex:1" />
            <span class="muted mono">{{ w?.detail?.volume_done }}/{{ w?.detail?.volume_total }}</span>
          </div>
          <el-alert v-if="w?.detail?.missing?.length" type="warning" :closable="false" show-icon class="gap-alert"
                    :title="`缺章提示：第 ${w.detail.missing.join('、')} 章未写（流水线按顺序写作，建议先补）`" />
          <div class="step-actions">
            <el-input v-model="genPrompt" size="small" style="width: 260px" placeholder="可选：本章创作指令" :disabled="busy || s2done" />
            <el-button type="primary" :disabled="busy || !s2?.available" @click="runNext" size="small"><el-icon><VideoPlay /></el-icon>生成第 {{ w?.detail?.next_chapter }} 章</el-button>
            <span class="batch">
              <span class="muted">批量续写至第</span>
              <el-input-number v-model="batchEnd" size="small" :min="w?.detail?.next_chapter || 1" :max="maxEnd" controls-position="right" style="width: 110px" :disabled="busy || s2done" />
              <el-button size="small" :disabled="busy || !s2?.available" @click="runBatch" title="顺序执行，单章失败即停止">连写 {{ batchCount }} 章</el-button>
            </span>
            <el-button link type="primary" @click="goto('chapters')">去读已写章节 →</el-button>
          </div>
          <div class="muted tip">批量 = 一个任务依次跑 {{ batchCount }} 章（约 {{ batchCount * 8 }}-{{ batchCount * 14 }} 次 LLM 调用，注意成本；单任务上限 20 章，失败即停）</div>
        </section>

        <!-- ④ 卷末总结 + 修订 -->
        <section class="step-card" :class="cardClass(3)">
          <div class="step-head">
            <span class="step-no">4</span>
            <div class="grow"><strong>卷末总结</strong><span class="muted"> 每卷写完后生成，反哺下一卷规划</span></div>
            <el-tag v-if="s3?.pending?.length" type="warning" size="small">{{ s3.pending.length }} 卷待总结</el-tag>
            <el-tag v-else-if="s3?.done" type="success" size="small">无欠账</el-tag>
            <el-tag v-else size="small">{{ s3?.available ? '' : '尚无写完的卷' }}</el-tag>
          </div>
          <div class="step-actions" v-if="s3?.pending?.length">
            <el-button v-for="p in s3.pending" :key="p.key" size="small" type="warning" plain :disabled="busy" @click="run('summary', { volume: p.num })">生成「{{ p.name }}」总结</el-button>
          </div>
          <div class="step-actions revise-row">
            <span class="muted">单章修订：</span>
            <el-input-number v-model="reviseChapter" size="small" :min="1" :max="pipe?.chapter_count || 999" controls-position="right" style="width: 110px" :disabled="busy" />
            <el-input v-model="revisePrompt" size="small" style="width: 260px" placeholder="修改要求，如：节奏太快" :disabled="busy" />
            <el-button size="small" :disabled="busy || !revisePrompt" @click="run('revise', { chapter: reviseChapter, prompt: revisePrompt })">修订</el-button>
          </div>
        </section>

        <!-- ⑤ 发布 -->
        <section class="step-card" :class="cardClass(4)">
          <div class="step-head">
            <span class="step-no">5</span>
            <div class="grow"><strong>发布与宣传</strong><span class="muted"> 全部章节完成后：简介 / 标签 / 封面与立绘提示词 / 作者的话</span></div>
            <el-tag :type="s4?.done ? 'success' : 'info'" size="small">{{ s4?.done ? '可以发布 🎉' : '待续写' }}</el-tag>
          </div>
          <div class="step-actions">
            <span class="mono muted">python novel.py --novel {{ novelName }} promo synopsis | tags | cover | author</span>
          </div>
        </section>
      </div>

      <!-- 任务输出 -->
      <section class="content-card section-gap">
        <div class="card-heading">
          <div><h2>任务输出</h2><p>{{ running ? `运行中：${taskLabel}` : '最近任务的实时日志' }}</p></div>
          <div class="toolbar-group">
            <el-tag v-if="running && stepInfo.total > 1" type="warning">{{ stepInfo.done }}/{{ stepInfo.total }} 步</el-tag>
            <el-button v-if="running" size="small" type="danger" plain :loading="cancelling" @click="cancelCurrent">取消任务</el-button>
            <el-button size="small" @click="clearLog" :disabled="running">清屏</el-button>
          </div>
        </div>
        <el-alert v-if="['failed', 'error'].includes(taskStatus)" title="任务失败，见日志末尾" type="error" :closable="false" class="log-alert" />
        <el-alert v-else-if="taskStatus === 'done'" title="任务完成" type="success" :closable="false" class="log-alert" />
        <el-alert v-else-if="taskStatus === 'cancelled'" title="任务已取消" type="warning" :closable="false" class="log-alert" />
        <el-alert v-else-if="taskStatus === 'orphaned'" title="服务重启，任务已中断" type="warning" :closable="false" class="log-alert" />
        <div ref="logBox" class="log"><span v-if="logText">{{ logText }}</span><span v-else class="log-placeholder">点上方任意步骤的执行按钮，输出会实时显示在这里</span></div>
      </section>

      <section class="content-card section-gap">
        <div class="card-heading"><div><h2>历史任务</h2><p>当前小说最近执行的任务（同书串行）</p></div></div>
        <el-table v-if="history.length" :data="history" v-loading="historyLoading" max-height="260" size="small">
          <el-table-column prop="action" label="动作" width="100" />
          <el-table-column label="参数" min-width="160"><template #default="{ row }"><span class="mono">{{ (row.args || []).join(' ').slice(0, 56) || '—' }}</span></template></el-table-column>
          <el-table-column label="进度" width="90"><template #default="{ row }"><span class="mono" v-if="row.steps > 1">{{ row.done_steps||0 }}/{{ row.steps }}</span><span v-else>—</span></template></el-table-column>
          <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="tagType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column label="开始" min-width="150"><template #default="{ row }">{{ row.started ? new Date(row.started * 1000).toLocaleString() : '—' }}</template></el-table-column>
          <el-table-column label="操作" width="90"><template #default="{ row }"><el-button v-if="row.status === 'running'" link type="danger" :loading="cancelling" @click="cancelTask(row.id)">取消</el-button><span v-else>—</span></template></el-table-column>
        </el-table>
        <el-empty v-else :image-size="64" description="暂无历史任务" />
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '../stores/novel'
import { api, taskEventSource } from '../api'

const store = useNovelStore()
const route = useRoute()
const router = useRouter()
const novelName = computed(() => route.params.name || store.current || '')

const pipe = ref(null)
const pipeLoading = ref(false)
const prompt = ref('')
const genPrompt = ref('')
const batchEnd = ref(null)
const reviseChapter = ref(1)
const revisePrompt = ref('')
const logText = ref('')
const running = ref(false)
const cancelling = ref(false)
const currentTaskId = ref('')
const taskStatus = ref('')
const taskLabel = ref('')
const stepInfo = ref({ total: 1, done: 0 })
const history = ref([])
const historyLoading = ref(false)
const error = ref('')
const logBox = ref(null)
let es = null
let poll = null
let reconnectTimer = null
let statusPollTimer = null
let contextSeq = 0
let pipelineRequestSeq = 0
let historyRequestSeq = 0
let taskSessionSeq = 0
let reconnectAttempts = 0
let statusPollAttempts = 0
const maxReconnectAttempts = 3
const maxStatusPollAttempts = 10
const taskLabels = { outline: '生成大纲', titles: '提取章名', generate: '生成章节', summary: '卷末总结', revise: '修订章节', db: '知识库操作' }
const terminalStatuses = new Set(['done', 'failed', 'error', 'orphaned', 'cancelled'])

const s0 = computed(() => step('outline'))
const s1 = computed(() => step('titles'))
const s2 = computed(() => step('write'))
const s3 = computed(() => step('summary'))
const s4 = computed(() => step('publish'))
const w = computed(() => s2.value)
const busy = computed(() => running.value)
const s2done = computed(() => s2.value?.done)
const maxEnd = computed(() => Math.min((pipe.value?.chapter_count || 1), ((pipe.value?.next_chapter || 1) + 19)))
const batchCount = computed(() => Math.max(1, (batchEnd.value || pipe.value?.next_chapter || 1) - (pipe.value?.next_chapter || 1) + 1))
const stageHint = computed(() => ({
  outline: '第一步：先生成全书大纲',
  titles: '第二步：从大纲提取章名',
  fill_gaps: '有缺章，建议先补齐再续写',
  volume_summary: '一卷已完整：先做卷末总结再继续',
  write: '第三步：逐章写作',
  publish: '全部完成：可以发布 🎉',
}[pipe.value?.stage] || ''))

function step(key) { return pipe.value?.steps?.find(s => s.key === key) }
function cardClass(i) {
  if (!pipe.value) return {}
  const order = ['outline', 'titles', 'write', 'summary', 'publish']
  const current = pipe.value.stage === 'fill_gaps' ? 'write' : pipe.value.stage
  const idx = order.indexOf(current)
  const cur = order[i]
  const st = step(cur)
  return {
    active: i === idx,
    locked: !st?.available && i > idx && !st?.done,
  }
}
function isCurrentContext(name, seq) {
  return name === novelName.value && seq === contextSeq
}
function clearTaskTimers() {
  clearTimeout(reconnectTimer)
  clearTimeout(statusPollTimer)
  reconnectTimer = null
  statusPollTimer = null
}
function stopTaskTracking() {
  taskSessionSeq++
  clearTaskTimers()
  es?.close()
  es = null
}

async function loadPipeline(name = novelName.value, seq = contextSeq) {
  if (!name) { pipe.value = null; return }
  const requestSeq = ++pipelineRequestSeq
  pipeLoading.value = true
  try {
    const result = await api.pipeline(name)
    if (requestSeq !== pipelineRequestSeq || !isCurrentContext(name, seq)) return
    pipe.value = result
    if (batchEnd.value == null) syncBatchEnd()
  } catch (e) {
    if (requestSeq === pipelineRequestSeq && isCurrentContext(name, seq)) error.value = e.response?.data?.detail || '流水线状态加载失败'
  } finally {
    if (requestSeq === pipelineRequestSeq && isCurrentContext(name, seq)) pipeLoading.value = false
  }
}
function syncBatchEnd() {
  const next = pipe.value?.next_chapter || 1
  batchEnd.value = Math.min(next + 4, maxEnd.value)
}

async function refresh(name = novelName.value, seq = contextSeq) {
  await Promise.all([loadPipeline(name, seq), refreshHistory(name, seq, true)])
}
async function refreshHistory(name = novelName.value, seq = contextSeq, adopt = true) {
  if (!name) { history.value = []; return [] }
  const requestSeq = ++historyRequestSeq
  historyLoading.value = true
  try {
    const tasks = await api.tasks(name)
    if (requestSeq !== historyRequestSeq || !isCurrentContext(name, seq)) return []
    history.value = tasks
    const active = tasks.find(task => task.status === 'running')
    if (adopt && active) adoptTask(active, name, seq)
    return tasks
  } catch (e) {
    if (requestSeq === historyRequestSeq && isCurrentContext(name, seq)) error.value = e.response?.data?.detail || '任务历史加载失败'
    return []
  } finally {
    if (requestSeq === historyRequestSeq && isCurrentContext(name, seq)) historyLoading.value = false
  }
}

async function run(action, body) {
  if (running.value) return ElMessage.warning('已有任务运行中')
  const name = novelName.value
  const seq = contextSeq
  try {
    const res = await api.runTask(name, action, { prompt: '', ...body })
    if (!isCurrentContext(name, seq)) return
    startStream(res.task_id, { action, steps: res.steps || 1, done_steps: 0 }, name, seq)
  } catch (e) {
    if (isCurrentContext(name, seq)) ElMessage.error(e.response?.data?.detail || '任务启动失败')
  }
}
function runNext() {
  run('generate', { chapter: pipe.value.next_chapter, prompt: genPrompt.value })
}
function runBatch() {
  const start = pipe.value.next_chapter
  if (batchEnd.value <= start) return runNext()
  run('generate', { chapter: start, chapter_end: batchEnd.value, prompt: genPrompt.value })
}
function adoptTask(task, name, seq) {
  if (!isCurrentContext(name, seq)) return
  stepInfo.value = { total: task.steps || 1, done: task.done_steps || 0 }
  taskLabel.value = taskLabels[task.action] || task.action
  const tracking = es || reconnectTimer || statusPollTimer
  if (running.value && currentTaskId.value === task.id && tracking) return
  startStream(task.id, task, name, seq)
}
function startStream(id, task, name, seq) {
  stopTaskTracking()
  const sessionSeq = taskSessionSeq
  currentTaskId.value = id
  running.value = true
  cancelling.value = false
  taskStatus.value = ''
  taskLabel.value = taskLabels[task?.action] || task?.action || id
  stepInfo.value = { total: task?.steps || 1, done: task?.done_steps || 0 }
  logText.value = ''
  reconnectAttempts = 0
  statusPollAttempts = 0
  connectStream(id, name, seq, sessionSeq)
}
function connectStream(id, name, seq, sessionSeq) {
  if (sessionSeq !== taskSessionSeq || !isCurrentContext(name, seq) || id !== currentTaskId.value) return
  clearTimeout(reconnectTimer)
  reconnectTimer = null
  let replayText = ''
  let replayStarted = false
  const source = taskEventSource(id)
  es = source
  source.onmessage = event => {
    if (source !== es || sessionSeq !== taskSessionSeq || !isCurrentContext(name, seq) || id !== currentTaskId.value) return
    const data = JSON.parse(event.data)
    if (data.startsWith('__TASK_END__')) {
      finishTask(data.split(' ')[1], id, name, seq, sessionSeq)
      return
    }
    replayText += data
    logText.value = replayText
    replayStarted = true
    if (data.startsWith('━━')) stepInfo.value.done = parseInt((data.match(/步骤 (\d+)\//) || [])[1] || '0', 10)
    nextTick(() => { if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight })
  }
  source.onerror = () => {
    if (source !== es || sessionSeq !== taskSessionSeq || !isCurrentContext(name, seq)) return
    source.close()
    es = null
    if (!replayStarted) replayText = logText.value
    inspectTask(id, name, seq, sessionSeq)
  }
}
async function inspectTask(id, name, seq, sessionSeq) {
  if (sessionSeq !== taskSessionSeq || !isCurrentContext(name, seq)) return
  let tasks
  try {
    tasks = await api.tasks(name)
  } catch {
    scheduleStatusPoll(id, name, seq, sessionSeq)
    return
  }
  if (sessionSeq !== taskSessionSeq || !isCurrentContext(name, seq)) return
  history.value = tasks
  const task = tasks.find(item => item.id === id)
  if (!task) {
    running.value = false
    taskStatus.value = 'error'
    error.value = '任务状态不可用，实时日志已停止'
    return
  }
  stepInfo.value = { total: task.steps || 1, done: task.done_steps || 0 }
  if (terminalStatuses.has(task.status)) {
    finishTask(task.status, id, name, seq, sessionSeq)
    return
  }
  if (reconnectAttempts < maxReconnectAttempts) {
    reconnectAttempts++
    reconnectTimer = window.setTimeout(() => connectStream(id, name, seq, sessionSeq), reconnectAttempts * 1000)
  } else {
    scheduleStatusPoll(id, name, seq, sessionSeq)
  }
}
function scheduleStatusPoll(id, name, seq, sessionSeq) {
  if (sessionSeq !== taskSessionSeq || !isCurrentContext(name, seq)) return
  if (statusPollAttempts >= maxStatusPollAttempts) {
    error.value = '实时日志连接中断；任务仍可能在后台运行，请稍后点击刷新重新接管'
    return
  }
  statusPollAttempts++
  statusPollTimer = window.setTimeout(() => {
    statusPollTimer = null
    inspectTask(id, name, seq, sessionSeq)
  }, 3000)
}
function finishTask(status, id, name, seq, sessionSeq) {
  if (sessionSeq !== taskSessionSeq || !isCurrentContext(name, seq) || id !== currentTaskId.value) return
  stopTaskTracking()
  taskStatus.value = status
  running.value = false
  refresh(name, seq)
  store.reload(name).catch(() => {})
}
async function cancelTask(id) {
  if (!id || cancelling.value) return
  const name = novelName.value
  const seq = contextSeq
  cancelling.value = true
  try {
    const result = await api.cancelTask(id)
    if (!isCurrentContext(name, seq)) return
    if (id === currentTaskId.value) {
      stopTaskTracking()
      taskStatus.value = result.status
      running.value = false
    }
    ElMessage.success(result.cancelled ? '任务已取消' : `任务已是 ${result.status}`)
    await refresh(name, seq)
  } catch (e) {
    if (isCurrentContext(name, seq)) ElMessage.error(e.response?.data?.detail || '取消失败')
  } finally {
    if (isCurrentContext(name, seq)) cancelling.value = false
  }
}
function cancelCurrent() { return cancelTask(currentTaskId.value) }
function clearLog() { logText.value = '' }
function goto(view) { router.push({ name: view, params: { name: novelName.value } }) }

async function refreshAll() {
  const name = novelName.value
  const seq = contextSeq
  await store.reload(name)
  if (isCurrentContext(name, seq)) await refresh(name, seq)
}

watch(novelName, name => {
  contextSeq++
  const seq = contextSeq
  stopTaskTracking()
  pipelineRequestSeq++
  historyRequestSeq++
  running.value = false
  cancelling.value = false
  currentTaskId.value = ''
  taskStatus.value = ''
  taskLabel.value = ''
  stepInfo.value = { total: 1, done: 0 }
  logText.value = ''
  history.value = []
  pipe.value = null
  batchEnd.value = null
  error.value = ''
  refresh(name, seq)
}, { immediate: true })
onMounted(() => { poll = setInterval(() => { if (!running.value && document.visibilityState === 'visible') loadPipeline() }, 30000) })
onBeforeUnmount(() => {
  contextSeq++
  stopTaskTracking()
  if (poll) clearInterval(poll)
})
</script>

<style scoped>
.pipeline { display: grid; gap: 12px; margin-top: 4px; }
.step-card { padding: 16px 18px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); opacity: .72; transition: box-shadow .2s, border-color .2s, opacity .2s; }
.step-card.active { border-color: var(--primary); opacity: 1; box-shadow: 0 2px 14px rgba(24, 80, 69, .09); }
.step-card.locked { opacity: .48; }
.step-card.writing { opacity: 1; }
.step-head { display: flex; align-items: center; gap: 12px; }
.step-no { display: grid; place-items: center; width: 26px; height: 26px; flex: none; background: var(--primary-soft); color: var(--primary); border-radius: 8px; font-weight: 700; font-size: 14px; }
.step-head strong { font-size: 15px; margin-right: 6px; }
.step-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 12px; padding-left: 38px; }
.batch { display: inline-flex; align-items: center; gap: 6px; }
.vol-progress { display: flex; align-items: center; gap: 14px; padding-left: 38px; margin-top: 10px; }
.gap-alert { margin: 10px 0 0 38px; }
.tip { padding-left: 38px; margin-top: 6px; font-size: 12px; }
.revise-row { border-top: 1px dashed var(--border-light); padding-top: 12px; margin-top: 12px; }
.log-alert { margin-bottom: 12px; }
.log-placeholder { color: #83918e; }
@media (max-width: 760px) {
  .step-actions, .vol-progress, .gap-alert, .tip { padding-left: 0; }
}
</style>
