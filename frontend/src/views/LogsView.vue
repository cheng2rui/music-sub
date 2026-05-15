<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getLogs, clearLogs } from '@/api/index.js'
import AppButton from '@/components/AppButton.vue'

const logs = ref([])
const total = ref(0)
const level = ref('')
const loading = ref(false)
let timer = null

async function loadLogs() {
  try {
    const params = { lines: 200 }
    if (level.value) params.level = level.value
    const data = await getLogs(params)
    logs.value = data.lines || []
    total.value = data.total || 0
  } catch (e) { console.error(e) }
}

async function handleClear() {
  if (!confirm('确定清空所有日志？')) return
  try {
    await clearLogs()
    logs.value = []
    total.value = 0
  } catch (e) { console.error(e) }
}

function logClass(line) {
  if (line.includes('ERROR')) return 'log-error'
  if (line.includes('WARNING')) return 'log-warn'
  return 'log-info'
}

onMounted(() => { loadLogs(); timer = setInterval(loadLogs, 15000) })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="logs-view">
    <div class="logs-toolbar">
      <div class="logs-info">共 {{ total }} 条日志</div>
      <div class="logs-actions">
        <select v-model="level" @change="loadLogs" class="level-select">
          <option value="">全部级别</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <AppButton variant="ghost" size="sm" @click="loadLogs">刷新</AppButton>
        <AppButton variant="danger" size="sm" @click="handleClear">清空</AppButton>
      </div>
    </div>

    <div class="log-output">
      <div v-if="logs.length === 0" class="empty-text">暂无日志</div>
      <pre v-else v-for="(line, i) in logs" :key="i" :class="['log-line', logClass(line)]">{{ line }}</pre>
    </div>
  </div>
</template>

<style scoped>
.logs-view { padding: 24px; display: flex; flex-direction: column; gap: 16px; height: 100%; overflow: hidden; }
.logs-toolbar { display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
.logs-info { font-size: 13px; color: var(--text-dim); }
.logs-actions { display: flex; gap: 8px; align-items: center; }
.level-select { min-width: 120px; }
.log-output {
  flex: 1;
  overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.7;
}
.empty-text { color: var(--text-dim); padding: 20px 0; }
.log-line { white-space: pre-wrap; word-break: break-all; margin: 0; padding: 2px 0; }
.log-error { color: var(--danger); }
.log-warn { color: var(--warning); }
.log-info { color: var(--text); }

@media (max-width: 768px) {
  .logs-view {
    padding: 0;
    gap: 12px;
  }
  .logs-toolbar {
    align-items: flex-start;
    gap: 10px;
    flex-direction: column;
  }
  .logs-actions {
    width: 100%;
    gap: 6px;
  }
  .level-select {
    min-width: 0;
    flex: 1;
  }
  .log-output {
    padding: 10px;
    font-size: 11px;
    line-height: 1.6;
    border-radius: var(--radius-md);
  }
}
</style>