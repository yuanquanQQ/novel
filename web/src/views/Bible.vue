<template>
  <div class="page">
    <header class="page-header">
      <div>
        <div class="eyebrow">KNOWLEDGE BASE</div>
        <h1>知识库</h1>
        <p>{{ store.novel?.title || novelName }} 的人物、叙事线索与运行记忆</p>
      </div>
      <div class="page-actions">
        <el-button :loading="loading" @click="loadAll"><el-icon><Refresh /></el-icon>刷新</el-button>
        <el-button type="primary" :loading="syncing" @click="syncKnowledge"><el-icon><Connection /></el-icon>同步原始文件</el-button>
      </div>
    </header>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="section-gap" />
    <div v-if="!novelName" class="empty-panel"><el-empty description="请先新建或选择一部小说" /></div>

    <div v-else class="content-card" v-loading="loading">
      <el-tabs v-model="tab" class="clean-tabs">
        <el-tab-pane label="人物" name="characters">
          <section class="tab-section">
            <div class="section-toolbar"><div><h3>人物档案</h3><span>{{ characters.length }} 位人物</span></div><el-button type="primary" plain @click="editCharacter()"><el-icon><Plus /></el-icon>添加人物</el-button></div>
            <el-table v-if="characters.length" :data="characters">
              <el-table-column prop="name" label="姓名" min-width="120" />
              <el-table-column prop="role" label="角色" min-width="130" />
              <el-table-column prop="voice_print" label="声纹" min-width="180" show-overflow-tooltip />
              <el-table-column prop="first_appearance_chapter" label="初登场" width="90" />
              <el-table-column label="近期状态" min-width="220">
                <template #default="{ row }"><div v-if="row.recent_states?.length" class="state-list"><span v-for="state in row.recent_states" :key="state.chapter">第 {{ state.chapter }} 章 · {{ shortState(state.state) }}</span></div><span v-else class="muted">暂无状态记录</span></template>
              </el-table-column>
              <el-table-column label="操作" width="82" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="editCharacter(row)">编辑</el-button></template></el-table-column>
            </el-table>
            <el-empty v-else description="尚未录入人物"><el-button type="primary" plain @click="editCharacter()">添加第一个人物</el-button></el-empty>
          </section>
        </el-tab-pane>

        <el-tab-pane label="线索" name="clues">
          <section class="tab-section">
            <div class="section-toolbar"><div><h3>线索记录</h3><span>{{ clues.length }} 条线索</span></div><el-button type="primary" plain @click="editClue()"><el-icon><Plus /></el-icon>添加线索</el-button></div>
            <el-table v-if="clues.length" :data="clues">
              <el-table-column prop="id" label="ID" min-width="110" />
              <el-table-column prop="name" label="名称" min-width="130" />
              <el-table-column prop="type" label="类型" width="110" />
              <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
              <el-table-column label="章节" width="160"><template #default="{ row }"><span class="mono muted">{{ row.introduced_chapter || '—' }} → {{ row.intended_reveal_chapter || '—' }}</span></template></el-table-column>
              <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.resolved ? 'success' : 'info'" effect="plain">{{ row.resolved ? '已解决' : '进行中' }}</el-tag></template></el-table-column>
              <el-table-column label="操作" width="82" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="editClue(row)">编辑</el-button></template></el-table-column>
            </el-table>
            <el-empty v-else description="尚未录入线索"><el-button type="primary" plain @click="editClue()">添加第一条线索</el-button></el-empty>
          </section>
        </el-tab-pane>

        <el-tab-pane label="伏笔" name="foreshadow">
          <section class="tab-section">
            <div class="section-toolbar responsive-toolbar">
              <div><h3>伏笔追踪</h3><span>以第 {{ currentCh }} 章为当前进度</span></div>
              <div class="toolbar-group"><el-input-number v-model="currentCh" :min="1" controls-position="right" @change="loadForeshadow" /><el-button type="primary" plain @click="editForeshadow()"><el-icon><Plus /></el-icon>添加伏笔</el-button></div>
            </div>
            <div v-if="fore.buckets?.overdue_to_payoff?.length || fore.buckets?.stale?.length" class="notice-stack">
              <el-alert v-if="fore.buckets.overdue_to_payoff?.length" type="warning" :closable="false" :title="`待回收：${fore.buckets.overdue_to_payoff.map(item => item.name).join('、')}`" />
              <el-alert v-if="fore.buckets.stale?.length" type="info" :closable="false" :title="`久未触碰：${fore.buckets.stale.map(item => item.name).join('、')}`" />
            </div>
            <el-table v-if="fore.rows.length" :data="fore.rows">
              <el-table-column prop="id" label="ID" min-width="110" />
              <el-table-column prop="name" label="名称" min-width="140" />
              <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'resolved' ? 'success' : row.status === 'active' ? 'warning' : 'info'" effect="plain">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
              <el-table-column label="埋设 / 触碰 / 回收" min-width="210"><template #default="{ row }"><span class="mono muted">{{ row.introduced_chapter || '—' }} / {{ row.hinted_chapters?.join(', ') || '—' }} / {{ row.intended_payoff_chapter || '—' }}</span></template></el-table-column>
              <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
              <el-table-column label="操作" width="82" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="editForeshadow(row)">编辑</el-button></template></el-table-column>
            </el-table>
            <el-empty v-else description="尚未录入伏笔"><el-button type="primary" plain @click="editForeshadow()">添加第一条伏笔</el-button></el-empty>
          </section>
        </el-tab-pane>

        <el-tab-pane label="母题" name="motifs">
          <section class="tab-section">
            <div class="section-toolbar"><div><h3>母题库</h3><span>{{ motifs.length }} 个叙事母题</span></div><el-button type="primary" plain @click="editMotif()"><el-icon><Plus /></el-icon>添加母题</el-button></div>
            <el-table v-if="motifs.length" :data="motifs">
              <el-table-column prop="id" label="ID" min-width="120" />
              <el-table-column prop="name" label="名称" min-width="140" />
              <el-table-column prop="description" label="描述" min-width="260" />
              <el-table-column label="使用章节" min-width="160"><template #default="{ row }"><span class="mono muted">{{ row.used_in_chapters?.join(', ') || '尚未使用' }}</span></template></el-table-column>
              <el-table-column label="操作" width="82" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="editMotif(row)">编辑</el-button></template></el-table-column>
            </el-table>
            <el-empty v-else description="尚未录入母题"><el-button type="primary" plain @click="editMotif()">添加第一个母题</el-button></el-empty>
          </section>
        </el-tab-pane>

        <el-tab-pane label="事实" name="facts">
          <section class="tab-section">
            <div class="section-toolbar responsive-toolbar"><div><h3>跨章事实</h3><span>用于保持情节与设定一致</span></div><div class="toolbar-group fact-search"><el-input v-model="factQ" clearable placeholder="输入关键词" @keyup.enter="loadFacts" /><el-input-number v-model="factBefore" :min="0" controls-position="right" /><el-button type="primary" @click="loadFacts"><el-icon><Search /></el-icon>检索</el-button></div></div>
            <el-table v-if="facts.length" :data="facts">
              <el-table-column prop="chapter" label="章节" width="80" />
              <el-table-column prop="kind" label="类型" width="110" />
              <el-table-column prop="subject" label="主体" min-width="130" />
              <el-table-column prop="content" label="事实内容" min-width="320" />
            </el-table>
            <el-empty v-else description="暂无匹配事实" />
          </section>
        </el-tab-pane>

        <el-tab-pane label="教训" name="lessons">
          <section class="tab-section">
            <div class="section-toolbar"><div><h3>创作教训</h3><span>最近 {{ lessons.length }} 条复盘记录</span></div></div>
            <el-table v-if="lessons.length" :data="lessons">
              <el-table-column prop="chapter" label="章节" width="80" />
              <el-table-column prop="issue" label="发现的问题" min-width="260" />
              <el-table-column prop="fix" label="处理方式" min-width="260" />
              <el-table-column prop="source" label="来源" width="110" />
            </el-table>
            <el-empty v-else description="暂无教训记录" />
          </section>
        </el-tab-pane>

        <el-tab-pane label="原始文件" name="files">
          <section class="tab-section">
            <div class="section-toolbar responsive-toolbar"><div><h3>原始 Bible 文件</h3><span>保存后会自动同步运行时知识库</span></div><div class="toolbar-group"><el-select v-model="bFile" @change="loadBFile"><el-option v-for="file in BIBLE_FILES" :key="file" :value="file" :label="file" /></el-select><el-button :loading="fileLoading" @click="loadBFile"><el-icon><Refresh /></el-icon>重载</el-button><el-button type="primary" :loading="fileSaving" @click="saveBFile"><el-icon><Check /></el-icon>保存</el-button></div></div>
            <el-alert v-if="fileError" type="error" :title="fileError" show-icon :closable="false" class="section-gap" />
            <el-input v-model="bContent" type="textarea" :autosize="{ minRows: 20 }" class="code-editor" :disabled="fileLoading" />
          </section>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>

  <el-dialog v-model="editor.visible" :title="editor.title" width="min(620px, calc(100vw - 32px))" destroy-on-close>
    <el-form label-position="top" @submit.prevent="saveEntity">
      <el-form-item label="ID / 姓名" required><el-input v-model="editor.id" :disabled="editor.lockId" placeholder="输入唯一 ID" /></el-form-item>
      <template v-if="editor.type === 'character'">
        <el-form-item label="角色定位"><el-input v-model="editor.data.role" /></el-form-item>
        <el-form-item label="人物声纹"><el-input v-model="editor.data.voice_print" /></el-form-item>
        <el-form-item label="初登场章节"><el-input-number v-model="editor.data.first_appearance_chapter" :min="1" controls-position="right" /></el-form-item>
        <el-form-item label="完整档案（JSON）"><el-input v-model="editor.json" type="textarea" :rows="8" class="code-editor" /></el-form-item>
        <el-form-item label="更新章节（可选）"><el-input-number v-model="editor.data.chapter" :min="1" controls-position="right" /></el-form-item>
      </template>
      <template v-else-if="editor.type === 'clue'">
        <div class="dialog-grid"><el-form-item label="名称"><el-input v-model="editor.data.name" /></el-form-item><el-form-item label="类型"><el-input v-model="editor.data.type" /></el-form-item></div>
        <el-form-item label="描述"><el-input v-model="editor.data.description" type="textarea" :rows="3" /></el-form-item>
        <div class="dialog-grid"><el-form-item label="引入章节"><el-input-number v-model="editor.data.introduced_chapter" :min="1" controls-position="right" /></el-form-item><el-form-item label="预定揭示章节"><el-input-number v-model="editor.data.intended_reveal_chapter" :min="1" controls-position="right" /></el-form-item></div>
        <el-form-item label="当前状态（JSON）"><el-input v-model="editor.json" type="textarea" :rows="5" class="code-editor" /></el-form-item>
        <el-form-item><el-checkbox v-model="editor.data.resolved">已解决</el-checkbox></el-form-item>
      </template>
      <template v-else-if="editor.type === 'foreshadow'">
        <div class="dialog-grid"><el-form-item label="名称"><el-input v-model="editor.data.name" /></el-form-item><el-form-item label="状态"><el-select v-model="editor.data.status"><el-option label="待激活" value="pending" /><el-option label="进行中" value="active" /><el-option label="已回收" value="resolved" /></el-select></el-form-item></div>
        <el-form-item label="描述"><el-input v-model="editor.data.description" type="textarea" :rows="3" /></el-form-item>
        <div class="dialog-grid"><el-form-item label="埋设章节"><el-input-number v-model="editor.data.introduced_chapter" :min="1" controls-position="right" /></el-form-item><el-form-item label="预定回收章节"><el-input-number v-model="editor.data.intended_payoff_chapter" :min="1" controls-position="right" /></el-form-item><el-form-item label="实际回收章节"><el-input-number v-model="editor.data.resolved_chapter" :min="1" controls-position="right" /></el-form-item></div>
        <el-form-item label="触碰章节（逗号分隔）"><el-input v-model="editor.hinted" placeholder="如：3, 8, 12" /></el-form-item>
      </template>
      <template v-else-if="editor.type === 'motif'">
        <el-form-item label="名称"><el-input v-model="editor.data.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="editor.data.description" type="textarea" :rows="4" /></el-form-item>
        <el-form-item label="使用章节（逗号分隔）"><el-input v-model="editor.hinted" /></el-form-item>
      </template>
    </el-form>
    <template #footer><el-button @click="editor.visible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveEntity">保存并重新加载</el-button></template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '../stores/novel'
import { api } from '../api'

const BIBLE_FILES = ['characters.json', 'clues.json', 'motif_bank.json', 'master_bible.md', 'lessons_learned.jsonl', 'chapter_titles.json']
const store = useNovelStore()
const route = useRoute()
const novelName = computed(() => route.params.name || store.current || '')
const tab = ref('characters')
const loading = ref(false)
const syncing = ref(false)
const saving = ref(false)
const error = ref('')
const characters = ref([])
const clues = ref([])
const motifs = ref([])
const fore = ref({ rows: [], buckets: {} })
const facts = ref([])
const lessons = ref([])
const currentCh = ref(1)
const factQ = ref('')
const factBefore = ref(0)
const bFile = ref('characters.json')
const bContent = ref('')
const fileLoading = ref(false)
const fileSaving = ref(false)
const fileError = ref('')
let requestSeq = 0

const editor = reactive({ visible: false, title: '', type: '', id: '', lockId: false, data: {}, json: '{}', hinted: '' })
const detail = (e, fallback) => e?.response?.data?.detail || fallback
const nullable = (value) => value || null
const parseChapters = (value) => value.split(/[,，\s]+/).filter(Boolean).map(Number).filter(n => Number.isInteger(n) && n > 0)
const statusLabel = (status) => ({ pending: '待激活', active: '进行中', resolved: '已回收' }[status] || status)
const shortState = (value) => { try { return JSON.stringify(JSON.parse(value)).slice(0, 80) } catch { return String(value || '').slice(0, 80) } }

function clearData() {
  characters.value = []; clues.value = []; motifs.value = []; fore.value = { rows: [], buckets: {} }; facts.value = []; lessons.value = []; bContent.value = ''; error.value = ''
}

async function loadAll() {
  const name = novelName.value
  if (!name) { clearData(); return }
  const seq = ++requestSeq
  loading.value = true
  error.value = ''
  try {
    const [charData, clueData, motifData, foreData, factData, lessonData] = await Promise.all([
      api.dbCharacters(name), api.dbClues(name), api.dbMotifs(name), api.dbForeshadow(name, currentCh.value), api.dbFacts(name, { limit: 30 }), api.dbLessons(name),
    ])
    if (seq !== requestSeq || name !== novelName.value) return
    characters.value = charData; clues.value = clueData; motifs.value = motifData; fore.value = foreData; facts.value = factData; lessons.value = lessonData
    currentCh.value = (store.novel?.chapters_written || 0) + 1
  } catch (e) {
    if (seq === requestSeq) error.value = detail(e, '知识库加载失败')
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

async function loadForeshadow() {
  if (!novelName.value) return
  try { fore.value = await api.dbForeshadow(novelName.value, currentCh.value) } catch (e) { error.value = detail(e, '伏笔加载失败') }
}
async function loadFacts() {
  if (!novelName.value) return
  loading.value = true
  try { facts.value = await api.dbFacts(novelName.value, { q: factQ.value, chapter: factBefore.value, limit: 50 }) } catch (e) { error.value = detail(e, '事实加载失败') } finally { loading.value = false }
}
async function syncKnowledge() {
  if (!novelName.value) return
  syncing.value = true
  try { const result = await api.knowledgeSync(novelName.value); await loadAll(); ElMessage.success(`同步完成，共更新 ${Object.values(result.counts || {}).filter(Number.isFinite).reduce((a, b) => a + b, 0)} 条`) } catch (e) { ElMessage.error(detail(e, '同步失败')) } finally { syncing.value = false }
}
async function loadBFile() {
  if (!novelName.value) return
  fileLoading.value = true; fileError.value = ''
  try { bContent.value = await api.bibleFile(novelName.value, bFile.value) } catch (e) { bContent.value = ''; fileError.value = detail(e, '文件加载失败') } finally { fileLoading.value = false }
}
async function saveBFile() {
  if (!novelName.value) return
  fileSaving.value = true; fileError.value = ''
  try { await api.saveBibleFile(novelName.value, bFile.value, bContent.value); await loadAll(); await loadBFile(); ElMessage.success('文件已保存并同步') } catch (e) { fileError.value = detail(e, '文件保存失败') } finally { fileSaving.value = false }
}

function openEditor(type, id, data, json = '{}', hinted = '') {
  Object.assign(editor, { visible: true, type, id: id || '', lockId: Boolean(id), title: `${id ? '编辑' : '添加'}${{ character: '人物', clue: '线索', foreshadow: '伏笔', motif: '母题' }[type]}`, data, json, hinted })
}
function editCharacter(row) {
  const profile = row?.profile || {}
  openEditor('character', row?.name, { role: row?.role || '', voice_print: row?.voice_print || '', first_appearance_chapter: row?.first_appearance_chapter || null, chapter: null }, JSON.stringify(profile, null, 2))
}
function editClue(row) {
  openEditor('clue', row?.id, { name: row?.name || '', type: row?.type || '', description: row?.description || '', introduced_chapter: row?.introduced_chapter || null, intended_reveal_chapter: row?.intended_reveal_chapter || null, resolved: Boolean(row?.resolved), chapter: row?.updated_chapter || null }, JSON.stringify(row?.state || {}, null, 2))
}
function editForeshadow(row) {
  openEditor('foreshadow', row?.id, { name: row?.name || '', status: row?.status || 'pending', description: row?.description || '', introduced_chapter: row?.introduced_chapter || null, intended_payoff_chapter: row?.intended_payoff_chapter || null, resolved_chapter: row?.resolved_chapter || null }, '{}', row?.hinted_chapters?.join(', ') || '')
}
function editMotif(row) {
  openEditor('motif', row?.id, { name: row?.name || '', description: row?.description || '' }, '{}', row?.used_in_chapters?.join(', ') || '')
}

async function saveEntity() {
  const name = novelName.value
  const id = editor.id.trim()
  if (!name || !id) { ElMessage.warning('请输入唯一 ID 或姓名'); return }
  saving.value = true
  try {
    if (editor.type === 'character') {
      const profile = JSON.parse(editor.json || '{}')
      await api.saveCharacter(name, id, { profile: { ...profile, role: editor.data.role, voice_print: editor.data.voice_print, first_appearance_chapter: nullable(editor.data.first_appearance_chapter) }, chapter: nullable(editor.data.chapter) })
    } else if (editor.type === 'clue') {
      await api.saveClue(name, id, { ...editor.data, introduced_chapter: nullable(editor.data.introduced_chapter), intended_reveal_chapter: nullable(editor.data.intended_reveal_chapter), chapter: nullable(editor.data.chapter), state: JSON.parse(editor.json || '{}') })
    } else if (editor.type === 'foreshadow') {
      await api.dbForeshadowUpdate(name, id, { ...editor.data, introduced_chapter: nullable(editor.data.introduced_chapter), intended_payoff_chapter: nullable(editor.data.intended_payoff_chapter), resolved_chapter: nullable(editor.data.resolved_chapter), hinted_chapters: parseChapters(editor.hinted) })
    } else {
      const raw = await api.bibleFile(name, 'motif_bank.json')
      const parsed = JSON.parse(raw || '{"motifs":[]}')
      const item = { id, name: editor.data.name, description: editor.data.description, used_in_chapters: parseChapters(editor.hinted) }
      const index = (parsed.motifs ||= []).findIndex(motif => (motif.id || motif.name) === id)
      if (index >= 0) parsed.motifs[index] = { ...parsed.motifs[index], ...item }
      else parsed.motifs.push(item)
      await api.saveBibleFile(name, 'motif_bank.json', JSON.stringify(parsed, null, 2))
    }
    editor.visible = false
    await loadAll()
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e instanceof SyntaxError ? 'JSON 格式不正确' : detail(e, '保存失败'))
  } finally { saving.value = false }
}

watch(novelName, async (name) => {
  ++requestSeq; clearData()
  if (!name) return
  currentCh.value = (store.novel?.chapters_written || 0) + 1
  await loadAll()
  await loadBFile()
}, { immediate: true })
</script>

<style scoped>
.tab-section { min-height: 360px; }
.section-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.section-toolbar h3 { margin: 0 0 3px; font-size: 16px; }
.section-toolbar span { color: var(--muted); font-size: 13px; }
.toolbar-group { display: flex; align-items: center; gap: 8px; }
.fact-search .el-input { width: 220px; }
.fact-search .el-input-number { width: 130px; }
.state-list { display: flex; flex-direction: column; gap: 3px; color: var(--muted); font-size: 12px; }
.notice-stack { display: grid; gap: 8px; margin-bottom: 14px; }
.dialog-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }
.dialog-grid :deep(.el-input-number), .dialog-grid :deep(.el-select) { width: 100%; }
.code-editor :deep(textarea) { font-family: var(--mono); line-height: 1.65; }
@media (max-width: 760px) {
  .responsive-toolbar { align-items: stretch; flex-direction: column; }
  .toolbar-group { flex-wrap: wrap; }
  .fact-search .el-input { width: 100%; }
  .dialog-grid { grid-template-columns: 1fr; }
}
</style>
