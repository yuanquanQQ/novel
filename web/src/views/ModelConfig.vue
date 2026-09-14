<template>
  <div class="page" v-loading="loading">
    <header class="page-header">
      <div>
        <div class="eyebrow">MODEL</div>
        <h1>模型配置 · {{ store.novel?.title || store.current }}</h1>
        <p>本书使用的 API 与每个 Agent 的模型，写入 <span class="mono">novels/{{ store.current }}/.env</span>，下次任务立即生效</p>
      </div>
      <div class="page-actions">
        <el-button @click="load">重置</el-button>
        <el-button type="primary" :loading="saving" @click="save" :disabled="!dirty">保存</el-button>
      </div>
    </header>

    <el-alert v-if="view && !view.env_supported" type="warning" show-icon :closable="false" class="block"
      title="本书 config.py 为旧版（模型名内嵌）" description="保存后会自动升级为 .env 驱动版，原文件备份为 config.py.bak，书名与卷结构保留。" />
    <el-alert v-else-if="dirty" type="info" :closable="false" class="block" title="有未保存的修改" />

    <section v-if="view" class="content-card block">
      <div class="card-heading"><div><h2>API 接入</h2><p>密钥只保存在本书 .env 与前端会话中，接口永不回传明文</p></div></div>
      <div class="api-grid">
        <div>
          <label class="field-label">API Key</label>
          <el-input v-model="form.api_key" type="password" show-password
                    :placeholder="view.api_key_masked ? `已设置 ${view.api_key_masked}，留空保持不变` : 'sk-…（必填）'" />
        </div>
        <div>
          <label class="field-label">Base URL</label>
          <el-input v-model="form.base_url" :placeholder="view.base_url || 'https://api.deepseek.com/v1'" />
          <div class="field-tip">OpenAI 兼容端点：DeepSeek / Kimi / 智谱 / 本地 ollama·LM Studio 均可</div>
        </div>
        <div class="quick-box">
          <label class="field-label">快速配置（覆盖右侧全部角色）</label>
          <div class="quick-row">
            <el-input v-model="form.quick_chat" placeholder="对话/创作用模型，如 deepseek-chat" />
            <el-input v-model="form.quick_reasoner" placeholder="推理/审阅用模型，如 deepseek-reasoner" />
          </div>
        </div>
        <div class="test-box">
          <label class="field-label">连接测试</label>
          <div class="row">
            <el-input v-model="form.test_model" placeholder="测试模型（默认 Writer）" style="width: 220px" />
            <el-button :loading="testing" @click="runTest">测试</el-button>
          </div>
          <div v-if="testResult" class="test-result" :class="testResult.ok ? 'ok' : 'fail'">
            <span v-if="testResult.ok">✓ {{ testResult.model }} · {{ testResult.latency_ms }}ms · 回复「{{ testResult.reply }}」</span>
            <span v-else>✕ {{ testResult.error || '失败' }}</span>
          </div>
        </div>
      </div>
    </section>

    <section v-if="view" class="content-card block">
      <div class="card-heading">
        <div><h2>各 Agent 模型</h2><p>留空 = 维持当前值；填「恢复默认」列建议模型可一键抄送</p></div>
        <el-tag :type="view.api_key_set ? 'success' : 'danger'" effect="plain">{{ view.api_key_set ? 'Key 已配置' : 'Key 未配置' }}</el-tag>
      </div>
      <table class="role-table">
        <thead><tr><th>Agent</th><th>当前生效</th><th class="env-col">.env 值</th><th>新值</th><th></th></tr></thead>
        <tbody>
          <tr v-for="role in view.roles" :key="role.attr">
            <td>
              <strong>{{ role.label }}</strong>
              <div class="mono muted env-name">{{ role.env }}</div>
            </td>
            <td><el-tag size="small" effect="plain">{{ role.model }}</el-tag></td>
            <td class="env-col mono muted">{{ role.env_value || '—' }}</td>
            <td>
              <el-input v-model="form.models[role.env]" size="small" :placeholder="role.model" style="width: 220px" />
            </td>
            <td><el-button size="small" link type="primary" @click="form.models[role.env] = role.default">默认</el-button></td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import { useNovelStore } from '../stores/novel'
import { api } from '../api'

const store = useNovelStore()
const route = useRoute()
const name = computed(() => route.params.name || store.current)
const view = ref(null)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const testResult = ref(null)
const form = reactive({ api_key: '', base_url: '', quick_chat: '', quick_reasoner: '', test_model: '', models: {} })

const dirty = computed(() => form.api_key || form.base_url || form.quick_chat || form.quick_reasoner
  || Object.values(form.models).some(v => v))

async function load() {
  loading.value = true
  try {
    view.value = await api.modelConfig(name.value)
    resetForm()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '配置加载失败')
  } finally { loading.value = false }
}
function resetForm() {
  Object.assign(form, { api_key: '', base_url: '', quick_chat: '', quick_reasoner: '', test_model: '', models: {} })
  testResult.value = null
}

async function save() {
  saving.value = true
  try {
    const quick = {}
    if (form.quick_chat) quick.chat_model = form.quick_chat
    if (form.quick_reasoner) quick.reasoner_model = form.quick_reasoner
    const models = {}
    for (const [k, v] of Object.entries(form.models)) if (v) models[k] = v
    const body = { models }
    if (form.api_key) body.api_key = form.api_key
    if (form.base_url) body.base_url = form.base_url
    if (Object.keys(quick).length) body.quick = quick
    const res = await api.saveModelConfig(name.value, body)
    view.value = res.view
    resetForm()
    ElMessage.success(res.upgraded_config ? '已保存，config.py 已升级为 env 驱动（备份 .bak）' : '已保存到本书 .env')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally { saving.value = false }
}

async function runTest() {
  testing.value = true
  testResult.value = null
  try {
    const body = {}
    if (form.test_model) body.model = form.test_model
    else {
      const w = Object.entries(form.models).find(([k]) => k === 'WRITER_MODEL')
      const wr = view.value.roles.find(r => r.env === 'WRITER_MODEL')
      body.model = w ? w[1] : wr?.model
    }
    if (form.api_key) body.api_key = form.api_key
    if (form.base_url) body.base_url = form.base_url
    testResult.value = await api.testModelConfig(name.value, body)
  } catch (e) {
    testResult.value = { ok: false, error: e.response?.data?.detail || '请求失败' }
  } finally { testing.value = false }
}

onMounted(load)
</script>

<style scoped>
.block { margin-bottom: 16px; }
.api-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.api-grid > div { min-width: 0; }
.field-label { display: block; margin-bottom: 7px; color: var(--text); font-size: 13px; font-weight: 600; }
.field-tip { margin-top: 5px; color: var(--muted); font-size: 12px; line-height: 1.4; }
.quick-box, .test-box { background: var(--surface-soft); padding: 16px; border-radius: var(--radius-sm); border: 1px solid var(--border-light); }
.quick-row { display: grid; gap: 8px; }
.test-result { margin-top: 10px; font-size: 13px; }
.test-result.ok { color: var(--primary); }
.test-result.fail { color: var(--danger); }
.role-table { width: 100%; border-collapse: collapse; }
.role-table th { text-align: left; padding: 8px 10px; color: var(--muted); font-size: 12px; border-bottom: 1px solid var(--border);}
.role-table td { padding: 9px 10px; border-bottom: 1px solid var(--border-light); font-size: 13px; vertical-align: middle; }
.env-name { font-size: 11px; }
.env-col { width: 180px; }
@media (max-width: 900px) { .api-grid { grid-template-columns: 1fr; } .env-col { display: none; } }
</style>
