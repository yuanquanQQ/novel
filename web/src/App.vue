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
        <el-button class="create-side-button" plain @click="openCreate"><el-icon><Plus /></el-icon>新建小说</el-button>
      </div>

      <el-menu :default-active="$route.name" router>
        <el-menu-item index="dashboard" :route="{ name: 'dashboard' }"><el-icon><DataBoard /></el-icon><span>总览</span></el-menu-item>
        <template v-if="novelStore.current">
          <el-menu-item index="outline" :route="novelRoute('outline')"><el-icon><Notebook /></el-icon><span>大纲与章名</span></el-menu-item>
          <el-menu-item index="chapters" :route="novelRoute('chapters')"><el-icon><Document /></el-icon><span>章节</span></el-menu-item>
          <el-menu-item index="console" :route="novelRoute('console')"><el-icon><VideoPlay /></el-icon><span>生成控制台</span></el-menu-item>
          <el-menu-item index="bible" :route="novelRoute('bible')"><el-icon><Collection /></el-icon><span>知识库</span></el-menu-item>
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

  <el-dialog v-model="createVisible" title="新建小说" width="min(560px, calc(100vw - 32px))" destroy-on-close>
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
import { ElMessage } from 'element-plus'
import { useNovelStore } from './stores/novel'
import { api } from './api'

const novelStore = useNovelStore()
const router = useRouter()
const createVisible = ref(false)
const creating = ref(false)
const createFormRef = ref(null)
const form = reactive({ id: '', title: '', chapter_count: 200, words_per_chapter: 3000, genre: '', description: '' })
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
  createVisible.value = true
}

function onNovelChange(name) {
  novelStore.setNovel(name)
  const route = router.currentRoute.value
  if (route.meta?.requiresNovel !== false && route.params.name) router.replace({ name: route.name, params: { ...route.params, name } })
  else router.replace({ name: 'dashboard' })
}

async function submitCreate() {
  if (!createFormRef.value || creating.value) return
  try {
    await createFormRef.value.validate()
    creating.value = true
    const created = await api.createNovel({ ...form })
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
.create-side-button { width: 100%; margin-top: 8px; }
.side :deep(.el-menu) { flex: 1; background: transparent; border-right: 0; padding: 4px 10px; }
.side :deep(.el-menu-item) { height: 44px; margin: 3px 0; border-radius: 9px; color: #52606d; }
.side :deep(.el-menu-item:hover) { background: #eef2f4; }
.side :deep(.el-menu-item.is-active) { color: var(--primary); background: var(--primary-soft); font-weight: 600; }
.side-footer { padding: 16px 18px; color: #a0a9b2; font-size: 11px; border-top: 1px solid var(--border-light); }
.workspace { min-width: 0; padding: 0; overflow-y: auto; background: var(--bg); }
.app-alert { margin: 16px 24px 0; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.form-grid :deep(.el-input-number) { width: 100%; }
.field-tip { margin-top: 5px; color: var(--muted); font-size: 12px; line-height: 1.4; }
@media (max-width: 760px) {
  .app-shell { display: block; }
  .side { width: 100% !important; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }
  .brand { padding: 12px 16px 8px; }
  .brand-mark { width: 32px; height: 32px; }
  .novel-picker { display: grid; grid-template-columns: 1fr auto; gap: 8px; padding: 4px 12px 10px; }
  .novel-picker .side-label { grid-column: 1 / -1; margin-bottom: 0; }
  .create-side-button { width: auto; margin-top: 0; }
  .side :deep(.el-menu) { display: flex; overflow-x: auto; padding: 4px 8px 8px; }
  .side :deep(.el-menu-item) { flex: 0 0 auto; padding: 0 13px; }
  .side-footer { display: none; }
  .form-grid { grid-template-columns: 1fr; }
}
</style>
