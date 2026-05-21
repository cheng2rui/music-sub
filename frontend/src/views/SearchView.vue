<script setup>
import { computed, onMounted, toRefs } from 'vue'
import { searchCandidates, downloadTorrent, downloadOnlineSong } from '@/api/index.js'
import { useSearchCacheStore } from '@/stores/searchCache.js'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'

const cache = useSearchCacheStore()
const {
  keyword,
  searchType,
  quality,
  formatFilter,
  sortBy,
  sourceFilter,
  siteFilter,
  onlineSourceFilter,
  loading,
  downloading,
  downloadMessage,
  lastResp,
  history,
} = toRefs(cache.pt)

const sites = computed(() => lastResp.value?.pt?.sites || [])
const queries = computed(() => lastResp.value?.pt?.queries || [])
const total = computed(() => lastResp.value?.total || 0)
const ptCount = computed(() => lastResp.value?.pt?.count || 0)
const onlineCount = computed(() => lastResp.value?.online?.count || 0)
const sourceSummary = computed(() => {
  const map = new Map()
  for (const item of lastResp.value?.candidates || []) {
    if (item.source_type !== 'online') continue
    const source = item.source || 'online'
    map.set(source, (map.get(source) || 0) + 1)
  }
  return Array.from(map.entries()).map(([source, count]) => ({ source, count }))
})
const notices = computed(() => {
  if (!lastResp.value) return []
  const items = []
  const ptError = lastResp.value?.pt?.error
  const onlineError = lastResp.value?.online?.error
  if (ptError) items.push({ type: 'warn', text: `PT 搜索部分失败：${ptError}` })
  if (onlineError) items.push({ type: 'warn', text: `在线音乐搜索部分失败：${onlineError}` })
  if (!ptError && !onlineError && total.value === 0) items.push({ type: 'muted', text: '没有找到候选，可以换关键词或放宽质量条件。' })
  return items
})

const filteredResults = computed(() => {
  const list = (lastResp.value?.candidates || []).slice()
  const filtered = list.filter(item => {
    if (sourceFilter.value !== 'all' && item.source_type !== sourceFilter.value) return false
    if (item.source_type === 'pt' && siteFilter.value && item.source !== siteFilter.value) return false
    if (item.source_type === 'online' && onlineSourceFilter.value && item.source !== onlineSourceFilter.value) return false
    if (formatFilter.value === 'lossless') {
      return ['FLAC', 'ALAC', 'APE', 'WAV', 'DSD'].includes(String(item.format || '').toUpperCase())
    }
    if (formatFilter.value === 'lossy') {
      return ['MP3', 'AAC', 'M4A', 'OGG'].includes(String(item.format || '').toUpperCase())
    }
    return true
  })
  if (sortBy.value === 'seeders') {
    filtered.sort((a, b) => {
      if (a.source_type !== b.source_type) return a.source_type === 'pt' ? -1 : 1
      return (b.seeders || 0) - (a.seeders || 0)
    })
  } else if (sortBy.value === 'size') filtered.sort((a, b) => (b.size || 0) - (a.size || 0))
  else if (sortBy.value === 'pt_first') filtered.sort((a, b) => (a.source_type === b.source_type ? (b.score || 0) - (a.score || 0) : (a.source_type === 'pt' ? -1 : 1)))
  else if (sortBy.value === 'online_first') filtered.sort((a, b) => (a.source_type === b.source_type ? (b.score || 0) - (a.score || 0) : (a.source_type === 'online' ? -1 : 1)))
  else filtered.sort((a, b) => (b.score || 0) - (a.score || 0))
  return filtered
})

async function handleSearch() {
  if (!keyword.value.trim()) return
  loading.value = true
  downloadMessage.value = null
  try {
    const params = { keyword: keyword.value.trim(), type: searchType.value, quality: quality.value, limit: 80, include_pt: true, include_online: true }
    if (searchType.value === 'album') params.album = keyword.value.trim()
    if (searchType.value === 'artist') params.artist = keyword.value.trim()
    lastResp.value = await searchCandidates(params)
    cache.rememberPtSearch(keyword.value.trim(), {
      type: searchType.value,
      quality: quality.value,
      sourceFilter: sourceFilter.value,
      total: lastResp.value?.total || 0,
      ptCount: lastResp.value?.pt?.count || 0,
      onlineCount: lastResp.value?.online?.count || 0,
      siteCount: lastResp.value?.pt?.sites?.length || 0,
    })
  } catch (e) {
    downloadMessage.value = { type: 'error', text: e.message || '搜索失败' }
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function handleDownload(item) {
  downloading.value = item.id
  downloadMessage.value = null
  try {
    let res
    if (item.download_tool === 'download_online_song' || item.source_type === 'online') {
      const args = item.download_args || {}
      res = await downloadOnlineSong(args.song || item.raw || item, args.organize ?? true)
    } else {
      const args = item.download_args || {}
      res = await downloadTorrent(args.site || item.source, args.torrent_id, args.title || item.title)
    }
    const action = item.source_type === 'online' ? '已开始下载单曲' : (res.already_exists ? '任务已存在' : '已添加下载任务')
    const suffix = res.task_id ? ` · 任务 #${res.task_id}` : ''
    downloadMessage.value = { type: 'success', text: `${action}：${item.title}${suffix}` }
  } catch (e) {
    downloadMessage.value = { type: 'error', text: e.message || '下载失败' }
  } finally {
    downloading.value = null
  }
}

function formatSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB'
}

function formatUploadTime(value) {
  if (!value) return '-'
  const text = String(value).trim()
  const m = text.match(/^(\d{4}-\d{2}-\d{2})/)
  return m ? m[1] : text.slice(0, 16)
}

function candidateScore(item) {
  return Math.round(Number(item.score || 0))
}

function scoreColor(item) {
  const score = candidateScore(item)
  return score >= 80 ? 'green' : (score >= 50 ? 'orange' : 'dim')
}

function sourceLabel(item) {
  return item.source_type === 'online' ? `在线 · ${item.source}` : `PT · ${item.source}`
}

function candidateFormat(item) {
  return item.format || item.media_format || '-'
}

function candidateKey(item) {
  return item.id || `${item.source_type}-${item.source}-${item.title}`
}

function downloadButtonText(item) {
  if (!item.downloadable) return '不可用'
  return item.source_type === 'online' ? '下载单曲' : '添加任务'
}

function sourceTypeLabel(value) {
  if (value === 'pt') return 'PT'
  if (value === 'online') return '在线'
  return '全部'
}

function toggleSource(value) {
  sourceFilter.value = sourceFilter.value === value ? 'all' : value
  if (value !== 'pt') siteFilter.value = ''
  if (value !== 'online') onlineSourceFilter.value = ''
}

function toggleSite(name) {
  sourceFilter.value = 'pt'
  siteFilter.value = siteFilter.value === name ? '' : name
}

function toggleOnlineSource(name) {
  sourceFilter.value = 'online'
  onlineSourceFilter.value = onlineSourceFilter.value === name ? '' : name
}

function restoreHistory(item) {
  keyword.value = item.keyword || ''
  searchType.value = item.type || 'keyword'
  quality.value = item.quality || 'any'
  sourceFilter.value = item.sourceFilter || 'all'
  siteFilter.value = ''
  onlineSourceFilter.value = ''
  handleSearch()
}

function formatHistoryTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

onMounted(() => {
  const pending = localStorage.getItem('music_sub_pending_search_keyword')
  if (pending) {
    localStorage.removeItem('music_sub_pending_search_keyword')
    keyword.value = pending
    quality.value = 'flac'
    handleSearch()
  }
})
</script>

<template>
  <div class="search-view">
    <div class="search-bar">
      <input
        v-model="keyword"
        placeholder="搜索专辑/艺人/歌单..."
        class="search-input"
        @keyup.enter="handleSearch"
      />
      <select v-model="searchType" class="sel">
        <option value="keyword">关键字</option>
        <option value="artist">艺人</option>
        <option value="album">专辑</option>
      </select>
      <select v-model="quality" class="sel">
        <option value="any">不限质量</option>
        <option value="flac">无损</option>
        <option value="mp3">MP3</option>
      </select>
      <AppButton variant="primary" :loading="loading" @click="handleSearch">搜索</AppButton>
    </div>

    <div v-if="history.length" class="history-row">
      <span class="history-label">最近搜索</span>
      <button v-for="item in history.slice(0, 6)" :key="item.id" class="history-chip" @click="restoreHistory(item)">
        {{ item.keyword }} <small>{{ item.total ?? 0 }}条 · PT {{ item.ptCount ?? '-' }} · 在线 {{ item.onlineCount ?? '-' }} · {{ sourceTypeLabel(item.sourceFilter || 'all') }} · {{ formatHistoryTime(item.at) }}</small>
      </button>
    </div>

    <div v-if="lastResp" class="source-row">
      <span class="site-label">来源</span>
      <button :class="['source-chip', { active: sourceFilter === 'all' }]" @click="toggleSource('all')">全部 <small>{{ total }}</small></button>
      <button :class="['source-chip', { active: sourceFilter === 'pt' }]" @click="toggleSource('pt')">PT <small>{{ ptCount }}</small></button>
      <button :class="['source-chip', { active: sourceFilter === 'online' }]" @click="toggleSource('online')">在线 <small>{{ onlineCount }}</small></button>
    </div>

    <div v-if="sites.length" class="site-row">
      <span class="site-label">PT 站点</span>
      <button
        v-for="s in sites"
        :key="s.site"
        :class="['site-chip', { active: sourceFilter === 'pt' && siteFilter === s.site, error: !s.ok }]"
        @click="toggleSite(s.site)"
      >
        <strong>{{ s.site }}</strong>
        <span class="site-meta">{{ s.ok ? `${s.count} 条` : (s.error || '失败') }} · {{ Number(s.seconds || 0).toFixed(1) }}s</span>
      </button>
      <span v-if="queries.length" class="queries">queries: {{ queries.join('  ,  ') }}</span>
    </div>

    <div v-if="sourceSummary.length" class="site-row">
      <span class="site-label">在线源</span>
      <button
        v-for="s in sourceSummary"
        :key="s.source"
        :class="['source-chip', { active: sourceFilter === 'online' && onlineSourceFilter === s.source }]"
        @click="toggleOnlineSource(s.source)"
      >{{ s.source }} <small>{{ s.count }}</small></button>
    </div>

    <div v-if="notices.length || downloadMessage" class="notice-stack">
      <div v-for="item in notices" :key="item.text" :class="['notice', item.type]">{{ item.text }}</div>
      <div v-if="downloadMessage" :class="['notice', downloadMessage.type]">{{ downloadMessage.text }}</div>
    </div>

    <div v-if="lastResp" class="toolbar">
      <div class="left">共 {{ filteredResults.length }} / {{ total }} 条 <span v-if="lastResp?.pt || lastResp?.online" class="count-breakdown">PT {{ ptCount }} · 在线 {{ onlineCount }}</span></div>
      <div class="right">
        <select v-model="formatFilter" class="sel">
          <option value="all">全部格式</option>
          <option value="lossless">仅无损</option>
          <option value="lossy">仅有损</option>
        </select>
        <select v-model="sortBy" class="sel">
          <option value="score">智能评分</option>
          <option value="seeders">PT 热度</option>
          <option value="size">文件大小</option>
          <option value="pt_first">PT 优先</option>
          <option value="online_first">在线优先</option>
        </select>
      </div>
    </div>

    <div v-if="loading" class="loading-text">搜索中...</div>
    <div v-else-if="lastResp && filteredResults.length === 0" class="empty-text">未找到符合条件的资源</div>
    <div v-else-if="filteredResults.length" class="results-section">
      <div class="results-table-wrap">
        <table class="results-table">
          <thead>
            <tr>
              <th>评分</th>
              <th>标题</th>
              <th>格式</th>
              <th>质量</th>
              <th>标记</th>
              <th>来源</th>
              <th>大小</th>
              <th>做种</th>
              <th>上传时间</th>
              <th>下载</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in filteredResults" :key="candidateKey(item)">
              <td><AppBadge :color="scoreColor(item)">{{ candidateScore(item) }}</AppBadge></td>
              <td class="title-cell">
                <div class="title-text">{{ item.title }}</div>
                <div v-if="item.artist || item.album" class="title-subtitle">{{ item.artist || '未知艺人' }}<span v-if="item.album"> · {{ item.album }}</span></div>
                <div v-if="item.reasons?.length" class="title-reasons">{{ item.reasons.join(' · ') }}</div>
              </td>
              <td class="text-dim">{{ candidateFormat(item) }}</td>
              <td class="text-dim">{{ item.quality || '-' }}</td>
              <td><AppBadge v-if="item.free" color="green">FREE</AppBadge><AppBadge v-else-if="item.source_type === 'online'" color="blue">在线</AppBadge><AppBadge v-else-if="!item.downloadable" color="orange">不可用</AppBadge></td>
              <td class="text-dim">{{ sourceLabel(item) }}</td>
              <td class="text-dim">{{ formatSize(item.size) }}</td>
              <td class="text-dim">{{ item.source_type === 'pt' ? (item.seeders ?? '-') : '-' }}</td>
              <td class="text-dim">{{ formatUploadTime(item.upload_time) }}</td>
              <td>
                <AppButton
                  variant="primary"
                  size="sm"
                  :disabled="!item.downloadable"
                  :loading="downloading === item.id"
                  @click="handleDownload(item)"
                >{{ downloadButtonText(item) }}</AppButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="result-cards">
        <article v-for="item in filteredResults" :key="`card-${candidateKey(item)}`" class="result-card">
          <div class="card-head">
            <h3>{{ item.title }}</h3>
            <AppBadge :color="scoreColor(item)">{{ candidateScore(item) }}</AppBadge>
          </div>
          <div v-if="item.artist || item.album" class="title-subtitle">{{ item.artist || '未知艺人' }}<span v-if="item.album"> · {{ item.album }}</span></div>
          <div class="chip-row">
            <span class="info-chip">{{ sourceLabel(item) }}</span>
            <span class="info-chip">{{ candidateFormat(item) }}</span>
            <span class="info-chip">{{ item.quality || '-' }}</span>
            <span class="info-chip">{{ formatSize(item.size) }}</span>
            <span v-if="item.source_type === 'pt'" class="info-chip">seed {{ item.seeders ?? '-' }}</span>
            <span v-if="item.free" class="info-chip free">FREE</span>
            <span v-if="!item.downloadable" class="info-chip warn">不可用</span>
          </div>
          <div v-if="item.reasons?.length" class="card-reasons">{{ item.reasons.join(' · ') }}</div>
          <div class="card-footer">
            <span class="text-dim">{{ formatUploadTime(item.upload_time) }}</span>
            <AppButton
              variant="primary"
              size="sm"
              :disabled="!item.downloadable"
              :loading="downloading === item.id"
              @click="handleDownload(item)"
            >{{ downloadButtonText(item) }}</AppButton>
          </div>
        </article>
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-view { padding: 24px; display: flex; flex-direction: column; gap: 16px; overflow-y: auto; height: 100%; }
.search-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.search-input { flex: 1; min-width: 220px; }
.sel { padding: 6px 10px; border-radius: var(--radius-md); background: var(--surface); border: 1px solid var(--border); color: var(--text); font-size: 13px; }
.history-row, .source-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: -6px; }
.history-label { color: var(--text-dim); font-size: 12px; }
.history-chip { border: 1px solid var(--border); background: var(--surface); color: var(--text); border-radius: 999px; padding: 6px 10px; font-size: 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.history-chip small { color: var(--text-dim); }
.site-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.site-label { color: var(--text-dim); font-size: 12px; }
.site-chip, .source-chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--text-dim); cursor: pointer; font-size: 12px; }
.site-chip { flex-direction: column; align-items: flex-start; gap: 2px; }
.source-chip small { color: var(--text-muted); }
.site-chip strong { color: var(--text); font-size: 13px; }
.site-chip.active, .source-chip.active { background: var(--surface-hover); color: var(--text); border-color: var(--accent); }
.site-chip.error { color: var(--danger); border-color: var(--danger); }
.site-meta { font-size: 11px; color: var(--text-muted); }
.queries { color: var(--text-muted); font-size: 12px; margin-left: 6px; }
.notice-stack { display: flex; flex-direction: column; gap: 8px; }
.notice { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 9px 12px; font-size: 13px; color: var(--text-dim); background: var(--surface-soft); }
.notice.warn { color: var(--warning); border-color: color-mix(in srgb, var(--warning) 35%, var(--border)); }
.notice.error { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 40%, var(--border)); }
.notice.success { color: var(--success); border-color: color-mix(in srgb, var(--success) 35%, var(--border)); }
.notice.muted { color: var(--text-muted); }
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
.toolbar .left { color: var(--text-dim); font-size: 13px; }
.count-breakdown { margin-left: 8px; color: var(--text-muted); }
.toolbar .right { display: flex; gap: 8px; }
.loading-text, .empty-text { color: var(--text-dim); padding: 20px 0; }
.results-section { display: block; }
.results-table-wrap { overflow-x: auto; }
.results-table { width: 100%; border-collapse: collapse; }
.results-table th { text-align: left; padding: 8px 12px; font-size: 12px; font-weight: 600; color: var(--text-dim); border-bottom: 1px solid var(--border); }
.results-table td { padding: 10px 12px; font-size: 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
.results-table tr:hover td { background: var(--surface-hover); }
.title-cell { max-width: 360px; }
.title-text { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.title-subtitle { margin-top: 2px; font-size: 12px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.title-reasons { margin-top: 2px; font-size: 11px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.result-cards { display: none; }
.result-card { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-elevated); padding: 14px; }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.card-head h3 { min-width: 0; margin: 0; font-size: 15px; line-height: 1.35; font-weight: 700; overflow-wrap: anywhere; }
.chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.info-chip { border: 1px solid var(--border); border-radius: 999px; padding: 3px 8px; color: var(--text-dim); background: var(--surface); font-size: 12px; }
.info-chip.free { color: var(--success); border-color: color-mix(in srgb, var(--success) 35%, var(--border)); }
.info-chip.warn { color: var(--warning); border-color: color-mix(in srgb, var(--warning) 35%, var(--border)); }
.card-reasons { margin-top: 10px; color: var(--text-muted); font-size: 12px; line-height: 1.45; }
.card-footer { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: 12px; }
@media (max-width: 768px) {
  .search-bar { flex-direction: column; align-items: stretch; }
  .search-input { min-width: 0; width: 100%; }
  .sel { width: 100%; }
  .toolbar { align-items: flex-start; }
  .toolbar .right { width: 100%; flex-wrap: wrap; }
  .site-chip { max-width: 100%; }
  .results-table-wrap { display: none; }
  .result-cards { display: flex; flex-direction: column; gap: 12px; }
}
@media (max-width: 420px) {
  .search-view { padding: 16px; }
  .toolbar .right { flex-direction: column; }
  .card-footer { align-items: stretch; }
}
</style>
