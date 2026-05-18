<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  getAssistantCapabilities,
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

const enabled = computed(() => caps.value?.enabled)

async function loadCaps() {
  caps.value = await getAssistantCapabilities()
}

async function loadConversations() {
  conversations.value = await getAssistantConversations()
  if (!currentId.value && conversations.value.length) {
    currentId.value = conversations.value[0].id
    await loadMessages()
  }
}

async function loadMessages() {
  if (!currentId.value) {
    messages.value = []
    return
  }
  messages.value = await getAssistantMessages(currentId.value)
}

async function newConversation() {
  const conv = await createAssistantConversation('新对话')
  currentId.value = conv.id
  input.value = ''
  pendingAction.value = null
  await loadConversations()
  await loadMessages()
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
  currentId.value = id
  pendingAction.value = null
  await loadMessages()
}

function pushLocal(role, content, extra = {}) {
  messages.value.push({ id: `local-${Date.now()}-${Math.random()}`, role, content, created_at: new Date().toISOString(), ...extra })
}

async function sendMessage() {
  const text = input.value.trim()
  if (!text || loading.value) return
  input.value = ''
  errorText.value = ''
  pushLocal('user', text)
  loading.value = true
  try {
    const res = await sendAssistantMessage(text, currentId.value)
    currentId.value = res.conversation_id
    pushLocal('assistant', res.message)
    pendingAction.value = res.needs_confirm ? { id: res.action_id, calls: res.tool_calls || [] } : null
    await loadConversations()
    await loadMessages()
  } catch (e) {
    errorText.value = e.message || '发送失败'
  } finally {
    loading.value = false
  }
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
    alert(e.message || '确认失败')
  } finally {
    loading.value = false
  }
}

async function handleCancel() {
  if (!pendingAction.value?.id) return
  await cancelAssistantAction(pendingAction.value.id)
  pendingAction.value = null
  await loadMessages()
}

function roleLabel(role) {
  return role === 'user' ? '你' : role === 'tool' ? '工具' : '助手'
}

function formatToolResult(message) {
  if (!message.tool_result_json) return ''
  try {
    return JSON.stringify(JSON.parse(message.tool_result_json), null, 2).slice(0, 1200)
  } catch {
    return message.tool_result_json.slice(0, 1200)
  }
}

onMounted(async () => {
  await loadCaps()
  await loadConversations()
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
        <AppButton size="sm" variant="primary" @click="newConversation">新对话</AppButton>
      </div>
      <div v-if="!enabled" class="warning-box">助手未启用：到设置里开启 Assistant 并填写 OpenAI-compatible 模型。</div>
      <div class="conversation-list">
        <button
          v-for="conv in conversations"
          :key="conv.id"
          class="conversation-item"
          :class="{ active: conv.id === currentId }"
          @click="selectConversation(conv.id)"
        >
          <span>{{ conv.title || '新对话' }}</span>
          <small>{{ new Date(conv.updated_at).toLocaleString() }}</small>
          <i @click.stop="removeConversation(conv)">×</i>
        </button>
      </div>
    </aside>

    <section class="chat-panel">
      <div class="chat-toolbar">
        <div>
          <h2>Music Sub Copilot</h2>
          <p>可以问：帮我搜周杰伦 FLAC、最近任务状态、库里有没有稻香、列出订阅。</p>
        </div>
        <AppBadge :color="enabled ? 'green' : 'orange'">{{ enabled ? '已启用' : '未启用' }}</AppBadge>
      </div>

      <div v-if="errorText" class="error-text">{{ errorText }}</div>

      <div class="messages">
        <div v-if="messages.length === 0" class="empty-text">暂无消息，试试“搜索周杰伦 FLAC，优先猫站”。</div>
        <div v-for="msg in messages" :key="msg.id" class="message" :class="msg.role">
          <div class="message-role">{{ roleLabel(msg.role) }}</div>
          <div class="message-content">
            <template v-if="msg.role === 'tool'">
              <div class="tool-name">{{ msg.tool_name }}</div>
              <pre>{{ formatToolResult(msg) }}</pre>
            </template>
            <template v-else>{{ msg.content }}</template>
          </div>
        </div>
      </div>

      <div v-if="pendingAction" class="confirm-card">
        <strong>需要确认操作</strong>
        <div v-for="call in pendingAction.calls" :key="call.id" class="confirm-line">
          <div>{{ call.summary || call.name }} · 风险 {{ call.risk }}</div>
          <pre>{{ JSON.stringify(call.args || {}, null, 2).slice(0, 800) }}</pre>
        </div>
        <div class="confirm-actions">
          <AppButton variant="ghost" @click="handleCancel">取消</AppButton>
          <AppButton variant="danger" :loading="loading" @click="handleConfirm">确认执行</AppButton>
        </div>
      </div>

      <div class="composer">
        <textarea
          v-model="input"
          placeholder="输入你的音乐管理需求..."
          :disabled="loading"
          @keydown.enter.exact.prevent="sendMessage"
        />
        <AppButton variant="primary" :loading="loading" :disabled="!input.trim()" @click="sendMessage">发送</AppButton>
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
.chat-toolbar h2 { margin: 0; font-size: 20px; }
.chat-toolbar p { margin: 4px 0 0; color: var(--text-dim); font-size: 13px; }
.messages { flex: 1; overflow-y: auto; padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.message { display: grid; grid-template-columns: 48px minmax(0, 1fr); gap: 10px; }
.message-role { color: var(--text-dim); font-size: 12px; padding-top: 8px; }
.message-content { white-space: pre-wrap; line-height: 1.55; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; overflow-x: auto; }
.message.user .message-content { background: color-mix(in srgb, var(--accent) 12%, transparent); }
.message.tool .message-content { font-size: 12px; color: var(--text-dim); }
.tool-name { color: var(--accent); font-weight: 600; margin-bottom: 6px; }
pre { margin: 0; white-space: pre-wrap; }
.empty-text { color: var(--text-dim); text-align: center; padding: 40px; }
.error-text { margin: 12px 18px 0; color: var(--danger); }
.confirm-card { margin: 0 18px 12px; padding: 12px; border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent); border-radius: var(--radius-md); background: color-mix(in srgb, var(--danger) 8%, transparent); }
.confirm-line { color: var(--text-dim); margin-top: 6px; font-size: 13px; }
.confirm-actions { margin-top: 10px; display: flex; justify-content: flex-end; gap: 8px; }
.composer { border-top: 1px solid var(--border); padding: 14px; display: grid; grid-template-columns: 1fr auto; gap: 10px; }
.composer textarea { resize: none; min-height: 46px; max-height: 120px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg); color: var(--text); padding: 10px 12px; outline: none; }
@media (max-width: 900px) { .assistant-view { grid-template-columns: 1fr; padding: 12px; } .conversation-panel { display: none; } }
</style>
