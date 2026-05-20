<script setup>
import { computed, toRefs, watch } from 'vue'
import { searchOnlineMusic, resolveOnlineSong, downloadOnlineSong } from '@/api/index.js'
import { useSearchCacheStore } from '@/stores/searchCache.js'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'
import { useThemeStore } from '@/stores/theme.js'
import { animalIslandIcons } from '@/utils/animalIsland.js'

const theme = useThemeStore()
const isIsland = computed(() => theme.current === 'island')
const cache = useSearchCacheStore()
const {
  keyword,
  results,
  loading,
  downloading,
  resolving,
  downloadMessage,
  resolveMessage,
  page,
  pageSize,
  filterSource,
  filterFormat,
  onlyDownloadable,
  selectedSources,
  history,
  downloadHistory,
} = toRefs(cache.online)
const searchLimit = cache.online.searchLimit || 100
const allSources = ['qq', 'migu', 'kugou', 'netease', 'kuwo']

const sourceLabels = {
  qq: 'QQ音乐',
  migu: '咪咕',
  kugou: '酷狗',
  netease: '网易云',
  kuwo: '酷我'
}

const formatOptions = computed(() => {
  const values = [...new Set(results.value.map(r => String(r.format || '').toLowerCase()).filter(Boolean))]
  return values.sort()
})
const filteredResults = computed(() => results.value.filter(song => {
  if (filterSource.value !== 'all' && song.source !== filterSource.value) return false
  if (filterFormat.value !== 'all' && String(song.format || '').toLowerCase() !== filterFormat.value) return false
  if (onlyDownloadable.value && song.disabled) return false
  return true
}))
const totalPages = computed(() => Math.max(1, Math.ceil(filteredResults.value.length / pageSize.value)))
const pagedResults = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredResults.value.slice(start, start + pageSize.value)
})
const pageStart = computed(() => filteredResults.value.length ? (page.value - 1) * pageSize.value + 1 : 0)
const pageEnd = computed(() => Math.min(page.value * pageSize.value, filteredResults.value.length))
const maybeMore = computed(() => results.value.length >= searchLimit)

watch([filterSource, filterFormat, onlyDownloadable], () => { page.value = 1 })
watch(totalPages, (n) => { if (page.value > n) page.value = n })

function changePage(next) {
  page.value = Math.min(Math.max(1, next), totalPages.value)
}

function formatSize(bytes) {
  if (!bytes) return '-'
  if (bytes >= 1024 * 1024 * 1024) return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB'
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return bytes + ' B'
}

async function handleSearch() {
  if (!keyword.value.trim()) return
  loading.value = true
  downloadMessage.value = null
  resolveMessage.value = null
  try {
    page.value = 1
    results.value = await searchOnlineMusic(keyword.value.trim(), selectedSources.value, searchLimit)
    cache.rememberOnlineSearch(keyword.value.trim(), {
      sources: [...selectedSources.value],
      resultCount: results.value.length,
    })
  } catch (e) {
    downloadMessage.value = { type: 'error', text: '搜索失败：' + (e.message || '网络错误') }
  } finally {
    loading.value = false
  }
}

function downloadErrorHint(errorOrMessage = '') {
  const payload = errorOrMessage?.payload?.detail || errorOrMessage?.payload || null
  const reason = payload?.reason || ''
  const message = typeof errorOrMessage === 'string' ? errorOrMessage : (payload?.message || errorOrMessage?.message || '')
  const text = `${reason} ${String(message || '')}`
  if (text.includes('qq_resolve_failed') || text.includes('没有拿到可下载链接')) return 'QQ 解析源未返回可用链接，可能是 NKI 短时不可用或该曲目需要会员权限。可以稍后重试，或换酷狗/网易云/咪咕。'
  if (text.includes('qq_download_failed') || text.includes('候选链接均不可用')) return 'QQ 链接已解析但 CDN 下载失败，通常是链接过期、区域限制或服务器返回异常内容。可以重试一次，或换源下载。'
  if (text.includes('非音频内容')) return '下载地址返回了错误页，不是真正音频文件。建议换源或稍后重试。'
  if (text.includes('内容过小')) return '下载文件过小，疑似试听片段或错误响应，已自动丢弃。'
  if (reason || message) return `${message || '下载失败'}${reason ? `（${reason}）` : ''}`
  return '下载失败，请稍后重试。'
}

function restoreHistory(item) {
  keyword.value = item.keyword || ''
  if (Array.isArray(item.sources) && item.sources.length) selectedSources.value = item.sources
  handleSearch()
}

function formatHistoryTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function describeResolveResult(song, res) {
  const candidates = res?.candidates || []
  if (!candidates.length) return `${sourceLabels[song.source] || song.source} 没有解析出可下载候选。`
  const details = candidates.map(c => `${(c.format || c.path_ext || '-').toUpperCase()} · ${c.host || '-'}`).join('；')
  return `解析成功：${candidates.length} 个候选｜${details}`
}

async function handleResolve(song) {
  resolving.value = song.source + ':' + song.song_id
  resolveMessage.value = null
  try {
    const res = await resolveOnlineSong(song)
    resolveMessage.value = { type: res.ok ? 'ok' : 'error', text: `${song.title}：${describeResolveResult(song, res)}` }
  } catch (e) {
    resolveMessage.value = { type: 'error', text: `${song.title}：诊断失败：${downloadErrorHint(e.message)}` }
  } finally {
    resolving.value = ''
  }
}

async function handleDownload(song) {
  if (song.disabled) return
  downloading.value = song.source + ':' + song.song_id
  downloadMessage.value = null
  resolveMessage.value = null
  try {
    const res = await downloadOnlineSong(song, true)
    if (res.ok) {
      downloadMessage.value = { type: 'ok', text: `✅ 已下载并整理完成：${song.title}` }
      cache.pushOnlineDownload({ title: song.title, artist: song.artist, source: song.source, ok: true, taskId: res.task_id })
    } else downloadMessage.value = { type: 'error', text: '下载失败' }
  } catch (e) {
    const hint = downloadErrorHint(e)
    cache.pushOnlineDownload({ title: song.title, artist: song.artist, source: song.source, ok: false, error: hint })
    downloadMessage.value = { type: 'error', text: `下载失败：${hint}` }
  } finally {
    downloading.value = ''
  }
}
</script>

<template>
  <div class="online-view">
    <div class="online-card">
      <h3 class="animal-page-title"><img v-if="isIsland" :src="animalIslandIcons.shopping" alt="" /><span v-else>🎧</span><span>在线音乐下载</span></h3>
      <p class="hint">从 QQ音乐 / 咪咕 / 酷狗 / 网易云 / 酷我搜索直链，下载后自动进入整理刮削流程。</p>
      <div class="source-row">
        <label v-for="s in allSources" :key="s" class="source-item">
          <input type="checkbox" :value="s" v-model="selectedSources" />
          <span>{{ sourceLabels[s] }}</span>
        </label>
      </div>
      <div class="search-row">
        <input v-model="keyword" placeholder="歌曲 / 歌手，例如：周杰伦 稻香" @keyup.enter="handleSearch" />
        <AppButton variant="primary" :loading="loading" @click="handleSearch">搜索</AppButton>
      </div>
      <div v-if="history.length" class="history-row">
        <span class="history-label">最近搜索</span>
        <button v-for="item in history.slice(0, 6)" :key="item.id" class="history-chip" @click="restoreHistory(item)">
          {{ item.keyword }} <small>{{ item.resultCount ?? 0 }}条 · {{ formatHistoryTime(item.at) }}</small>
        </button>
      </div>
    </div>

    <div class="results-card">
      <div v-if="resolveMessage" :class="['download-message', resolveMessage.type]">{{ resolveMessage.text }}</div>
      <div v-if="downloadMessage" :class="['download-message', downloadMessage.type]">{{ downloadMessage.text }}</div>
      <div v-if="loading" class="empty-text">搜索中...</div>
      <div v-else-if="results.length === 0" class="empty-text">暂无结果</div>
      <div v-else class="result-summary">
        <span>显示 {{ pageStart }}-{{ pageEnd }} / 筛选后 {{ filteredResults.length }} 条（总 {{ results.length }} 条）</span>
        <span v-if="maybeMore" class="more-hint">已达到本次搜索上限，可缩小关键词继续找</span>
      </div>
      <div v-if="!loading && results.length" class="filter-row">
        <label>来源
          <select v-model="filterSource">
            <option value="all">全部</option>
            <option v-for="s in allSources" :key="s" :value="s">{{ sourceLabels[s] }}</option>
          </select>
        </label>
        <label>格式
          <select v-model="filterFormat">
            <option value="all">全部</option>
            <option v-for="fmt in formatOptions" :key="fmt" :value="fmt">{{ fmt.toUpperCase() }}</option>
          </select>
        </label>
        <label class="inline-check"><input type="checkbox" v-model="onlyDownloadable" /> 仅可下载</label>
      </div>
      <div v-if="!loading && results.length && !filteredResults.length" class="empty-text">当前筛选没有匹配结果。</div>
      <div v-if="!loading && filteredResults.length" class="table-wrap">
        <table class="results-table">
          <thead>
            <tr>
              <th>来源</th>
              <th>歌曲</th>
              <th>艺人</th>
              <th>专辑</th>
              <th>格式</th>
              <th>大小</th>
              <th>时长</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="song in pagedResults" :key="song.source + ':' + song.song_id + ':' + song.filename">
              <td><AppBadge :color="song.disabled ? 'dim' : 'green'">{{ sourceLabels[song.source] || song.source }}</AppBadge></td>
              <td class="title-cell">{{ song.title }}</td>
              <td>{{ song.artist || '-' }}</td>
              <td>{{ song.album || '-' }}</td>
              <td>{{ song.format?.toUpperCase?.() || '-' }}</td>
              <td>{{ formatSize(song.size) }}</td>
              <td>{{ song.duration ? Math.floor(song.duration / 60) + ':' + String(song.duration % 60).padStart(2, '0') : '-' }}</td>
              <td>
                <div class="row-actions">
                  <AppButton
                    size="sm"
                    variant="ghost"
                    :loading="resolving === song.source + ':' + song.song_id"
                    @click="handleResolve(song)"
                  >诊断</AppButton>
                  <AppButton
                    size="sm"
                    :variant="song.disabled ? 'ghost' : 'primary'"
                    :disabled="song.disabled"
                    :loading="downloading === song.source + ':' + song.song_id"
                    @click="handleDownload(song)"
                  >{{ song.url ? '下载' : '解析下载' }}</AppButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!loading && filteredResults.length > pageSize" class="pager">
        <AppButton variant="ghost" size="sm" :disabled="page <= 1" @click="changePage(page - 1)">上一页</AppButton>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <AppButton variant="ghost" size="sm" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</AppButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.online-view { height: 100%; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 18px; padding: 24px; }
.online-card, .results-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px;
}
.online-card h3 { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.hint { color: var(--text-dim); font-size: 13px; margin-bottom: 14px; }
.source-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.source-item { display: flex; align-items: center; gap: 6px; color: var(--text-dim); font-size: 13px; }
.search-row { display: flex; gap: 10px; }
.search-row input { flex: 1; min-width: 0; }
.history-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; align-items: center; }
.history-label { color: var(--text-dim); font-size: 12px; }
.history-chip { border: 1px solid var(--border); background: var(--surface); color: var(--text); border-radius: 999px; padding: 6px 10px; font-size: 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.history-chip small { color: var(--text-dim); }
.empty-text { color: var(--text-dim); padding: 20px 0; text-align: center; }
.download-message { margin-bottom: 10px; padding: 10px 12px; border-radius: var(--radius-md); font-size: 13px; line-height: 1.5; border: 1px solid var(--border); background: var(--surface-soft); color: var(--text-dim); }
.download-message.ok { border-color: rgba(58, 196, 125, .35); color: var(--success); }
.download-message.error { border-color: rgba(255, 193, 7, .35); color: var(--warning); }
.result-summary { display: flex; justify-content: space-between; gap: 12px; color: var(--text-dim); font-size: 13px; margin-bottom: 10px; flex-wrap: wrap; }
.more-hint { color: var(--warning); }
.filter-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; color: var(--text-dim); font-size: 13px; }
.filter-row label { display: inline-flex; align-items: center; gap: 6px; }
.filter-row select { min-width: 96px; background: var(--surface); border: 1px solid var(--border); color: var(--text); border-radius: var(--radius-md); padding: 6px 8px; }
.inline-check input { margin: 0; }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.results-table { width: 100%; border-collapse: collapse; }
.results-table th {
  text-align: left;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-dim);
  border-bottom: 1px solid var(--border);
}
.results-table td { padding: 10px 12px; font-size: 14px; border-bottom: 1px solid var(--border); }
.results-table tr:hover td { background: var(--surface-hover); }
.title-cell { font-weight: 500; }
.row-actions { display: flex; align-items: center; justify-content: flex-end; gap: 6px; white-space: nowrap; }
.pager { display: flex; align-items: center; justify-content: center; gap: 12px; padding-top: 14px; color: var(--text-dim); font-size: 13px; }

@media (max-width: 768px) {
  .online-view { padding: 14px; padding-bottom: var(--mobile-page-bottom, 70px); overflow-y: auto; -webkit-overflow-scrolling: touch; }
  .online-card, .results-card { padding: 14px; border-radius: 16px; flex-shrink: 0; }
  .source-row { gap: 8px; }
  .source-item { min-width: calc(50% - 4px); }
  .search-row { flex-direction: column; }
  .result-summary, .filter-row { font-size: 12px; }
  .filter-row { align-items: stretch; }
  .filter-row label { flex: 1 1 120px; justify-content: space-between; }
  .results-table th, .results-table td { padding: 8px; font-size: 12px; white-space: nowrap; }
  .title-cell { min-width: 120px; max-width: 180px; white-space: normal; }
  .pager { position: sticky; bottom: 0; background: var(--bg-elevated); padding: 10px 0 2px; }
  .results-table th:nth-child(4), .results-table td:nth-child(4),
  .results-table th:nth-child(6), .results-table td:nth-child(6),
  .results-table th:nth-child(7), .results-table td:nth-child(7) { display: none; }
}
</style>
