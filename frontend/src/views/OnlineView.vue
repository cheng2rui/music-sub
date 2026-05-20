<script setup>
import { computed, ref } from 'vue'
import { searchOnlineMusic, downloadOnlineSong } from '@/api/index.js'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'
import { useThemeStore } from '@/stores/theme.js'
import { animalIslandIcons } from '@/utils/animalIsland.js'

const theme = useThemeStore()
const isIsland = computed(() => theme.current === 'island')
const keyword = ref('')
const results = ref([])
const loading = ref(false)
const downloading = ref('')
const page = ref(1)
const pageSize = ref(20)
const searchLimit = 100
const selectedSources = ref(['qq', 'migu', 'kugou', 'netease', 'kuwo'])
const allSources = ['qq', 'migu', 'kugou', 'netease', 'kuwo']

const sourceLabels = {
  qq: 'QQ音乐',
  migu: '咪咕',
  kugou: '酷狗',
  netease: '网易云',
  kuwo: '酷我'
}

const totalPages = computed(() => Math.max(1, Math.ceil(results.value.length / pageSize.value)))
const pagedResults = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return results.value.slice(start, start + pageSize.value)
})
const pageStart = computed(() => results.value.length ? (page.value - 1) * pageSize.value + 1 : 0)
const pageEnd = computed(() => Math.min(page.value * pageSize.value, results.value.length))
const maybeMore = computed(() => results.value.length >= searchLimit)

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
  try {
    page.value = 1
    results.value = await searchOnlineMusic(keyword.value.trim(), selectedSources.value, searchLimit)
  } catch (e) {
    alert('搜索失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

async function handleDownload(song) {
  if (song.disabled) return
  downloading.value = song.source + ':' + song.song_id
  try {
    const res = await downloadOnlineSong(song, true)
    if (res.ok) alert('✅ 下载并整理完成')
    else alert('下载失败')
  } catch (e) {
    alert('下载失败: ' + e.message)
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
    </div>

    <div class="results-card">
      <div v-if="loading" class="empty-text">搜索中...</div>
      <div v-else-if="results.length === 0" class="empty-text">暂无结果</div>
      <div v-else class="result-summary">
        <span>显示 {{ pageStart }}-{{ pageEnd }} / 共 {{ results.length }} 条</span>
        <span v-if="maybeMore" class="more-hint">已达到本次搜索上限，可缩小关键词继续找</span>
      </div>
      <div v-if="!loading && results.length" class="table-wrap">
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
                <AppButton
                  size="sm"
                  :variant="song.disabled ? 'ghost' : 'primary'"
                  :disabled="song.disabled"
                  :loading="downloading === song.source + ':' + song.song_id"
                  @click="handleDownload(song)"
                >{{ song.url ? '下载' : '解析下载' }}</AppButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!loading && results.length > pageSize" class="pager">
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
.empty-text { color: var(--text-dim); padding: 20px 0; text-align: center; }
.result-summary { display: flex; justify-content: space-between; gap: 12px; color: var(--text-dim); font-size: 13px; margin-bottom: 10px; flex-wrap: wrap; }
.more-hint { color: var(--warning); }
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
.pager { display: flex; align-items: center; justify-content: center; gap: 12px; padding-top: 14px; color: var(--text-dim); font-size: 13px; }

@media (max-width: 768px) {
  .online-view { padding: 14px; padding-bottom: var(--mobile-page-bottom, 70px); overflow-y: auto; -webkit-overflow-scrolling: touch; }
  .online-card, .results-card { padding: 14px; border-radius: 16px; flex-shrink: 0; }
  .source-row { gap: 8px; }
  .source-item { min-width: calc(50% - 4px); }
  .search-row { flex-direction: column; }
  .result-summary { font-size: 12px; }
  .results-table th, .results-table td { padding: 8px; font-size: 12px; white-space: nowrap; }
  .title-cell { min-width: 120px; max-width: 180px; white-space: normal; }
  .pager { position: sticky; bottom: 0; background: var(--bg-elevated); padding: 10px 0 2px; }
  .results-table th:nth-child(4), .results-table td:nth-child(4),
  .results-table th:nth-child(6), .results-table td:nth-child(6),
  .results-table th:nth-child(7), .results-table td:nth-child(7) { display: none; }
}
</style>
