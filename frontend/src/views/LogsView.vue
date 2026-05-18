<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { getLogs, clearLogs } from '@/api/index.js'
import AppButton from '@/components/AppButton.vue'

const logs = ref([])
const total = ref(0)
const level = ref('')
const loading = ref(false)
const quickFilter = ref('')
let timer = null

const quickFilters = [
  { key: '', label: '全部', hint: '' },
  { key: 'ERROR', label: '错误', hint: 'ERROR / Exception / Traceback' },
  { key: 'WARNING', label: '警告', hint: 'WARNING / warn' },
  { key: 'scraper', label: '刮削', hint: 'scrape / scraper / tagger' },
  { key: 'qb', label: 'qB', hint: 'qb / qBittorrent / tracker' },
  { key: 'task', label: '任务', hint: 'task / download / pipeline' },
  { key: 'assistant', label: '助手', hint: 'assistant / tool / llm' },
]

const filteredLogs = computed(() => {
  const key = quickFilter.value
  if (!key) return logs.value
  const lower = key.toLowerCase()
  if (key === 'ERROR') return logs.value.filter(line => /ERROR|Exception|Traceback|failed/i.test(line))
  if (key === 'WARNING') return logs.value.filter(line => /WARNING|WARN|warning/i.test(line))
  if (key === 'qb') return logs.value.filter(line => /qb|qbittorrent|tracker|torrent/i.test(line))
  if (key === 'scraper') return logs.value.filter(line => /scrape|scraper|tagger|lyrics|cover/i.test(line))
  if (key === 'task') return logs.value.filter(line => /task|download|pipeline|organize|cleanup/i.test(line))
  if (key === 'assistant') return logs.value.filter(line => /assistant|tool|llm|provider/i.test(line))
  return logs.value.filter(line => line.toLowerCase().includes(lower))
})

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
  if (/ERROR|Exception|Traceback|failed/i.test(line)) return 'log-error'
  if (/WARNING|WARN|warning/i.test(line)) return 'log-warn'
  if (/assistant|llm|tool/i.test(line)) return 'log-assistant'
  if (/qb|qbittorrent|tracker|torrent/i.test(line)) return 'log-qb'
  if (/scrape|scraper|tagger|lyrics|cover/i.test(line)) return 'log-scraper'
  return 'log-info'
}

function setQuickFilter(key) {
  quickFilter.value = key
}

onMounted(() => { loadLogs(); timer = setInterval(loadLogs, 15000) })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="logs-view">
    <div class="logs-toolbar">
      <div class="logs-info">
        <strong>运行日志</strong>
        <span>共 {{ total }} 条 · 当前显示 {{ filteredLogs.length }} 条</span>
      </div>
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

    <div class="quick-filters" aria-label="日志快捷过滤">
      <button
        v-for="item in quickFilters"
        :key="item.key || 'all'"
        type="button"
        class="filter-chip"
        :class="{ active: quickFilter === item.key }"
        :title="item.hint"
        @click="setQuickFilter(item.key)"
      >{{ item.label }}</button>
    </div>

    <div class="log-output">
      <div v-if="logs.length === 0" class="empty-text">暂无日志</div>
      <div v-else-if="filteredLogs.length === 0" class="empty-text">当前过滤条件没有匹配日志</div>
      <pre v-else v-for="(line, i) in filteredLogs" :key="i" :class="['log-line', logClass(line)]">{{ line }}</pre>
    </div>
  </div>
</template>

<style scoped>
.logs-view { padding: 24px; display: flex; flex-direction: column; gap: 16px; height: 100%; overflow: hidden; }
.logs-toolbar { display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
.logs-info { display: flex; flex-direction: column; gap: 2px; font-size: 13px; color: var(--text-dim); }
.logs-info strong { color: var(--text); font-size: 16px; }
.logs-actions { display: flex; gap: 8px; align-items: center; }
.quick-filters { display: flex; flex-wrap: wrap; gap: 8px; }
.filter-chip { border: 1px solid var(--border); background: var(--surface); color: var(--text-dim); border-radius: 999px; padding: 7px 11px; font-size: 12px; font-weight: 700; cursor: pointer; }
.filter-chip:hover, .filter-chip.active { color: var(--text); border-color: var(--accent); background: color-mix(in srgb, var(--accent) 13%, var(--surface)); }
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
.log-qb { color: var(--info); }
.log-scraper { color: var(--accent); }
.log-assistant { color: color-mix(in srgb, var(--accent) 72%, var(--text)); }

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
  .quick-filters { flex-wrap: nowrap; overflow-x: auto; padding-bottom: 2px; scrollbar-width: none; }
  .quick-filters::-webkit-scrollbar { display: none; }
  .filter-chip { flex: 0 0 auto; }
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