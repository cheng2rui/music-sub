<script setup>
import { ref } from 'vue'
import { searchOnlineMusic, downloadOnlineSong } from '@/api/index.js'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'

const keyword = ref('')
const results = ref([])
const loading = ref(false)
const downloading = ref('')
const selectedSources = ref(['migu', 'kugou', 'netease'])

const sourceLabels = {
  migu: '咪咕',
  kugou: '酷狗',
  netease: '网易云'
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
    results.value = await searchOnlineMusic(keyword.value.trim(), selectedSources.value, 30)
  } catch (e) {
    alert('搜索失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

async function handleDownload(song) {
  if (song.disabled || !song.url) return
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
      <h3>🎧 在线音乐下载</h3>
      <p class="hint">从咪咕 / 酷狗 / 网易云搜索直链，下载后自动进入整理刮削流程。</p>
      <div class="source-row">
        <label v-for="s in ['migu','kugou','netease']" :key="s" class="source-item">
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
      <div v-else class="table-wrap">
        <table class="results-table">
          <thead>
            <tr>
              <th>来源</th>
              <th>歌曲</th>
              <th>艺人</th>
              <th>专辑</th>
              <th>格式</th>
              <th>大小</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="song in results" :key="song.source + ':' + song.song_id + ':' + song.filename">
              <td><AppBadge :color="song.disabled ? 'dim' : 'green'">{{ sourceLabels[song.source] || song.source }}</AppBadge></td>
              <td class="title-cell">{{ song.title }}</td>
              <td>{{ song.artist || '-' }}</td>
              <td>{{ song.album || '-' }}</td>
              <td>{{ song.format?.toUpperCase?.() || '-' }}</td>
              <td>{{ formatSize(song.size) }}</td>
              <td>
                <AppButton
                  size="sm"
                  :variant="song.disabled ? 'ghost' : 'primary'"
                  :disabled="song.disabled"
                  :loading="downloading === song.source + ':' + song.song_id"
                  @click="handleDownload(song)"
                >下载</AppButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.online-view { display: flex; flex-direction: column; gap: 18px; }
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
.table-wrap { overflow-x: auto; }
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

@media (max-width: 768px) {
  .online-card, .results-card { padding: 14px; }
  .search-row { flex-direction: column; }
  .results-table th, .results-table td { padding: 8px; font-size: 12px; }
}
</style>
