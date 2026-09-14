<template>
  <el-container style="height: 100vh">
    <el-aside width="210px" class="side">
      <div class="brand">📖 创作控制台</div>
      <el-select v-model="novelStore.current" size="default" style="width: 100%; padding: 0 10px 12px"
                 @change="onNovelChange">
        <el-option v-for="n in novelStore.novels" :key="n.id" :label="`${n.title} (${n.chapters_written}/${n.chapter_count || '?'})`" :value="n.id" />
      </el-select>
      <el-menu :default-active="$route.name" router background-color="#1d2330" text-color="#a8adba" active-text-color="#ffd04b">
        <el-menu-item index="dashboard" :route="{ name: 'dashboard' }"><el-icon><DataBoard /></el-icon><span>总览</span></el-menu-item>
        <el-menu-item index="outline" :route="{ name: 'outline', params: { name: cur } }"><el-icon><Notebook /></el-icon><span>大纲/章名</span></el-menu-item>
        <el-menu-item index="chapters" :route="{ name: 'chapters', params: { name: cur } }"><el-icon><Document /></el-icon><span>章节</span></el-menu-item>
        <el-menu-item index="console" :route="{ name: 'console', params: { name: cur } }"><el-icon><VideoPlay /></el-icon><span>生成控制台</span></el-menu-item>
        <el-menu-item index="bible" :route="{ name: 'bible', params: { name: cur } }"><el-icon><Collection /></el-icon><span>知识库</span></el-menu-item>
        <el-menu-item index="style" :route="{ name: 'style' }"><el-icon><MagicStick /></el-icon><span>风格工坊</span></el-menu-item>
      </el-menu>
    </el-aside>
    <el-main style="padding: 0; overflow-y: auto">
      <router-view v-if="novelStore.loaded" :key="`${$route.fullPath}:${novelStore.current}`" />
    </el-main>
  </el-container>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useNovelStore } from './stores/novel'

const novelStore = useNovelStore()
const router = useRouter()
const cur = computed(() => novelStore.current)

onMounted(async () => { await novelStore.load() })

function onNovelChange(name) {
  novelStore.setNovel(name)
  const r = router.currentRoute.value
  if (r.params.name) router.replace({ name: r.name, params: { ...r.params, name } })
}
</script>

<style scoped>
.side { background: #1d2330; color: #fff; overflow-y: auto }
.brand { font-size: 17px; font-weight: 700; padding: 18px 14px 12px; color: #ffd04b }
:deep(.el-select) { background: transparent }
:deep(.el-menu) { border-right: none }
</style>
