<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  getAssistantCapabilities,
  getAssistantActivity,
  getAssistantConversations,
  getAssistantMessages,
  sendAssistantMessage,
  confirmAssistantAction,
  cancelAssistantAction,
  createAssistantConversation,
  deleteAssistantConversation,
} from '@/api/index.js'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'

const conversations = ref([])
const messages = ref([])
const currentId = ref(null)
const input = ref('')
const loading = ref(false)
const caps = ref(null)
const errorText = ref('')
const pendingAction = ref(null)
const activity = ref([])
const retryDraft = ref('')

const enabled = computed(() => caps.value?.enabled)
const groupedTools = computed(() => {
  const groups = {}
  for (const tool of caps.value?.tool_catalog || []) {
    const group = tool.group || '其他'
    groups[group] = groups[group] || []
    groups[group].push(tool)
  }
  return groups
})

function showError(error, fallback = '操作失败') {
  errorText.value = error?.message || fallback
}

async function loadCaps() {
  try { caps.value = await getAssistantCapabilities() }
  catch (e) { showError(e, '加载助手配置失败') }
}

async function loadConversations() {
  try {
    conversations.value = await getAssistantConversations()
    if (!currentId.value && conversations.value.length) {
      currentId.value = conversations.value[0].id
      await loadMessages()
    }
  } catch (e) { showError(e, '加载对话失败') }
}

async function loadMessages() {
  if (!currentId.value) {
    messages.value = []
    return
  }
  try { messages.value = await getAssistantMessages(currentId.value) }
  catch (e) { showError(e, '加载消息失败') }
}

async function loadActivity() {
  try {
    const data = await getAssistantActivity(30)
    activity.value = data.items || []
  } catch (e) { console.warn('load assistant activity failed', e) }
}

async function newConversation() {
  if (loading.value) return
  try {
    const conv = await createAssistantConversation('新对话')
    currentId.value = conv.id
    input.value = ''
    retryDraft.value = ''
    pendingAction.value = null
    await loadConversations()
    await loadMessages()
  } catch (e) { showError(e, '创建对话失败') }
}

async function removeConversation(conv) {
  if (!confirm(`删除对话「${conv.title || conv.id}」？`)) return
  await deleteAssistantConversation(conv.id)
  if (currentId.value === conv.id) currentId.value = null
  await loadConversations()
  if (!currentId.value && conversations.value.length) currentId.value = conversations.value[0].id
  await loadMessages()
}

async function selectConversation(id) {
  if (loading.value) return
  currentId.value = id
  pendingAction.value = null
  await loadMessages()
}

function pushLocal(role, content, extra = {}) {
  messages.value.push({ id: `local-${Date.now()}-${Math.random()}`, role, content, created_at: new Date().toISOString(), ...extra })
}

async function sendMessage(textOverride = '') {
  const text = (textOverride || input.value).trim()
  if (!text || loading.value) return
  retryDraft.value = text
  input.value = ''
  errorText.value = ''
  pushLocal('user', text)
  loading.value = true
  try {
    const res = await sendAssistantMessage(text, currentId.value)
    currentId.value = res.conversation_id
    pushLocal('assistant', res.message || '助手没有返回文字。')
    pendingAction.value = res.needs_confirm ? { id: res.action_id, calls: res.tool_calls || [] } : null
    retryDraft.value = ''
    await loadConversations()
    await loadMessages()
    await loadActivity()
  } catch (e) {
    input.value = text
    if (e?.payload?.conversation_id) {
      currentId.value = e.payload.conversation_id
      if (e.payload.message) pushLocal('assistant', e.payload.message, { status: 'failed' })
      pendingAction.value = null
      await loadConversations()
      await loadMessages()
      await loadActivity()
    }
    showError(e, '发送失败')
  } finally {
    loading.value = false
  }
}

function retryLastMessage() {
  const text = retryDraft.value || input.value
  sendMessage(text)
}

async function handleConfirm() {
  if (!pendingAction.value?.id) return
  loading.value = true
  try {
    const res = await confirmAssistantAction(pendingAction.value.id)
    pushLocal('assistant', res.message || (res.ok ? '已执行。' : '执行失败。'))
    pendingAction.value = null
    await loadMessages()
    await loadActivity()
  } catch (e) {
    showError(e, '确认失败')
  } finally {
    loading.value = false
  }
}

async function handleCancel() {
  if (!pendingAction.value?.id || loading.value) return
  loading.value = true
  try {
    await cancelAssistantAction(pendingAction.value.id)
    pendingAction.value = null
    await loadMessages()
    await loadActivity()
  } catch (e) { showError(e, '取消失败') }
  finally { loading.value = false }
}

function roleLabel(role) { return role === 'user' ? '你' : role === 'tool' ? '工具' : '助手' }

function parseToolResult(message) {
  if (!message.tool_result_json) return null
  try { return JSON.parse(message.tool_result_json) } catch { return null }
}

function formatToolResult(message) {
  const parsed = parseToolResult(message)
  if (parsed) return JSON.stringify(parsed, null, 2).slice(0, 1800)
  return (message.tool_result_json || '').slice(0, 1800)
}

function formatSizeGb(value) {
  if (value === null || value === undefined || value === '') return '-'
  const n = Number(value)
  return Number.isFinite(n) ? `${n} GB` : String(value)
}

function toolItems(message) {
  const parsed = parseToolResult(message)
  return Array.isArray(parsed?.items) ? parsed.items : []
}

function toolSummary(message) {
  const parsed = parseToolResult(message)
  if (!parsed) return ''
  if (message.tool_name === 'get_system_status') return `版本 ${parsed.version || '-'} · 站点 ${parsed.sites_enabled?.length || 0} · 任务 ${parsed.tasks || 0}`
  if (message.tool_name === 'get_library_stats') return `曲目 ${parsed.tracks || 0} · 专辑 ${parsed.albums || 0} · ${parsed.total_hours || 0} 小时`
  if (Array.isArray(parsed.items)) return `${parsed.items.length} 条结果`
  return ''
}

function cardTitle(item) { return item.title || item.name || item.keyword || `${item.artist || item.album_artist || ''} ${item.album || ''}`.trim() || '-' }
function cardSubtitle(item) { return [item.artist, item.album, item.site || item.source, item.status].filter(Boolean).join(' · ') }
function cardMeta(item) {
  const parts = []
  if (item.size_gb !== undefined) parts.push(formatSizeGb(item.size_gb))
  if (item.seeders !== undefined) parts.push(`做种 ${item.seeders}`)
  if (item.leechers !== undefined) parts.push(`下载 ${item.leechers}`)
  if (item.quality) parts.push(item.quality)
  if (item.format) parts.push(item.format)
  if (item.enabled !== undefined) parts.push(item.enabled ? '启用' : '停用')
  return parts.join(' · ')
}

function previewDetails(call) { return call.preview?.details || [] }
function riskColor(risk) { return risk === 'high' ? 'red' : risk === 'medium' ? 'orange' : 'green' }
function activityTime(item) { return item.updated_at || item.created_at ? new Date(item.updated_at || item.created_at).toLocaleString() : '-' }
function activityStatusColor(status) { return status === 'failed' ? 'red' : status === 'pending' ? 'orange' : status === 'cancelled' ? 'dim' : 'green' }

onMounted(async () => {
  await loadCaps()
  await loadConversations()
  await loadActivity()
})
</script>

<template>
  <div class="assistant-view">
    <aside class="conversation-panel">
      <div class="panel-head">
        <div>
          <h3>智能助手</h3>
          <div class="muted">{{ caps?.model || '未配置模型' }}</div>
        </div>
        <AppButton size="sm" variant="primary" :disabled="loading" @click="newConversation">新对话</AppButton>
      </div>
      <div v-if="!enabled" class="warning-box">助手未启用：到设置里开启 Assistant 并填写模型配置。</div>
      <div class="conversation-list">
        <button v-for="conv in conversations" :key="conv.id" class="conversation-item" :class="{ active: conv.id === currentId }" @click="selectConversation(conv.id)">
          <span>{{ conv.title || '新对话' }}</span>
          <small>{{ new Date(conv.updated_at).toLocaleString() }}</small>
          <i @click.stop="removeConversation(conv)">×</i>
        </button>
      </div>
      <details class="tool-catalog">
        <summary>工具能力</summary>
        <div v-for="(items, group) in groupedTools" :key="group" class="tool-group">
          <strong>{{ group }}</strong>
          <div v-for="tool in items" :key="tool.name" class="tool-chip" :class="{ disabled: !tool.enabled }">
            <span>{{ tool.name }}</span>
            <AppBadge :color="tool.enabled ? riskColor(tool.risk) : 'dim'">{{ tool.enabled ? tool.risk : 'off' }}</AppBadge>
          </div>
        </div>
      </details>
      <details class="activity-panel" open>
        <summary>活动记录</summary>
        <div v-if="!activity.length" class="activity-empty">暂无活动</div>
        <div v-for="item in activity.slice(0, 12)" :key="`${item.type}-${item.id}`" class="activity-item">
          <div class="activity-main">
            <span>{{ item.tool_name }}</span>
            <AppBadge :color="activityStatusColor(item.status)">{{ item.status }}</AppBadge>
          </div>
          <div class="activity-summary">{{ item.summary }}</div>
          <div class="activity-time">{{ activityTime(item) }}</div>
        </div>
      </details>
    </aside>

    <section class="chat-panel">
      <div class="chat-toolbar">
        <div>
          <h2>Music Sub Copilot</h2>
          <p>可以问：帮我搜周杰伦 FLAC、最近任务状态、库里有没有稻香、列出订阅。</p>
        </div>
        <div class="chat-toolbar-actions">
          <AppButton class="mobile-new-chat" size="sm" variant="ghost" :disabled="loading" @click="newConversation">新对话</AppButton>
          <AppBadge :color="enabled ? 'green' : 'orange'">{{ enabled ? '已启用' : '未启用' }}</AppBadge>
        </div>
      </div>

      <div v-if="errorText" class="error-text">
        <span>{{ errorText }}</span>
        <AppButton v-if="retryDraft" size="sm" variant="ghost" :disabled="loading" @click="retryLastMessage">重试</AppButton>
      </div>

      <div class="messages">
        <div v-if="messages.length === 0" class="empty-text">暂无消息，试试“搜索周杰伦 FLAC，优先猫站”。</div>
        <div v-for="msg in messages" :key="msg.id" class="message" :class="msg.role">
          <div class="message-role">{{ roleLabel(msg.role) }}</div>
          <div class="message-content">
            <template v-if="msg.role === 'tool'">
              <div class="tool-head">
                <span class="tool-name">{{ msg.tool_name }}</span>
                <span class="tool-summary">{{ toolSummary(msg) }}</span>
              </div>
              <div v-if="toolItems(msg).length" class="result-cards">
                <div v-for="(item, idx) in toolItems(msg).slice(0, 8)" :key="idx" class="result-card">
                  <div class="result-rank">#{{ idx + 1 }}</div>
                  <div class="result-main">
                    <div class="result-title">{{ cardTitle(item) }}</div>
                    <div v-if="cardSubtitle(item)" class="result-subtitle">{{ cardSubtitle(item) }}</div>
                    <div v-if="cardMeta(item)" class="result-meta">{{ cardMeta(item) }}</div>
                    <div v-if="item.reasons?.length" class="result-reasons">{{ item.reasons.join('、') }}</div>
                  </div>
                </div>
              </div>
              <details class="raw-json">
                <summary>原始结果</summary>
                <pre>{{ formatToolResult(msg) }}</pre>
              </details>
            </template>
            <template v-else>{{ msg.content }}</template>
          </div>
        </div>
        <div v-if="loading" class="message assistant loading-row">
          <div class="message-role">助手</div>
          <div class="message-content">正在思考/调用工具，请稍候…</div>
        </div>
      </div>

      <div v-if="pendingAction" class="confirm-card">
        <strong>需要确认操作</strong>
        <div v-for="call in pendingAction.calls" :key="call.id" class="confirm-line">
          <div class="confirm-summary">{{ call.preview?.summary || call.summary || call.name }}</div>
          <div class="confirm-effect">{{ call.preview?.effect || `风险 ${call.risk}` }}</div>
          <div v-if="previewDetails(call).length" class="confirm-grid">
            <div v-for="d in previewDetails(call)" :key="d.label" class="confirm-detail">
              <span>{{ d.label }}</span>
              <strong>{{ d.value }}</strong>
            </div>
          </div>
          <details class="raw-json"><summary>参数</summary><pre>{{ JSON.stringify(call.args || {}, null, 2).slice(0, 1200) }}</pre></details>
        </div>
        <div class="confirm-actions">
          <AppButton variant="ghost" :disabled="loading" @click="handleCancel">取消</AppButton>
          <AppButton variant="danger" :loading="loading" @click="handleConfirm">确认执行</AppButton>
        </div>
      </div>

      <div class="composer">
        <textarea v-model="input" placeholder="输入你的音乐管理需求..." :disabled="loading || !enabled" @keydown.enter.exact.prevent="sendMessage" />
        <AppButton variant="primary" :loading="loading" :disabled="loading || !enabled || !input.trim()" @click="sendMessage">发送</AppButton>
      </div>
    </section>
  </div>
</template>

<style scoped>
.assistant-view { height: 100%; display: grid; grid-template-columns: 300px 1fr; gap: 16px; padding: 20px; overflow: hidden; }
.conversation-panel, .chat-panel { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-lg); min-height: 0; }
.conversation-panel { padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.panel-head h3 { margin: 0; font-size: 16px; }
.muted { color: var(--text-dim); font-size: 12px; }
.warning-box { color: var(--warning); background: color-mix(in srgb, var(--warning) 12%, transparent); border: 1px solid color-mix(in srgb, var(--warning) 35%, transparent); border-radius: var(--radius-md); padding: 10px; font-size: 12px; }
.conversation-list { overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.conversation-item { text-align: left; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); color: var(--text); padding: 10px; cursor: pointer; position: relative; }
.conversation-item.active { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); }
.conversation-item span { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 18px; }
.conversation-item small { color: var(--text-dim); font-size: 11px; }
.conversation-item i { position: absolute; right: 8px; top: 8px; font-style: normal; color: var(--text-dim); }
.tool-catalog, .activity-panel { border-top: 1px solid var(--border); padding-top: 10px; color: var(--text-dim); font-size: 12px; }
.tool-catalog summary, .activity-panel summary { cursor: pointer; color: var(--text); font-weight: 650; }
.tool-group { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.tool-chip { display: flex; align-items: center; justify-content: space-between; gap: 8px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 6px 8px; background: var(--surface); }
.tool-chip.disabled { opacity: .55; }
.tool-chip span { color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.activity-item { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px; background: var(--surface); margin-top: 8px; }
.activity-main { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.activity-main span { color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.activity-summary { color: var(--text-dim); margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.activity-time, .activity-empty { color: var(--text-muted); margin-top: 4px; font-size: 11px; }
.chat-panel { display: flex; flex-direction: column; overflow: hidden; }
.chat-toolbar { padding: 16px 18px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.chat-toolbar h2 { margin: 0; font-size: 20px; }
.chat-toolbar p { margin: 4px 0 0; color: var(--text-dim); font-size: 13px; }
.chat-toolbar-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.mobile-new-chat { display: none; }
.messages { flex: 1; overflow-y: auto; padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.message { display: grid; grid-template-columns: 48px minmax(0, 1fr); gap: 10px; }
.message-role { color: var(--text-dim); font-size: 12px; padding-top: 8px; }
.message-content { white-space: pre-wrap; line-height: 1.55; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; overflow-x: auto; }
.message.user .message-content { background: color-mix(in srgb, var(--accent) 12%, transparent); }
.message.tool .message-content { font-size: 12px; color: var(--text-dim); }
.tool-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.tool-name { color: var(--accent); font-weight: 700; }
.tool-summary { color: var(--text-dim); }
.result-cards { display: grid; gap: 8px; margin: 8px 0; }
.result-card { display: grid; grid-template-columns: 38px 1fr; gap: 10px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px; background: var(--bg); }
.result-rank { color: var(--accent); font-weight: 700; }
.result-title { color: var(--text); font-weight: 650; }
.result-subtitle, .result-meta, .result-reasons { margin-top: 3px; color: var(--text-dim); font-size: 12px; }
.raw-json { margin-top: 8px; color: var(--text-dim); }
.raw-json summary { cursor: pointer; }
pre { margin: 6px 0 0; white-space: pre-wrap; }
.empty-text { color: var(--text-dim); text-align: center; padding: 40px; }
.error-text { margin: 12px 18px 0; color: var(--danger); display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent); border-radius: var(--radius-md); padding: 8px 10px; background: color-mix(in srgb, var(--danger) 8%, transparent); }
.loading-row .message-content { color: var(--text-dim); }
.confirm-card { margin: 0 18px 12px; padding: 12px; border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent); border-radius: var(--radius-md); background: color-mix(in srgb, var(--danger) 8%, transparent); }
.confirm-line { color: var(--text-dim); margin-top: 8px; font-size: 13px; }
.confirm-summary { color: var(--text); font-weight: 700; }
.confirm-effect { margin-top: 4px; color: var(--warning); }
.confirm-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
.confirm-detail { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px; background: var(--bg); }
.confirm-detail span { display: block; color: var(--text-dim); font-size: 11px; }
.confirm-detail strong { display: block; color: var(--text); margin-top: 2px; word-break: break-word; }
.confirm-actions { margin-top: 10px; display: flex; justify-content: flex-end; gap: 8px; }
.composer { border-top: 1px solid var(--border); padding: 14px; display: grid; grid-template-columns: 1fr auto; gap: 10px; }
.composer textarea { resize: none; min-height: 46px; max-height: 120px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg); color: var(--text); padding: 10px 12px; outline: none; }
@media (max-width: 900px) {
  .assistant-view { grid-template-columns: 1fr; padding: 12px; min-height: 0; }
  .conversation-panel { display: none; }
  .chat-panel { border-radius: 18px; }
  .chat-toolbar { padding: 12px; align-items: flex-start; }
  .chat-toolbar h2 { font-size: 17px; }
  .chat-toolbar p { font-size: 12px; line-height: 1.4; }
  .chat-toolbar-actions { flex-direction: column; align-items: flex-end; }
  .mobile-new-chat { display: inline-flex; }
  .messages { padding: 12px; gap: 10px; }
  .message { grid-template-columns: 1fr; gap: 4px; }
  .message-role { padding: 0 2px; font-size: 11px; }
  .message-content { padding: 9px 10px; border-radius: 14px; }
  .result-card { grid-template-columns: 28px minmax(0, 1fr); padding: 8px; }
  .confirm-card { margin: 0 12px 10px; }
  .confirm-grid { grid-template-columns: 1fr; }
  .confirm-actions { justify-content: stretch; }
  .confirm-actions button { flex: 1; }
  .composer { padding: 10px; grid-template-columns: 1fr; }
  .composer textarea { min-height: 74px; }
}

@media (max-width: 430px) {
  .chat-toolbar { flex-direction: column; }
  .chat-toolbar-actions { width: 100%; flex-direction: row; justify-content: space-between; }
}
</style>
