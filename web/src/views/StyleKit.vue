<template>
  <div class="page">
    <h2>风格工坊 <span class="muted">engine/style_kit · 全局生效，直接改这里=改所有小说</span></h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="禁用词/模式" name="rules">
        <div class="row" style="justify-content: space-between; margin-bottom: 10px">
          <div class="row">
            <el-button size="small" @click="reload">重读</el-button>
            <el-button size="small" type="primary" @click="save" :disabled="!JSONvalid">保存</el-button>
          </div>
          <div class="row">
            <el-tag type="danger">硬禁词 {{ (rules.hard_words||[]).length }}</el-tag>
            <el-tag type="warning">软禁词 {{ Object.keys(rules.soft_words||{}).length }}</el-tag>
            <el-tag type="danger">句式模式 {{ (rules.patterns||[]).length }}</el-tag>
            <el-tag v-if="!JSONvalid" type="danger">JSON 非法</el-tag>
          </div>
        </div>
        <el-input v-model="raw" type="textarea" :autosize="{ minRows: 26 }" class="mono" />
      </el-tab-pane>

      <el-tab-pane label="人味技法 techniques.md" name="tech">
        <div class="row" style="justify-content: flex-end; margin-bottom: 8px">
          <el-button size="small" @click="editT = !editT">{{ editT ? '预览' : '编辑' }}</el-button>
          <el-button size="small" type="primary" :disabled="!editT" @click="ElMessageNotReady()">保存(MD需后端PUT占位)</el-button>
        </div>
        <el-input v-if="editT" v-model="tech" type="textarea" :autosize="{ minRows: 24 }" class="mono" />
        <pre v-else class="prose md">{{ tech }}</pre>
      </el-tab-pane>

      <el-tab-pane label="番茄规则 & 模板道具警示" name="tomato">
        <h4>番茄规则</h4>
        <pre class="prose md">{{ tomato }}</pre>
        <h4>模板道具（出现≥2件即高度可疑）</h4>
        <el-tag v-for="p in rules.template_props_watch" :key="p" type="info" style="margin: 3px">{{ p }}</el-tag>
      </el-tab-pane>

      <el-tab-pane label="扫描器实验室" name="lab">
        <div class="muted" style="margin-bottom: 8px">粘贴文本，实时看 scanner 判定（与流水线同一规则）</div>
        <el-input v-model="sample" type="textarea" :autosize="{ minRows: 10 }" class="mono" placeholder="粘贴章节片段..." />
        <div class="row" style="margin-top: 10px">
          <el-button type="primary" @click="scanIt">扫描</el-button>
          <el-tag :type="report.passed ? 'success' : 'danger'">{{ report.passed ? '通过' : '未通过' }}</el-tag>
          <span class="mono muted" v-if="report.metrics">{{ JSON.stringify(report.metrics) }}</span>
        </div>
        <div v-for="(v, i) in report.violations" :key="'v' + i" style="margin: 4px 0">
          <el-tag size="small" type="danger">{{ v.category }}</el-tag>
          <span class="mono">「{{ v.pattern }}」x{{ v.count }} @ {{ v.where }}</span>
          <span class="muted"> {{ v.hint }}</span>
        </div>
        <div v-for="(w, i) in report.warnings" :key="'w' + i" style="margin: 4px 0">
          <el-tag size="small" type="warning">{{ w.category }}</el-tag>
          <span class="mono">「{{ w.pattern }}」x{{ w.count }}</span>
          <span class="muted"> {{ w.hint }}</span>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const tab = ref('rules')
const rules = ref({})
const raw = ref('')
const tech = ref('')
const tomato = ref('')
const editT = ref(false)
const sample = ref('他然而转身，眼中闪过一丝复杂，深吸一口气——仿佛整个世界都安静了。\n"你来了。"她说。\n\n「走了。」他说，「粥在锅里。」')
const report = ref({})

const JSONvalid = computed(() => { try { JSON.parse(raw.value); return true } catch { return false } })

async function reload() {
  rules.value = await api.styleKit()
  raw.value = JSON.stringify(rules.value, null, 2)
}
async function save() {
  try {
    await api.saveStyleKit(JSON.parse(raw.value))
    rules.value = JSON.parse(raw.value)
    ElMessage.success('已保存，scanner 立即生效（重启后端后彻底生效）')
  } catch (e) { ElMessage.error('保存失败: ' + (e?.response?.data?.detail || '')) }
}
function ElMessageNotReady() { ElMessage.info('技法/规则 MD 修改建议直接编辑 engine/style_kit 下文件') }
async function scanIt() { report.value = await api.scanPreview(sample.value) }

onMounted(async () => {
  reload()
  tech.value = await api.styleDoc('techniques')
  tomato.value = await api.styleDoc('tomato_rules')
  scanIt()
})
</script>

<style scoped>
.md { background: #fff; border-radius: 8px; padding: 14px; max-height: 68vh; overflow: auto; font-size: 14px }
</style>
