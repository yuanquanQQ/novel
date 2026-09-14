<template>
  <div class="page">
    <header class="page-header"><div><div class="eyebrow">STORY PLAN</div><h1>大纲与章名</h1><p>{{ store.novel?.title || novelName }} 的全书结构与章节索引</p></div><el-button :loading="loading" @click="load"><el-icon><Refresh /></el-icon>刷新</el-button></header>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="section-gap" />
    <div v-if="!novelName" class="empty-panel"><el-empty description="请先选择小说" /></div>
    <div v-else class="content-card" v-loading="loading">
      <el-tabs v-model="tab" class="clean-tabs">
        <el-tab-pane label="全书大纲" name="outline">
          <div class="section-toolbar"><div><h3>outline.md</h3><span>可直接编辑并保存全书大纲</span></div><div class="toolbar-group"><el-button @click="editing = !editing"><el-icon><component :is="editing ? 'View' : 'EditPen'" /></el-icon>{{ editing ? '预览' : '编辑' }}</el-button><el-button type="primary" :loading="saving" :disabled="!editing" @click="saveOutline"><el-icon><Check /></el-icon>保存</el-button></div></div>
          <el-input v-if="editing" v-model="outline" type="textarea" :autosize="{ minRows: 24 }" class="code-editor" />
          <div v-else-if="outline" class="document-view prose">{{ outline }}</div>
          <el-empty v-else description="大纲尚未生成" />
        </el-tab-pane>
        <el-tab-pane label="章名库" name="titles">
          <div v-if="titleVolumes.length" class="volume-cards">
            <section v-for="volume in titleVolumes" :key="volume.key" class="volume-card">
              <div class="volume-heading"><h3>{{ volume.name }}</h3><span>第 {{ volume.lo }}–{{ volume.hi }} 章</span></div>
              <el-table :data="volume.rows" max-height="360">
                <el-table-column prop="num" label="章" width="68" />
                <el-table-column label="章名" min-width="220"><template #default="{ row }"><el-input v-if="row.editing" v-model="row.title" size="small" @keyup.enter="saveTitle(row)" /><span v-else class="editable-title" @dblclick="row.editing = true">{{ row.title }}</span></template></el-table-column>
                <el-table-column label="状态" width="92"><template #default="{ row }"><el-tag v-if="row.done" type="success" effect="plain">已写</el-tag><el-tag v-else-if="row.auto" type="info" effect="plain">默认</el-tag><el-tag v-else effect="plain">待写</el-tag></template></el-table-column>
                <el-table-column label="操作" width="86"><template #default="{ row }"><el-button v-if="row.editing" link type="primary" @click="saveTitle(row)">保存</el-button><el-button v-else link type="primary" @click="row.editing = true">编辑</el-button></template></el-table-column>
              </el-table>
            </section>
          </div>
          <el-empty v-else description="章名库为空" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '../stores/novel'
import { api } from '../api'

const store = useNovelStore(); const route = useRoute()
const novelName = computed(() => route.params.name || store.current || '')
const tab = ref('outline'); const outline = ref(''); const editing = ref(false); const titles = ref({ volumes: {} }); const doneSet = ref(new Set())
const loading = ref(false); const saving = ref(false); const error = ref(''); let seq = 0
const titleVolumes = computed(() => Object.entries(titles.value.volumes || {}).map(([key, volume]) => ({ key, name: volume.name, lo: volume.range?.[0], hi: volume.range?.[1], rows: Object.entries(volume.chapters || {}).map(([num, title]) => ({ num: Number(num), title, editing: false, auto: /^第\d+章$/.test(title), done: doneSet.value.has(Number(num)) })).sort((a, b) => a.num - b.num) })))

async function load() {
  const name = novelName.value; const request = ++seq
  outline.value = ''; titles.value = { volumes: {} }; doneSet.value = new Set(); error.value = ''; editing.value = false
  if (!name) return
  loading.value = true
  try { const [o, t, status] = await Promise.all([api.outline(name), api.titles(name), api.status(name)]); if (request === seq && name === novelName.value) { outline.value = typeof o === 'string' ? o : ''; titles.value = t || { volumes: {} }; doneSet.value = new Set((status.chapter_log || []).map(row => row.chapter)) } }
  catch (e) { if (request === seq) error.value = e.response?.data?.detail || '大纲数据加载失败' }
  finally { if (request === seq) loading.value = false }
}
async function saveOutline() { if (!novelName.value) return; saving.value = true; try { await api.saveOutline(novelName.value, outline.value); editing.value = false; ElMessage.success('大纲已保存') } catch (e) { ElMessage.error(e.response?.data?.detail || '保存失败') } finally { saving.value = false } }
async function saveTitle(row) { try { await api.saveTitle(novelName.value, row.num, row.title); row.editing = false; ElMessage.success('章名已更新') } catch (e) { ElMessage.error(e.response?.data?.detail || '更新失败') } }
watch(novelName, load, { immediate: true })
</script>

<style scoped>
.section-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.section-toolbar h3 { margin: 0 0 3px; font-size: 15px; }.section-toolbar span,.volume-heading span { color: var(--muted); font-size: 12px; }.toolbar-group { display: flex; gap: 8px; }
.document-view { min-height: 420px; padding: 22px; background: #fbfcfc; border: 1px solid var(--border-light); border-radius: var(--radius-sm); }
.volume-cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }.volume-card { border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }.volume-heading { padding: 14px 16px 10px; }.volume-heading h3 { margin: 0 0 3px; font-size: 15px; }.editable-title { cursor: text; }
.code-editor :deep(textarea) { font-family: var(--mono); line-height: 1.7; }
@media (max-width: 900px) { .volume-cards { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .section-toolbar { align-items: stretch; flex-direction: column; } }
</style>
