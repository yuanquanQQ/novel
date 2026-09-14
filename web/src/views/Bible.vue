<template>
  <div class="page">
    <h2>知识库 · {{ novelName }}</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="人物" name="characters">
        <el-table :data="characters" size="small">
          <el-table-column prop="name" label="姓名" width="120" />
          <el-table-column prop="role" label="角色" width="140" />
          <el-table-column prop="voice_print" label="声纹" />
          <el-table-column label="近况（状态时间线）">
            <template #default="{ row }">
              <div v-for="s in row.recent_states" :key="s.chapter" class="mono muted" style="font-size: 12px">
                [{{ s.chapter }}章] {{ short(s.state_json) }}
              </div>
              <span v-if="!row.recent_states?.length" class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="first_chapter" label="登场" width="70" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="伏笔" name="foreshadow">
        <div ref="curWrap">
          <div class="row" style="margin-bottom: 8px">
            <span class="muted">当前章号（判定过期/遗忘）：</span>
            <el-input-number v-model="currentCh" size="small" :min="1" @change="loadFore" />
          </div>
          <el-alert type="warning" v-if="fore.buckets?.overdue_to_payoff?.length" :closable="false"
                    :title="'到期未收: ' + fore.buckets.overdue_to_payoff.map(f => f.name).join('、')" style="margin-bottom: 8px" />
          <el-alert type="info" v-if="fore.buckets?.stale?.length" :closable="false"
                    :title="'久未触碰: ' + fore.buckets.stale.map(f => f.name + '(暗了' + f.days_dark + '章)').join('、')" style="margin-bottom: 8px" />
        </div>
        <el-table :data="fore.rows" size="small">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="status" label="状态" width="90">
            <template #default="{ row }"><el-tag size="small" :type="row.status === 'resolved' ? 'success' : 'warning'">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column label="埋设→触碰→预定回收" width="280">
            <template #default="{ row }">
              <span class="mono">
                {{ row.planted_ch }} → {{ row.hinted_chs.join(', ') || '从未' }} → {{ row.payoff_ch || '?' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="跨章事实" name="facts">
        <div class="row" style="margin-bottom: 8px">
          <el-input v-model="factQ" placeholder="关键词检索（空格分隔，如：银色 颈圈）" style="width: 320px" @keyup.enter="loadFacts" />
          <el-input-number v-model="factBefore" :min="0" size="small" placeholder="章号前" />
          <el-button size="small" type="primary" @click="loadFacts">检索</el-button>
        </div>
        <el-table :data="facts" size="small" max-height="520">
          <el-table-column prop="chapter" label="章" width="60" />
          <el-table-column prop="kind" label="类型" width="100" />
          <el-table-column prop="subject" label="主体" width="120" />
          <el-table-column prop="content" label="事实" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="教训 & 原档" name="bible">
        <el-table :data="lessons" size="small" max-height="240">
          <el-table-column prop="chapter" label="章" width="60" />
          <el-table-column prop="issue" label="问题" />
          <el-table-column prop="fix" label="修复" width="200" />
          <el-table-column prop="source" label="来源" width="90" />
        </el-table>
        <h4>原始 Bible 文件</h4>
        <el-select v-model="bFile" size="small" style="width: 220px; margin-bottom: 10px" @change="loadBFile">
          <el-option v-for="f in BIBLE_FILES" :key="f" :label="f" :value="f" />
        </el-select>
        <el-input v-model="bContent" type="textarea" :autosize="{ minRows: 14 }" class="mono" />
        <el-button size="small" type="primary" style="margin-top: 8px" @click="saveBFile">保存文件</el-button>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '../stores/novel'
import { api } from '../api'

const BIBLE_FILES = ['characters.json', 'clues.json', 'motif_bank.json', 'master_bible.md', 'lessons_learned.jsonl', 'chapter_titles.json']
const store = useNovelStore()
const route = useRoute()
const novelName = computed(() => route.params.name || store.current)
const tab = ref('characters')
const characters = ref([])
const fore = ref({ rows: [], buckets: {} })
const currentCh = ref(5)
const facts = ref([])
const factQ = ref('')
const factBefore = ref(0)
const lessons = ref([])
const bFile = ref('characters.json')
const bContent = ref('')

const short = (s) => { try { return JSON.stringify(JSON.parse(s)).slice(0, 90) } catch { return (s || '').slice(0, 90) } }

async function loadFore() { fore.value = await api.dbForeshadow(novelName.value, currentCh.value) }
async function loadFacts() { facts.value = await api.dbFacts(novelName.value, { q: factQ.value, chapter: factBefore.value }) }
async function loadBFile() { bContent.value = await api.bibleFile(novelName.value, bFile.value) }
async function saveBFile() {
  try {
    await api.saveBibleFile(novelName.value, bFile.value, bContent.value)
    ElMessage.success('已保存')
  } catch (e) { ElMessage.error('格式错误: ' + (e?.response?.data?.detail || '')) }
}

onMounted(async () => {
  await store.load()
  currentCh.value = (store.novel?.chapters_written || 4) + 1
  characters.value = await api.dbCharacters(novelName.value)
  lessons.value = await api.dbLessons(novelName.value)
  loadFore(); loadBFile()
})
</script>
