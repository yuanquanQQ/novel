<template>
  <div class="page">
    <header class="page-header"><div><div class="eyebrow">STYLE SYSTEM</div><h1>风格工坊</h1><p>全局写作规则与文本扫描实验室</p></div><el-button :loading="loading" @click="loadAll"><el-icon><Refresh /></el-icon>刷新</el-button></header>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="section-gap" />
    <div class="content-card" v-loading="loading">
      <el-tabs v-model="tab" class="clean-tabs">
        <el-tab-pane label="禁用词与模式" name="rules">
          <div class="section-toolbar"><div><h3>规则源文件</h3><span>保存后对所有小说生效</span></div><div class="toolbar-group tags"><el-tag type="danger" effect="plain">硬禁词 {{ (rules.hard_words || []).length }}</el-tag><el-tag type="warning" effect="plain">软禁词 {{ Object.keys(rules.soft_words || {}).length }}</el-tag><el-tag type="info" effect="plain">句式 {{ (rules.patterns || []).length }}</el-tag><el-button type="primary" :loading="saving" :disabled="!jsonValid" @click="save"><el-icon><Check /></el-icon>保存</el-button></div></div>
          <el-alert v-if="!jsonValid" title="JSON 格式不正确，修复后才能保存" type="error" :closable="false" class="section-gap" />
          <el-input v-model="raw" type="textarea" :autosize="{ minRows: 25 }" class="code-editor" />
        </el-tab-pane>
        <el-tab-pane label="人味技法" name="tech">
          <div class="section-toolbar"><div><h3>techniques.md</h3><span>当前接口仅支持只读预览</span></div></div>
          <div v-if="tech" class="document-view prose">{{ tech }}</div><el-empty v-else description="暂无技法文档" />
        </el-tab-pane>
        <el-tab-pane label="番茄规则" name="tomato">
          <div class="document-view prose">{{ tomato }}</div>
          <div class="watch-list"><h3>模板道具警示</h3><div><el-tag v-for="item in rules.template_props_watch" :key="item" type="info" effect="plain">{{ item }}</el-tag></div></div>
        </el-tab-pane>
        <el-tab-pane label="扫描实验室" name="lab">
          <div class="section-toolbar"><div><h3>文本扫描</h3><span>使用与创作流水线相同的规则</span></div><div class="toolbar-group"><el-button type="primary" :loading="scanning" @click="scanIt"><el-icon><Search /></el-icon>开始扫描</el-button><el-tag v-if="report.passed != null" :type="report.passed ? 'success' : 'danger'" effect="plain">{{ report.passed ? '通过' : '未通过' }}</el-tag></div></div>
          <el-input v-model="sample" type="textarea" :autosize="{ minRows: 11 }" placeholder="粘贴需要检查的章节片段" />
          <div v-if="report.metrics" class="metrics mono">{{ JSON.stringify(report.metrics) }}</div>
          <div class="result-list"><div v-for="(item, index) in report.violations" :key="`v-${index}`" class="result-row"><el-tag type="danger" effect="plain">{{ item.category }}</el-tag><span class="mono">「{{ item.pattern }}」× {{ item.count }} · {{ item.where }}</span><span class="muted">{{ item.hint }}</span></div><div v-for="(item, index) in report.warnings" :key="`w-${index}`" class="result-row"><el-tag type="warning" effect="plain">{{ item.category }}</el-tag><span class="mono">「{{ item.pattern }}」× {{ item.count }}</span><span class="muted">{{ item.hint }}</span></div></div>
          <el-empty v-if="report.passed != null && !report.violations?.length && !report.warnings?.length" :image-size="64" description="未发现问题" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
const tab = ref('rules'); const rules = ref({}); const raw = ref(''); const tech = ref(''); const tomato = ref(''); const sample = ref(''); const report = ref({}); const loading = ref(false); const saving = ref(false); const scanning = ref(false); const error = ref('')
const jsonValid = computed(() => { try { JSON.parse(raw.value); return true } catch { return false } })
async function loadAll() { loading.value = true; error.value = ''; try { const [nextRules, nextTech, nextTomato] = await Promise.all([api.styleKit(), api.styleDoc('techniques'), api.styleDoc('tomato_rules')]); rules.value = nextRules; raw.value = JSON.stringify(nextRules, null, 2); tech.value = nextTech; tomato.value = nextTomato } catch (e) { error.value = e.response?.data?.detail || '风格配置加载失败' } finally { loading.value = false } }
async function save() { saving.value = true; try { const parsed = JSON.parse(raw.value); await api.saveStyleKit(parsed); rules.value = parsed; ElMessage.success('规则已保存并生效') } catch (e) { ElMessage.error(e.response?.data?.detail || '保存失败') } finally { saving.value = false } }
async function scanIt() { scanning.value = true; try { report.value = await api.scanPreview(sample.value) } catch (e) { ElMessage.error(e.response?.data?.detail || '扫描失败') } finally { scanning.value = false } }
onMounted(loadAll)
</script>

<style scoped>
.section-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }.section-toolbar h3,.watch-list h3 { margin: 0 0 3px; font-size: 15px; }.section-toolbar span { color: var(--muted); font-size: 12px; }.code-editor :deep(textarea) { font-family: var(--mono); line-height: 1.65; }.document-view { max-height: 65vh; overflow: auto; padding: 20px; background: var(--surface-soft); border: 1px solid var(--border-light); border-radius: var(--radius-sm); }.watch-list { margin-top: 20px; }.watch-list .el-tag { margin: 8px 7px 0 0; }.metrics { margin-top: 12px; padding: 10px 12px; color: var(--muted); background: var(--surface-soft); border-radius: 8px; font-size: 12px; }.result-list { display: grid; gap: 8px; margin-top: 14px; }.result-row { display: flex; align-items: center; gap: 9px; padding: 10px 0; border-bottom: 1px solid var(--border-light); font-size: 13px; }
@media (max-width: 760px) { .section-toolbar { align-items: stretch; flex-direction: column; }.tags { flex-wrap: wrap; }.result-row { align-items: flex-start; flex-direction: column; } }
</style>
