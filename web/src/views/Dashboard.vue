<template>
  <div class="page">
    <template v-if="!store.current">
      <div class="welcome-empty">
        <div class="empty-icon"><el-icon><Reading /></el-icon></div>
        <h1>开始你的第一部小说</h1>
        <p>创建独立的创作空间，管理大纲、章节、人物设定与叙事线索。</p>
        <el-button type="primary" size="large" @click="$emit('create-novel')"><el-icon><Plus /></el-icon>新建小说</el-button>
      </div>
    </template>

    <template v-else>
      <header class="page-header">
        <div><div class="eyebrow">OVERVIEW</div><h1>{{ status?.title || store.novel?.title || store.current }}</h1><p>掌握创作进度与知识库状态</p></div>
        <el-button :loading="loading" @click="load"><el-icon><Refresh /></el-icon>刷新数据</el-button>
      </header>
      <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="section-gap" />
      <el-alert v-if="seedWarnings.length" type="warning" show-icon :closable="false" class="section-gap" :title="`种子数据待补充：${seedWarnings.join('；')}`">
        <template #default><el-button link type="primary" @click="goto('bible')">去补充 →</el-button></template>
      </el-alert>

      <div v-loading="loading">
        <div v-if="status" class="stat-grid">
          <div class="stat-card"><span class="stat-label">章节进度</span><strong>{{ status.written }}<small>/ {{ status.chapter_count }}</small></strong><el-progress :percentage="bookPct" :show-text="false" :stroke-width="5" /></div>
          <div class="stat-card"><span class="stat-label">累计字数</span><strong>{{ totalWords.toLocaleString() }}</strong><span class="stat-note">已生成章节总字数</span></div>
          <div class="stat-card"><span class="stat-label">伏笔回收</span><strong>{{ status.db.foreshadow_resolved }}<small>/ {{ status.db.foreshadow_total }}</small></strong><span class="stat-note">已回收 / 总伏笔</span></div>
          <div class="stat-card"><span class="stat-label">跨章事实</span><strong>{{ status.db.facts }}</strong><span class="stat-note">知识库记忆条目</span></div>
          <div class="stat-card"><span class="stat-label">待人工修订</span><strong>{{ status.pending_count || 0 }}</strong><span class="stat-note">未通过全部质量闸门的章节</span></div>
        </div>

        <section v-if="status" class="content-card section-gap">
          <div class="card-heading"><div><h2>各卷进度</h2><p>按卷查看章节完成情况</p></div></div>
          <div v-if="status.volumes?.length" class="volume-list">
            <div v-for="v in status.volumes" :key="v.key" class="volume-row"><div class="volume-name"><strong>{{ v.name }}</strong><span>第 {{ v.lo }}–{{ v.hi }} 章</span></div><el-progress :percentage="pct(v)" :stroke-width="8" /><span class="volume-count mono">{{ v.done }} / {{ v.hi - v.lo + 1 }}</span></div>
          </div>
          <el-empty v-else description="暂无分卷信息" />
        </section>

        <div v-if="status" class="dashboard-grid section-gap">
          <section class="content-card">
            <div class="card-heading"><div><h2>读者评分</h2><p>最近的续读反馈</p></div></div>
            <div v-if="scored.length" class="simple-list"><div v-for="c in scored" :key="c.chapter" class="simple-row"><span>第 {{ c.chapter }} 章</span><el-rate :model-value="c.reader_score / 2" disabled size="small" /><b class="mono">{{ c.reader_score }}</b><el-tag :type="c.would_continue ? 'success' : 'danger'" effect="plain">{{ c.would_continue ? '续读' : '弃书' }}</el-tag></div></div>
            <el-empty v-else :image-size="72" description="生成章节后会出现评分" />
          </section>
          <section class="content-card">
            <div class="card-heading"><div><h2>高频风格命中</h2><p>反复出现的写作问题</p></div></div>
            <div v-if="styleHits.patterns?.length" class="simple-list"><div v-for="hit in styleHits.patterns.slice(0, 8)" :key="`${hit.category}-${hit.pattern}`" class="simple-row style-row"><el-tag type="info" effect="plain">{{ hit.category }}</el-tag><span class="grow mono">{{ hit.pattern }}</span><span class="muted">{{ hit.total }} 次 / {{ hit.chapters }} 章</span></div></div>
            <el-empty v-else :image-size="72" description="暂无命中数据" />
          </section>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useNovelStore } from '../stores/novel'
import { api } from '../api'

defineEmits(['create-novel'])
const router = useRouter()
const store = useNovelStore()
const status = ref(null)
const styleHits = ref({ patterns: [] })
const loading = ref(false)
const error = ref('')
let seq = 0
const scored = computed(() => (status.value?.chapter_log || []).filter(c => c.reader_score != null).slice(-8).reverse())
const totalWords = computed(() => (status.value?.chapter_log || []).reduce((sum, row) => sum + (row.words || 0), 0))
const seedWarnings = computed(() => status.value?.seed_coverage?.warnings || [])
const goto = (view) => router.push({ name: view, params: { name: store.current } })
const bookPct = computed(() => status.value?.chapter_count ? Math.round(status.value.written * 100 / status.value.chapter_count) : 0)
const pct = (volume) => Math.round(volume.done * 100 / Math.max(1, volume.hi - volume.lo + 1))

async function load() {
  const name = store.current
  const request = ++seq
  status.value = null; styleHits.value = { patterns: [] }; error.value = ''
  if (!name) return
  loading.value = true
  try {
    const [nextStatus, nextHits] = await Promise.all([api.status(name), api.dbStyleHits(name)])
    if (request === seq && name === store.current) { status.value = nextStatus; styleHits.value = nextHits }
  } catch (e) { if (request === seq) error.value = e.response?.data?.detail || '总览数据加载失败' }
  finally { if (request === seq) loading.value = false }
}
watch(() => store.current, load, { immediate: true })
</script>

<style scoped>
.welcome-empty { display: grid; justify-items: center; max-width: 620px; margin: 14vh auto 0; padding: 56px 24px; text-align: center; }
.empty-icon { display: grid; place-items: center; width: 72px; height: 72px; margin-bottom: 22px; color: var(--primary); background: var(--primary-soft); border: 1px solid #dbe7e3; border-radius: 20px; font-size: 32px; }
.welcome-empty h1 { margin: 0; font-size: 28px; }
.welcome-empty p { max-width: 440px; margin: 12px 0 26px; color: var(--muted); line-height: 1.8; }
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.stat-card { display: flex; flex-direction: column; min-height: 116px; padding: 20px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); }
.stat-label { margin-bottom: 13px; color: var(--muted); font-size: 13px; }
.stat-card strong { margin-bottom: 8px; color: var(--text); font-size: 27px; font-weight: 650; letter-spacing: -.03em; }
.stat-card strong small { color: #98a2ab; font-size: 15px; font-weight: 500; }
.stat-note { color: #9aa3ab; font-size: 12px; }
.volume-list { display: grid; gap: 16px; }
.volume-row { display: grid; grid-template-columns: 150px 1fr 72px; align-items: center; gap: 18px; }
.volume-name strong, .volume-name span { display: block; }
.volume-name strong { font-size: 14px; }
.volume-name span { margin-top: 3px; color: var(--muted); font-size: 12px; }
.volume-count { color: var(--muted); font-size: 12px; text-align: right; }
.dashboard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.simple-list { display: grid; }
.simple-row { display: flex; align-items: center; gap: 10px; min-height: 38px; border-bottom: 1px solid var(--border-light); font-size: 13px; }
.simple-row:last-child { border-bottom: 0; }
@media (max-width: 1050px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } .dashboard-grid { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .stat-grid { grid-template-columns: 1fr; } .volume-row { grid-template-columns: 105px 1fr; } .volume-count { display: none; } }
</style>
