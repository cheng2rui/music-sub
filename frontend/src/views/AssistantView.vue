<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  getAssistantCapabilities,
  getAssistantConversations,
  getAssistantMessages,
  sendAssistantMessage,
  prepareAssistantAction,
  prepareAssistantResultAction,
  confirmAssistantAction,
  cancelAssistantAction,
  createAssistantConversation,
  deleteAssistantConversation,
} from '@/api/index.js'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'
import { useThemeStore } from '@/stores/theme.js'
import { animalIslandIcons } from '@/utils/animalIsland.js'

const theme = useThemeStore()
const isIsland = computed(() => theme.current === 'island')
const conversations = ref([])
const messages = ref([])
const currentId = ref(null)
const input = ref('')
const loading = ref(false)
const caps = ref(null)
const errorText = ref('')
const pendingAction = ref(null)
const retryDraft = ref('')
const messagesEl = ref(null)
const quickPrompts = [
  { label: '失败任务', text: '/tasks failed' },
  { label: '曲库健康', text: '/health' },
  { label: '缺歌词', text: '/health missing_lyrics' },
  { label: '搜索 FLAC', text: '搜索 周杰伦 FLAC，PT 和在线都看一下' },
  { label: '最近日志', text: '读取最近日志，帮我看有没有错误' },
]

const enabled = computed(() => caps.value?.enabled)
const currentConversation = computed(() => conversations.value.find(c => c.id === currentId.value))

function showError(error, fallback = '操作失败') {
  errorText.value = error?.message || fallback
}

async function scrollToBottom() {
  await nextTick()
  const el = messagesEl.value
  if (el) el.scrollTop = el.scrollHeight
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
  scrollToBottom()
}

async function sendMessage(textOverride = '') {
  const override = typeof textOverride === 'string' ? textOverride : ''
  const text = (override || input.value).trim()
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
  } catch (e) {
    input.value = text
    if (e?.payload?.conversation_id) {
      currentId.value = e.payload.conversation_id
      if (e.payload.message) pushLocal('assistant', e.payload.message, { status: 'failed' })
      pendingAction.value = null
      await loadConversations()
      await loadMessages()
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

function useQuickPrompt(text) {
  if (loading.value || !enabled.value) return
  input.value = text
  scrollToBottom()
}

function sendQuickPrompt(text) {
  if (loading.value || !enabled.value) return
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
  if (Array.isArray(parsed?.candidates)) return parsed.candidates
  if (Array.isArray(parsed?.items)) return parsed.items
  if (message.tool_name === 'complete_album' && Array.isArray(parsed?.downloaded)) return parsed.downloaded
  return []
}

function toolSummary(message) {
  const parsed = parseToolResult(message)
  if (!parsed) return ''
  if (message.tool_name === 'get_system_status') return `版本 ${parsed.version || '-'} · 站点 ${parsed.sites_enabled?.length || 0} · 任务 ${parsed.tasks || 0}`
  if (message.tool_name === 'get_library_stats') return `曲目 ${parsed.tracks || 0} · 专辑 ${parsed.albums || 0} · ${parsed.total_hours || 0} 小时`
  if (Array.isArray(parsed.items)) return `${parsed.items.length} 条结果`
  if (message.tool_name === 'complete_album') return `本地已有 ${parsed.existing || 0} 首 · 候选 ${parsed.candidate_count ?? parsed.candidates?.length ?? 0} 首 · 已下载 ${parsed.downloaded?.length || 0} 首`
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

function cardBadges(item) {
  const badges = []
  if (item.site || item.source) badges.push({ text: item.site || item.source, color: 'blue' })
  if (item.score !== undefined) badges.push({ text: `评分 ${item.score}`, color: 'green' })
  if (item.status) badges.push({ text: item.status, color: item.status === 'failed' ? 'red' : 'dim' })
  if (item.source_type) badges.push({ text: item.source_type, color: item.source_type === 'pt' ? 'purple' : 'orange' })
  return badges
}

function itemActions(message, item) {
  if (item.download_tool && item.download_args) {
    return [
      { key: 'result-action', label: item.download_tool === 'download_torrent' ? '下载 PT' : '下载', variant: 'primary', actionKey: 'download' },
      { key: 'result-action', label: '订阅关键词', variant: 'ghost', actionKey: 'subscribe-keyword' }
    ]
  }
  if (message.tool_name === 'search_online') {
    return [
      { key: 'result-action', label: item.url ? '下载' : '解析下载', variant: 'primary', actionKey: 'download' },
      { key: 'result-action', label: '订阅歌曲', variant: 'ghost', actionKey: 'subscribe-song' },
      { key: 'result-action', label: '搜 PT', variant: 'ghost', actionKey: 'search-pt' }
    ]
  }
  if (message.tool_name === 'search_pt') {
    return [
      { key: 'result-action', label: '下载', variant: 'primary', actionKey: 'download' },
      { key: 'result-action', label: '订阅关键词', variant: 'ghost', actionKey: 'subscribe-keyword' }
    ]
  }
  if (message.tool_name === 'search_library') {
    return [
      { key: 'result-action', label: '预览补齐', variant: 'ghost', actionKey: 'complete-album-preview' },
      { key: 'result-action', label: '重刮专辑', variant: 'ghost', actionKey: 'rescrape-album' }
    ]
  }
  if (message.tool_name === 'complete_album') {
    return [
      { key: 'result-action', label: item.url ? '下载此曲' : '解析下载', variant: 'primary', actionKey: 'download' }
    ]
  }
  if (message.tool_name === 'query_library_health') {
    return [
      { key: 'result-action', label: '重刮专辑', variant: 'ghost', actionKey: 'rescrape-album' }
    ]
  }
  return []
}

async function sendItemAction(message, item, idx, action) {
  const title = cardTitle(item)
  const artist = item.artist || item.album_artist || ''
  const payload = JSON.stringify(item.download_args || item, null, 2)
  if ((action.key === 'result-action' && Number.isInteger(Number(message.id))) || (action.key === 'direct-tool' && action.toolName)) {
    loading.value = true
    errorText.value = ''
    try {
      const res = action.key === 'result-action'
        ? await prepareAssistantResultAction(Number(message.id), idx, action.actionKey || 'download')
        : await prepareAssistantAction(action.toolName, action.args || {}, currentId.value)
      currentId.value = res.conversation_id || currentId.value
      if (res.message) pushLocal('assistant', res.message)
      pendingAction.value = res.needs_confirm ? { id: res.action_id, calls: res.tool_calls || [] } : null
      await loadConversations()
      await loadMessages()
    } catch (e) {
      showError(e, '创建操作失败')
    } finally {
      loading.value = false
    }
    return
  }
  const prompts = {
    'subscribe-song': `创建歌曲订阅：${[title, artist].filter(Boolean).join(' ')}，质量优先 FLAC。`,
    'subscribe-keyword': `创建关键词订阅：${title}，质量优先 FLAC。`,
    'search-pt': `搜索 PT 资源：${[title, artist].filter(Boolean).join(' ')}，质量优先 FLAC。`,
    'rescrape-album': `重新刮削专辑：${item.artist || item.album_artist || item.suggested_album_artist || ''} - ${item.album || ''}`,
    'complete-album-preview': `预览补齐专辑：${item.artist || item.album_artist || item.suggested_album_artist || ''} - ${item.album || ''}`,
    'complete-album-download': `确认下载并补齐专辑：${item.artist || item.album_artist || item.suggested_album_artist || ''} - ${item.album || ''}`
  }
  sendMessage(prompts[action.key] || `${action.label}：${payload}`)
}

function previewDetails(call) { return call.preview?.details || [] }

watch(messages, () => scrollToBottom(), { deep: true })

onMounted(async () => {
  await loadCaps()
  await loadConversations()
  await loadActivity()
  await scrollToBottom()
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
          <i @click.stop="removeConversation(conv)"><img v-if="isIsland" :src="animalIslandIcons.close" alt="" class="animal-remove-icon" /><span v-else>×</span></i>
        </button>
      </div>
    </aside>

    <section class="chat-panel">
      <div class="chat-toolbar">
        <div>
          <div class="eyebrow">Music Sub Copilot</div>
          <h2>{{ currentConversation?.title || '音乐管理助手' }}</h2>
          <p>搜索、下载、订阅、治理和日志排查都可以直接在这里完成。</p>
          <div class="quick-prompts">
            <button v-for="prompt in quickPrompts" :key="prompt.label" type="button" :disabled="loading || !enabled" @click="sendQuickPrompt(prompt.text)">{{ prompt.label }}</button>
          </div>
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

      <div ref="messagesEl" class="messages">
        <div v-if="messages.length === 0" class="empty-state">
          <div class="empty-icon">🎧</div>
          <h3>从一个音乐任务开始</h3>
          <p>你可以直接搜索资源、查看任务、做曲库治理，也可以用下面的快捷入口。</p>
          <div class="empty-prompts">
            <button v-for="prompt in quickPrompts" :key="prompt.label" type="button" :disabled="loading || !enabled" @click="useQuickPrompt(prompt.text)">{{ prompt.text }}</button>
          </div>
        </div>
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
                    <div class="result-title-row">
                      <div class="result-title">{{ cardTitle(item) }}</div>
                      <div v-if="cardBadges(item).length" class="result-badges">
                        <AppBadge v-for="badge in cardBadges(item)" :key="`${badge.text}-${badge.color}`" :color="badge.color">{{ badge.text }}</AppBadge>
                      </div>
                    </div>
                    <div v-if="cardSubtitle(item)" class="result-subtitle">{{ cardSubtitle(item) }}</div>
                    <div v-if="cardMeta(item)" class="result-meta">{{ cardMeta(item) }}</div>
                    <div v-if="item.reasons?.length" class="result-reasons">{{ item.reasons.join('、') }}</div>
                    <div v-if="itemActions(msg, item).length" class="result-actions">
                      <AppButton
                        v-for="action in itemActions(msg, item)"
                        :key="action.key"
                        size="sm"
                        :variant="action.variant"
                        :disabled="loading"
                        @click="sendItemAction(msg, item, idx, action)"
                      >{{ action.label }}</AppButton>
                    </div>
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
        <div class="composer-box">
          <textarea v-model="input" placeholder="输入你的音乐管理需求... Shift+Enter 换行，Enter 发送" :disabled="loading || !enabled" @keydown.enter.exact.prevent="sendMessage" />
          <div class="composer-footer">
            <div class="composer-hint">{{ loading ? '正在执行，请稍候…' : 'Enter 发送 · Shift+Enter 换行' }}</div>
            <AppButton variant="primary" :loading="loading" :disabled="loading || !enabled || !input.trim()" @click="sendMessage()">发送</AppButton>
          </div>
        </div>
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
.chat-panel { display: flex; flex-direction: column; overflow: hidden; }
.chat-toolbar { padding: 16px 18px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.eyebrow { color: var(--accent); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; margin-bottom: 4px; }
.chat-toolbar h2 { margin: 0; font-size: 20px; }
.chat-toolbar p { margin: 4px 0 0; color: var(--text-dim); font-size: 13px; }
.quick-prompts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.quick-prompts button, .empty-prompts button { border: 1px solid var(--border); background: color-mix(in srgb, var(--accent) 8%, var(--surface)); color: var(--text); border-radius: 999px; padding: 6px 10px; font-size: 12px; cursor: pointer; transition: .15s ease; }
.quick-prompts button:hover:not(:disabled), .empty-prompts button:hover:not(:disabled) { border-color: var(--accent); transform: translateY(-1px); }
.quick-prompts button:disabled, .empty-prompts button:disabled { opacity: .5; cursor: not-allowed; }
.chat-toolbar-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.mobile-new-chat { display: none; }
.messages { flex: 1; overflow-y: auto; padding: 18px; display: flex; flex-direction: column; gap: 14px; scroll-behavior: smooth; }
.message { display: grid; grid-template-columns: 48px minmax(0, 1fr); gap: 10px; }
.message-role { color: var(--text-dim); font-size: 12px; padding-top: 8px; }
.message-content { white-space: pre-wrap; line-height: 1.55; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; overflow-x: auto; box-shadow: 0 8px 24px color-mix(in srgb, #000 5%, transparent); }
.message.user .message-content { background: color-mix(in srgb, var(--accent) 12%, transparent); border-color: color-mix(in srgb, var(--accent) 28%, var(--border)); }
.message.tool .message-content { font-size: 12px; color: var(--text-dim); }
.tool-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.tool-name { color: var(--accent); font-weight: 700; }
.tool-summary { color: var(--text-dim); }
.result-cards { display: grid; gap: 8px; margin: 8px 0; }
.result-card { display: grid; grid-template-columns: 38px 1fr; gap: 10px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px; background: linear-gradient(135deg, color-mix(in srgb, var(--surface) 88%, var(--accent)), var(--bg)); transition: .15s ease; }
.result-card:hover { border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); transform: translateY(-1px); }
.result-rank { color: var(--accent); font-weight: 800; font-variant-numeric: tabular-nums; }
.result-title-row { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
.result-title { color: var(--text); font-weight: 700; word-break: break-word; }
.result-badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; flex-shrink: 0; }
.result-subtitle, .result-meta, .result-reasons { margin-top: 3px; color: var(--text-dim); font-size: 12px; }
.result-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.raw-json { margin-top: 8px; color: var(--text-dim); }
.raw-json summary { cursor: pointer; }
pre { margin: 6px 0 0; white-space: pre-wrap; }
.empty-state { color: var(--text-dim); text-align: center; padding: 44px 20px; border: 1px dashed var(--border); border-radius: var(--radius-lg); background: color-mix(in srgb, var(--surface) 55%, transparent); }
.empty-icon { font-size: 42px; margin-bottom: 8px; }
.empty-state h3 { color: var(--text); margin: 0 0 6px; }
.empty-state p { margin: 0 auto 14px; max-width: 520px; line-height: 1.5; }
.empty-prompts { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
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
.composer { border-top: 1px solid var(--border); padding: 14px; background: color-mix(in srgb, var(--bg-elevated) 80%, transparent); }
.composer-box { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg); padding: 8px; transition: .15s ease; }
.composer-box:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent); }
.composer textarea { resize: none; width: 100%; min-height: 54px; max-height: 140px; border: 0; background: transparent; color: var(--text); padding: 4px 4px 8px; outline: none; box-sizing: border-box; }
.composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; border-top: 1px solid var(--border); padding-top: 8px; }
.composer-hint { color: var(--text-muted); font-size: 11px; }
@media (max-width: 900px) {
  .assistant-view { grid-template-columns: 1fr; padding: 12px; min-height: 0; }
  .conversation-panel { display: none; }
  .chat-panel { border-radius: 18px; }
  .chat-toolbar { padding: 12px; align-items: flex-start; }
  .chat-toolbar h2 { font-size: 17px; }
  .chat-toolbar p { font-size: 12px; line-height: 1.4; }
  .quick-prompts { overflow-x: auto; flex-wrap: nowrap; padding-bottom: 2px; }
  .quick-prompts button { flex-shrink: 0; }
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
  .composer { padding: 10px; }
  .composer textarea { min-height: 74px; }
  .composer-footer { align-items: stretch; }
  .composer-hint { display: none; }
  .result-title-row { flex-direction: column; gap: 6px; }
  .result-badges { justify-content: flex-start; }
}

@media (max-width: 430px) {
  .chat-toolbar { flex-direction: column; }
  .chat-toolbar-actions { width: 100%; flex-direction: row; justify-content: space-between; }
}
.animal-remove-icon { width: 16px; height: 16px; object-fit: contain; display: block; }
</style>
