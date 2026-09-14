<template>
  <div class="page">
    <h2>{{ status?.title || store.current }} · 总览</h2>
    <el-row :gutter="14" v-if="status">
      <el-col :span="6"><div class="card"><div class="stat-num">{{ status.written }}/{{ status.chapter_count }}</div><div class="muted">章节进度</div></div></el-col>
      <el-col :span="6"><div class="card"><div class="stat-num">{{ totalWords.toLocaleString() }}</div><div class="muted">总字数</div></div></el-col>
      <el-col :span="6"><div class="card"><div class="stat-num">{{ status.db.foreshadow_resolved }}/{{ status.db.foreshadow_total }}</div><div class="muted">伏笔回收</div></div></el-col>
      <el-col :span="6"><div class="card"><div class="stat-num">{{ status.db.facts }}</div><div class="muted">跨章事实</div></div></el-col>
    </el-row>

    <div class="card" style="margin-top: 14px" v-if="status">
      <h3 style="margin: 0 0 12px">各卷进度</h3>
      <div v-for="v in status.volumes" :key="v.key" class="vol">
        <span class="vname">{{ v.name }}</span>
        <el-progress :percentage="pct(v)" :stroke-width="14" style="flex: 1" />
        <span class="muted mono">第{{ v.lo }}-{{ v.hi }}章 · {{ v.done }}/{{ v.hi - v.lo + 1 }}</span>
      </div>
    </div>

    <el-row :gutter="14" style="margin-top: 14px" v-if="status">
      <el-col :span="12">
        <div class="card">
          <h3 style="margin: 0 0 8px">读者评分趋势</h3>
          <div v-if="!scored.length" class="muted">暂无评分记录（运行 generate 后出现）</div>
          <table class="tbl" v-else>
            <tr v-for="c in scored" :key="c.chapter">
              <td>第{{ c.chapter }}章</td>
              <td><el-rate :model-value="c.reader_score / 2" disabled size="small" /></td>
              <td class="mono">{{ c.reader_score }}</td>
              <td><el-tag :type="c.would_continue ? 'success' : 'danger'" size="small">{{ c.would_continue ? '续读' : '弃书' }}</el-tag></td>
            </tr>
          </table>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="card">
          <h3 style="margin: 0 0 8px">风格惯性 Top（越靠上越是反复踩的雷）</h3>
          <div v-if="!styleHits.patterns?.length" class="muted">暂无命中数据</div>
          <table class="tbl" v-else>
            <tr v-for="h in styleHits.patterns.slice(0, 8)" :key="h.pattern">
              <td><el-tag size="small" type="warning">{{ h.category }}</el-tag></td>
              <td class="mono">{{ h.pattern }}</td>
              <td>命中 <b>{{ h.total }}</b> 次 / {{ h.chapters }} 章</td>
            </tr>
          </table>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useNovelStore } from '../stores/novel'
import { api } from '../api'

const store = useNovelStore()
const route = useRoute()
const name = computed(() => route.params.name || store.current)
const status = ref(null)
const styleHits = ref({})
const scored = computed(() => (status.value?.chapter_log || []).filter(c => c.reader_score != null).slice(-12).reverse())
const totalWords = computed(() => (status.value?.chapter_log || []).reduce((s, c) => s + (c.words || 0), 0))
const pct = (v) => Math.round(v.done * 100 / (v.hi - v.lo + 1))

async function load() {
  status.value = await api.status(name.value)
  styleHits.value = await api.dbStyleHits(name.value)
}
onMounted(async () => { await store.load(); load() })
</script>

<style scoped>
.vol { display: flex; align-items: center; gap: 14px; margin-bottom: 12px }
.vname { width: 90px; font-weight: 600 }
.tbl { width: 100%; border-collapse: collapse }
.tbl td { padding: 6px 4px; border-bottom: 1px solid #f0f0f0; font-size: 14px }
</style>
