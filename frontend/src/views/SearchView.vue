<script setup>
import { ref } from 'vue'
import { searchMusic, downloadTorrent } from '@/api/index.js'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'

const keyword = ref('')
const results = ref([])
const loading = ref(false)
const downloading = ref(null)

async function handleSearch() {
  if (!keyword.value.trim()) return
  loading.value = true
  results.value = []
  try {
    const data = await searchMusic(keyword.value.trim())
    results.value = Array.isArray(data) ? data : []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function handleDownload(site, torrentId, title) {
  downloading.value = `${site}-${torrentId}`
  try {
    const res = await downloadTorrent(site, torrentId, title)
    alert(res.already_exists ? '任务已存在，已跳过重复添加' : '已添加到下载任务')
  } catch (e) {
    alert(e.message || '下载失败')
    console.error(e)
  } finally {
    downloading.value = null
  }
}

function formatSize(bytes) {
  if (!bytes) return '-'
  if (typeof bytes === 'string') return bytes
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB'
}
</script>

<template>
  <div class="search-view">
    <div class="search-bar">
      <input
        v-model="keyword"
        placeholder="搜索音乐、专辑、艺人..."
        class="search-input"
        @keyup.enter="handleSearch"
      />
      <AppButton variant="primary" :loading="loading" @click="handleSearch">搜索</AppButton>
    </div>

    <div v-if="loading" class="loading-text">搜索中...</div>
    <div v-else-if="results.length === 0 && keyword" class="empty-text">未找到结果</div>
    <div v-else-if="results.length > 0" class="results-table-wrap">
      <table class="results-table">
        <thead>
          <tr>
            <th>标题</th>
            <th>FREE</th>
            <th>站点</th>
            <th>大小</th>
            <th>做种</th>
            <th>下载</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(item, idx) in results" :key="idx">
            <td class="title-cell">{{ item.title }}</td>
            <td>
              <AppBadge v-if="item.free || item.upload_time?.toLowerCase?.()?.includes('free')" color="green">FREE</AppBadge>
            </td>
            <td class="text-dim">{{ item.site }}</td>
            <td class="text-dim">{{ formatSize(item.size) }}</td>
            <td class="text-dim">{{ item.seeders ?? '-' }}</td>
            <td>
              <AppButton
                variant="primary"
                size="sm"
                :loading="downloading === `${item.site}-${item.torrent_id}`"
                @click="handleDownload(item.site, item.torrent_id, item.title)"
              >
                下载
              </AppButton>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.search-view { padding: 24px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; height: 100%; }
.search-bar { display: flex; gap: 10px; }
.search-input { flex: 1; }
.loading-text, .empty-text { color: var(--text-dim); padding: 20px 0; }
.results-table-wrap { overflow-x: auto; }
.results-table { width: 100%; border-collapse: collapse; }
.results-table th { text-align: left; padding: 8px 12px; font-size: 12px; font-weight: 600; color: var(--text-dim); border-bottom: 1px solid var(--border); }
.results-table td { padding: 10px 12px; font-size: 14px; border-bottom: 1px solid var(--border); }
.results-table tr:hover td { background: var(--surface-hover); }
.title-cell { font-weight: 500; max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>