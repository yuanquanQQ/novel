<template>
  <div class="page">
    <h2>大纲 / 章名 · {{ novelName }}</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="全书大纲 (outline.md)" name="outline">
        <div class="row" style="justify-content: space-between; margin-bottom: 10px">
          <span class="muted">编辑后可运行「全书大纲」任务重新生成，或直接保存你的修改</span>
          <div>
            <el-button size="small" @click="editO = !editO">{{ editO ? '预览' : '编辑' }}</el-button>
            <el-button size="small" type="primary" @click="saveOutline" :disabled="!editO">保存</el-button>
          </div>
        </div>
        <el-input v-if="editO" v-model="outline" type="textarea" :autosize="{ minRows: 26 }" class="mono" />
        <pre v-else class="prose md" v-text="outline"></pre>
      </el-tab-pane>

      <el-tab-pane label="章名库" name="titles">
        <div v-for="v in titleVolumes" :key="v.key" style="margin-bottom: 16px">
          <h4 style="margin: 6px 0">{{ v.name }} <span class="muted">第{{ v.lo }}-{{ v.hi }}章</span></h4>
          <el-table :data="v.rows" size="small" max-height="320">
            <el-table-column prop="num" label="#" width="60" />
            <el-table-column label="章名">
              <template #default="{ row }">
                <el-input v-model="row.title" size="small" @change="saveTitle(row)" v-if="row.dirty" />
                <span v-else @dblclick="row.dirty = true" style="cursor: pointer">{{ row.title }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.done" type="success" size="small">已写</el-tag>
                <el-tag v-else-if="row.auto" type="warning" size="small">自动名</el-tag>
                <el-tag v-else type="info" size="small">待写</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useNovelStore } from '../stores/novel'
import { api } from '../api'

const store = useNovelStore()
const route = useRoute()
const novelName = computed(() => route.params.name || store.current)
const tab = ref('outline')
const outline = ref('')
const editO = ref(false)
const titles = ref({ volumes: {} })
const doneSet = ref(new Set())
const titleVolumes = computed(() => Object.entries(titles.value.volumes || {}).map(([key, v]) => ({
  key, name: v.name, lo: v.range?.[0], hi: v.range?.[1],
  rows: Object.entries(v.chapters || {}).map(([num, title]) => ({
    num: +num, title, dirty: false,
    auto: /^第\d+章$/.test(title),
    done: doneSet.value.has(+num),
  })).sort((a, b) => a.num - b.num),
})))

async function saveOutline() {
  await api.saveOutline(novelName.value, outline.value)
  editO.value = false
  ElMessage.success('大纲已保存')
}
async function saveTitle(row) {
  await api.saveTitle(novelName.value, row.num, row.title)
  row.dirty = false
  ElMessage.success('已更新')
}

onMounted(async () => {
  await store.load()
  const [o, t, st] = await Promise.all([api.outline(novelName.value), api.titles(novelName.value), api.status(novelName.value)])
  outline.value = typeof o === 'string' ? o : ''
  titles.value = t || { volumes: {} }
  doneSet.value = new Set((st.chapter_log || []).map(c => c.chapter))
})
</script>

<style scoped>
.md { background: #fff; border-radius: 8px; padding: 16px; max-height: 74vh; overflow: auto }
</style>
