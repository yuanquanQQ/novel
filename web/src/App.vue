<template>
  <el-container class="app-shell">
    <el-aside class="side" width="244px">
      <div class="brand">
        <span class="brand-mark"><el-icon><Reading /></el-icon></span>
        <div><strong>创作控制台</strong><small>Novel Workspace</small></div>
      </div>

      <div class="novel-picker">
        <span class="side-label">当前作品</span>
        <el-select v-model="novelStore.current" placeholder="暂无小说" :disabled="!novelStore.hasNovels" @change="onNovelChange">
          <el-option v-for="n in novelStore.novels" :key="n.id" :label="`${n.title} · ${n.chapters_written}/${n.chapter_count || '?'}`" :value="n.id" />
        </el-select>
        <div v-if="novelStore.current" class="novel-actions">
          <el-button plain :loading="exporting" :disabled="deleting" @click="exportCurrentNovel">
            <el-icon v-if="!exporting"><Download /></el-icon>导出整本
          </el-button>
          <el-button plain type="danger" :loading="deleting" :disabled="exporting" @click="deleteCurrentNovel">
            <el-icon v-if="!deleting"><Delete /></el-icon>删除小说
          </el-button>
        </div>
        <el-button class="create-side-button" plain @click="openCreate"><el-icon><Plus /></el-icon>新建小说</el-button>
      </div>

      <el-menu :default-active="$route.name" router>
        <el-menu-item index="dashboard" :route="{ name: 'dashboard' }"><el-icon><DataBoard /></el-icon><span>总览</span></el-menu-item>
        <template v-if="novelStore.current">
          <el-menu-item index="outline" :route="novelRoute('outline')"><el-icon><Notebook /></el-icon><span>大纲与章名</span></el-menu-item>
          <el-menu-item index="chapters" :route="novelRoute('chapters')"><el-icon><Document /></el-icon><span>章节</span></el-menu-item>
          <el-menu-item index="console" :route="novelRoute('console')"><el-icon><VideoPlay /></el-icon><span>生成控制台</span></el-menu-item>
          <el-menu-item index="bible" :route="novelRoute('bible')"><el-icon><Collection /></el-icon><span>知识库</span></el-menu-item>
          <el-menu-item index="model" :route="novelRoute('model')"><el-icon><Cpu /></el-icon><span>模型配置</span></el-menu-item>
        </template>
        <el-menu-item index="style" :route="{ name: 'style' }"><el-icon><MagicStick /></el-icon><span>风格工坊</span></el-menu-item>
      </el-menu>
      <div class="side-footer">轻量小说工作台</div>
    </el-aside>

    <el-main class="workspace" v-loading="novelStore.loading">
      <el-alert v-if="novelStore.error" class="app-alert" type="error" :title="novelStore.error" :closable="false" show-icon />
      <router-view v-if="novelStore.loaded" :key="`${$route.name}:${$route.params.name || novelStore.current}`" @create-novel="openCreate" />
    </el-main>
  </el-container>

  <el-dialog v-model="createVisible" title="新建小说" width="min(920px, calc(100vw - 32px))" destroy-on-close>
    <section class="theme-generator">
      <div class="theme-heading">
        <div>
          <strong>AI 主题构思</strong>
          <span>生成三个建议，选中后仅填入表单</span>
        </div>
        <el-button type="primary" plain :loading="themeLoading" :disabled="!themeRequest.direction" @click="generateThemes">
          <el-icon v-if="!themeLoading"><MagicStick /></el-icon>生成方案
        </el-button>
      </div>
      <div class="direction-picker">
        <span class="direction-label">先选创作方向（必选）</span>
        <button v-for="direction in THEME_DIRECTIONS" :key="direction" type="button" class="direction-card" :class="{ selected: themeRequest.direction === direction }" @click="themeRequest.direction = direction">
          {{ direction }}
        </button>
      </div>
      <div class="theme-inputs">
        <el-input v-model="themeRequest.inspiration" maxlength="1000" show-word-limit placeholder="可选：一句灵感、人物或场景" />
        <el-input v-model="themeRequest.genre" maxlength="100" placeholder="可选：题材偏好" />
      </div>
      <el-alert v-if="themeError" class="theme-error" type="error" :title="themeError" :closable="false" show-icon />
      <div v-if="themeOptions.length" class="theme-cards">
        <button v-for="option in themeOptions" :key="option.id" type="button" class="theme-card" @click="applyTheme(option)">
          <span class="theme-card-title">{{ option.title }}</span>
          <span class="theme-card-meta">{{ option.genre }} · {{ option.chapter_count }} 章 · 每章 {{ option.words_per_chapter }} 字</span>
          <span class="theme-card-copy">{{ option.description }}</span>
          <span class="theme-card-line"><b>主题</b>{{ option.theme }}</span>
          <span class="theme-card-line"><b>冲突</b>{{ option.conflict }}</span>
          <span class="theme-card-action"><el-icon><EditPen /></el-icon>填入下方表单</span>
        </button>
      </div>
    </section>
    <el-divider />
    <el-form ref="createFormRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submitCreate">
      <div class="form-grid">
        <el-form-item label="小说 ID" prop="id">
          <el-input v-model="form.id" placeholder="如：my-new-story" maxlength="64" />
          <div class="field-tip">仅小写字母、数字和连字符，创建后不可修改</div>
        </el-form-item>
        <el-form-item label="书名" prop="title"><el-input v-model="form.title" placeholder="输入小说名称" /></el-form-item>
        <el-form-item label="总章节数" prop="chapter_count"><el-input-number v-model="form.chapter_count" :min="1" :max="100000" controls-position="right" /></el-form-item>
        <el-form-item label="每章目标字数" prop="words_per_chapter"><el-input-number v-model="form.words_per_chapter" :min="1" :max="1000000" :step="500" controls-position="right" /></el-form-item>
      </div>
      <el-form-item label="类型" prop="genre"><el-input v-model="form.genre" placeholder="如：都市悬疑、奇幻冒险" /></el-form-item>
      <el-form-item label="故事简介" prop="description"><el-input v-model="form.description" type="textarea" :rows="4" placeholder="简要描述故事背景、人物与核心冲突" /></el-form-item>

      <el-collapse v-model="createPanels" class="model-collapse">
        <el-collapse-item name="model">
          <template #title><span class="collapse-title"><el-icon><Cpu /></el-icon> 模型配置（可选）<span class="muted">　不填则用系统环境变量 / 默认 DeepSeek，创建后可在「模型配置」页修改</span></span></template>
          <div class="model-grid">
            <el-form-item label="API Key"><el-input v-model="modelForm.api_key" type="password" show-password placeholder="sk-…（仅存本书 .env，不进 git）" /></el-form-item>
            <el-form-item label="Base URL"><el-input v-model="modelForm.base_url" placeholder="https://api.deepseek.com/v1" /></el-form-item>
            <el-form-item label="创作/对话模型"><el-input v-model="modelForm.chat_model" placeholder="deepseek-chat" /></el-form-item>
            <el-form-item label="推理/审阅模型"><el-input v-model="modelForm.reasoner_model" placeholder="deepseek-reasoner" /></el-form-item>
          </div>
          <details class="adv-models">
            <summary>逐 Agent 精确覆盖（一般不用）</summary>
            <div class="adv-grid">
              <el-input v-for="role in AGENT_ROLES" :key="role.env" v-model="modelForm.models[role.env]" size="small" :placeholder="`${role.label} · ${role.default}`"><template #prepend>{{ role.env }}</template></el-input>
            </div>
          </details>
        </el-collapse-item>
      </el-collapse>
    </el-form>
    <template #footer>
      <el-button @click="createVisible = false">取消</el-button>
      <el-button type="primary" :loading="creating" @click="submitCreate">创建并进入</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useNovelStore } from './stores/novel'
import { api } from './api'

const novelStore = useNovelStore()
const router = useRouter()
const createVisible = ref(false)
const creating = ref(false)
const exporting = ref(false)
const deleting = ref(false)
const themeLoading = ref(false)
const themeError = ref('')
const themeOptions = ref([])
const THEME_DIRECTIONS = ['悬疑推理', '都市情感', '科幻未来', '奇幻冒险', '历史权谋', '成长热血', '惊悚生存', '自由创作']
const themeRequest = reactive({ inspiration: '', genre: '', direction: '' })
const createFormRef = ref(null)
const form = reactive({ id: '', title: '', chapter_count: 200, words_per_chapter: 3000, genre: '', description: '' })
const createPanels = ref([])
const AGENT_ROLES = [
  { env: 'PLANNER_MODEL', label: '规划', default: 'deepseek-reasoner' },
  { env: 'RESEARCHER_MODEL', label: '检索', default: 'deepseek-reasoner' },
  { env: 'WRITER_MODEL', label: '写作', default: 'deepseek-chat' },
  { env: 'IMMEDIATE_REVIEWER_MODEL', label: '即审', default: 'deepseek-chat' },
  { env: 'HEAVY_REVIEWER_MODEL', label: '重审', default: 'deepseek-reasoner' },
  { env: 'KEEPER_MODEL', label: '记忆', default: 'deepseek-chat' },
  { env: 'ARCHIVIST_MODEL', label: '归档', default: 'deepseek-chat' },
  { env: 'FORESHADOWING_STEWARD_MODEL', label: '伏笔', default: 'deepseek-reasoner' },
  { env: 'READER_PROXY_MODEL', label: '读者', default: 'deepseek-chat' },
  { env: 'MARKETER_MODEL', label: '宣传', default: 'deepseek-chat' },
]
const emptyModelForm = () => ({ api_key: '', base_url: '', chat_model: '', reasoner_model: '', models: {} })
const modelForm = reactive(emptyModelForm())
const rules = {
  id: [
    { required: true, message: '请输入小说 ID', trigger: 'blur' },
    { pattern: /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/, message: '仅允许小写字母、数字和连字符', trigger: 'blur' },
  ],
  title: [{ required: true, whitespace: true, message: '请输入书名', trigger: 'blur' }],
  chapter_count: [{ required: true, message: '请输入总章节数' }],
  words_per_chapter: [{ required: true, message: '请输入每章目标字数' }],
}

const currentNovel = computed(() => novelStore.current)
const novelRoute = (name) => ({ name, params: { name: currentNovel.value } })

onMounted(async () => {
  try {
    await novelStore.load()
    const route = router.currentRoute.value
    if (route.params.name && !novelStore.novels.some(item => item.id === route.params.name)) {
      await router.replace({ name: 'dashboard' })
    }
  } catch {
    return
  }
})

function openCreate() {
  Object.assign(form, { id: '', title: '', chapter_count: 200, words_per_chapter: 3000, genre: '', description: '' })
  Object.assign(modelForm, emptyModelForm())
  createPanels.value = []
  Object.assign(themeRequest, { inspiration: '', genre: '', direction: '' })
  themeOptions.value = []
  themeError.value = ''
  createVisible.value = true
}

async function generateThemes() {
  if (themeLoading.value) return
  if (!themeRequest.direction) {
    themeError.value = '请先选择创作方向'
    return
  }
  themeLoading.value = true
  themeError.value = ''
  try {
    const result = await api.generateNovelThemes({ ...themeRequest })
    themeOptions.value = result.options
  } catch (error) {
    themeError.value = error.response?.data?.detail || 'AI 构思失败，请稍后重试'
  } finally {
    themeLoading.value = false
  }
}

function applyTheme(option) {
  Object.assign(form, {
    id: option.id,
    title: option.title,
    chapter_count: option.chapter_count,
    words_per_chapter: option.words_per_chapter,
    genre: option.genre,
    description: `${option.description}\n\n主题：${option.theme}\n核心冲突：${option.conflict}`,
  })
  createFormRef.value?.clearValidate()
}

function onNovelChange(name) {
  novelStore.setNovel(name)
  const route = router.currentRoute.value
  if (route.meta?.requiresNovel !== false && route.params.name) router.replace({ name: route.name, params: { ...route.params, name } })
  else router.replace({ name: 'dashboard' })
}

async function exportCurrentNovel() {
  const id = novelStore.current
  if (!id || exporting.value || deleting.value) return
  exporting.value = true
  try {
    const blob = await api.exportNovel(id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${id}.zip`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    ElMessage.success('整本小说已导出')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '导出失败，请稍后重试')
  } finally {
    exporting.value = false
  }
}

async function deleteCurrentNovel() {
  const id = novelStore.current
  if (!id || deleting.value || exporting.value) return
  try {
    await ElMessageBox.confirm(
      `删除后将无法恢复，确定删除小说“${id}”吗？`,
      '删除小说',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  deleting.value = true
  try {
    await api.deleteNovel(id)
    novelStore.reset()
    await novelStore.reload('')
    await router.push({ name: 'dashboard' })
    ElMessage.success('小说已删除')
  } catch (error) {
    const detail = error.response?.data?.detail
    ElMessage.error(detail || '删除失败，请稍后重试')
  } finally {
    deleting.value = false
  }
}

async function submitCreate() {
  if (!createFormRef.value || creating.value) return
  try {
    await createFormRef.value.validate()
    creating.value = true
    const quick = {}
    if (modelForm.api_key) quick.api_key = modelForm.api_key
    if (modelForm.base_url) quick.base_url = modelForm.base_url
    if (modelForm.chat_model) quick.chat_model = modelForm.chat_model
    if (modelForm.reasoner_model) quick.reasoner_model = modelForm.reasoner_model
    const models = {}
    for (const [k, v] of Object.entries(modelForm.models)) if (v) models[k] = v
    const model = (Object.keys(quick).length || Object.keys(models).length)
      ? { quick: Object.keys(quick).length ? quick : undefined, models: Object.keys(models).length ? models : undefined }
      : undefined
    const created = await api.createNovel({ ...form, model })
    await novelStore.reload(created.id)
    createVisible.value = false
    await router.push({ name: 'dashboard' })
    ElMessage.success(`《${created.title}》已创建`)
  } catch (error) {
    if (error?.response) ElMessage.error(error.response.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.app-shell { min-height: 100vh; }
.side { display: flex; flex-direction: column; background: #f8fafc; border-right: 1px solid var(--border); overflow: hidden; }
.brand { display: flex; align-items: center; gap: 11px; padding: 22px 18px 18px; color: var(--text); }
.brand-mark { display: grid; place-items: center; width: 36px; height: 36px; color: var(--primary); background: var(--primary-soft); border: 1px solid #dce7e4; border-radius: 10px; font-size: 19px; }
.brand strong, .brand small { display: block; }
.brand strong { font-size: 16px; letter-spacing: .02em; }
.brand small { margin-top: 2px; color: var(--muted); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; }
.novel-picker { padding: 4px 14px 14px; }
.side-label { display: block; margin: 0 2px 7px; color: var(--muted); font-size: 12px; }
.novel-actions { display: flex; gap: 8px; margin-top: 8px; }
.novel-actions .el-button { flex: 1; margin-left: 0; }
.create-side-button { width: 100%; margin-top: 8px; }
.side :deep(.el-menu) { flex: 1; background: transparent; border-right: 0; padding: 4px 10px; }
.side :deep(.el-menu-item) { height: 44px; margin: 3px 0; border-radius: 9px; color: #52606d; }
.side :deep(.el-menu-item:hover) { background: #eef2f4; }
.side :deep(.el-menu-item.is-active) { color: var(--primary); background: var(--primary-soft); font-weight: 600; }
.side-footer { padding: 16px 18px; color: #a0a9b2; font-size: 11px; border-top: 1px solid var(--border-light); }
.workspace { min-width: 0; padding: 0; overflow-y: auto; background: var(--bg); }
.app-alert { margin: 16px 24px 0; }
.theme-generator { padding: 2px 0; }
.theme-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.theme-heading strong, .theme-heading span { display: block; }
.theme-heading strong { color: var(--text); font-size: 15px; }
.theme-heading span { margin-top: 3px; color: var(--muted); font-size: 12px; }
.direction-picker { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 14px; }
.direction-label { width: 100%; color: var(--muted); font-size: 12px; }
.direction-card { padding: 7px 12px; color: #52606d; background: #fff; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; }
.direction-card:hover, .direction-card.selected { color: var(--primary); border-color: var(--primary); background: var(--primary-soft); }
.theme-inputs { display: grid; grid-template-columns: 2fr 1fr; gap: 10px; margin-top: 14px; }
.theme-error { margin-top: 12px; }
.theme-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.theme-card { display: flex; flex-direction: column; gap: 7px; min-width: 0; padding: 14px; color: var(--text); text-align: left; background: #fff; border: 1px solid var(--border); border-radius: 10px; cursor: pointer; transition: border-color .2s, box-shadow .2s; }
.theme-card:hover, .theme-card:focus-visible { border-color: var(--primary); box-shadow: 0 4px 14px rgba(24, 80, 69, .1); outline: none; }
.theme-card-title { font-size: 15px; font-weight: 650; }
.theme-card-meta { color: var(--primary); font-size: 11px; line-height: 1.5; }
.theme-card-copy, .theme-card-line { color: #52606d; font-size: 12px; line-height: 1.55; }
.theme-card-copy { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.theme-card-line b { margin-right: 5px; color: var(--text); }
.theme-card-action { display: flex; align-items: center; gap: 4px; margin-top: auto; padding-top: 3px; color: var(--primary); font-size: 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.form-grid :deep(.el-input-number) { width: 100%; }
.model-collapse { margin-top: 4px; border-top-color: var(--border-light); }
.model-collapse :deep(.el-collapse-item__header) { height: 44px; color: var(--text); font-weight: 600; }
.collapse-title { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; }
.model-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; margin-top: 10px; }
.adv-models { margin: 10px 0 18px; color: var(--muted); font-size: 13px; }
.adv-models summary { cursor: pointer; color: var(--primary); margin-bottom: 10px; }
.adv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.adv-grid :deep(.el-input-group__prepend) { background: var(--surface-soft); font-family: var(--mono); font-size: 11px; padding: 0 10px; }
.field-tip { margin-top: 5px; color: var(--muted); font-size: 12px; line-height: 1.4; }
@media (max-width: 760px) {
  .app-shell { display: block; }
  .side { width: 100% !important; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }
  .brand { padding: 12px 16px 8px; }
  .brand-mark { width: 32px; height: 32px; }
  .novel-picker { display: grid; grid-template-columns: 1fr auto; gap: 8px; padding: 4px 12px 10px; }
  .novel-picker .side-label { grid-column: 1 / -1; margin-bottom: 0; }
  .novel-actions { grid-column: 1 / -1; margin-top: 0; }
  .create-side-button { grid-column: 1 / -1; width: auto; margin-top: 0; }
  .side :deep(.el-menu) { display: flex; overflow-x: auto; padding: 4px 8px 8px; }
  .side :deep(.el-menu-item) { flex: 0 0 auto; padding: 0 13px; }
  .side-footer { display: none; }
  .theme-inputs, .theme-cards, .form-grid, .model-grid, .adv-grid { grid-template-columns: 1fr; }
  .theme-heading { align-items: flex-start; }
}
</style>
