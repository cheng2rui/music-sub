<script setup>
import { ref, onMounted } from 'vue'
import { getSubs, addSub, deleteSub, toggleSub, parsePlaylistUrl } from '@/api/index.js'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppModal from '@/components/AppModal.vue'

const subs = ref([])
const loading = ref(false)

// New sub form
const newSub = ref({ keyword: '', type: 'artist', quality: 'any', sites: [] })
const adding = ref(false)

const typeOptions = [
  { label: '艺人', value: 'artist' },
  { label: '歌曲', value: 'song' },
  { label: '专辑', value: 'album' },
  { label: '关键词', value: 'keyword' }
]
const qualityOptions = [
  { label: '任意', value: 'any' },
  { label: 'FLAC', value: 'flac' },
  { label: 'MP3', value: 'mp3' }
]

async function loadSubs() {
  loading.value = true
  try {
    subs.value = await getSubs()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function handleAdd() {
  if (!newSub.value.keyword.trim()) return
  adding.value = true
  try {
    await addSub({
      keyword: newSub.value.keyword.trim(),
      type: newSub.value.type,
      quality: newSub.value.quality,
      sites: newSub.value.sites
    })
    newSub.value = { keyword: '', type: 'artist', quality: 'any', sites: [] }
    await loadSubs()
  } catch (e) {
    console.error(e)
  } finally {
    adding.value = false
  }
}

async function handleToggle(id) {
  try {
    await toggleSub(id)
    await loadSubs()
  } catch (e) {
    console.error(e)
  }
}

async function handleDelete(id) {
  try {
    await deleteSub(id)
    await loadSubs()
  } catch (e) {
    console.error(e)
  }
}

function typeBadgeColor(type) {
  const map = { artist: 'green', song: 'blue', album: 'orange', keyword: 'dim' }
  return map[type] || 'dim'
}

// Playlist URL parsing
const playlistUrl = ref('')
const parsing = ref(false)
const parsedResult = ref(null)
const showParseModal = ref(false)

async function handleParseUrl() {
  if (!playlistUrl.value.trim()) return
  parsing.value = true
  try {
    const data = await parsePlaylistUrl(playlistUrl.value.trim())
    if (data.ok) {
      parsedResult.value = data
      showParseModal.value = true
    } else {
      alert(data.message || '解析失败')
    }
  } catch (e) { alert('解析失败: ' + e.message) }
  finally { parsing.value = false }
}

async function batchSubscribe() {
  if (!parsedResult.value?.songs) return
  let count = 0
  for (const song of parsedResult.value.songs) {
    try {
      await addSub({ keyword: `${song.title} ${song.artist}`.trim(), type: 'song', quality: 'any', sites: 'all' })
      count++
    } catch (e) { /* skip duplicates */ }
  }
  alert(`✅ 已添加 ${count} 个订阅`)
  showParseModal.value = false
  playlistUrl.value = ''
  await loadSubs()
}

onMounted(loadSubs)
</script>

<template>
  <div class="subs-view">
    <!-- 新增订阅表单 -->
    <div class="add-form">
      <h3>新增订阅</h3>
      <div class="form-row">
        <input
          v-model="newSub.keyword"
          placeholder="关键词"
          class="input-keyword"
          @keyup.enter="handleAdd"
        />
        <select v-model="newSub.type">
          <option v-for="o in typeOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <select v-model="newSub.quality">
          <option v-for="o in qualityOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <AppButton variant="primary" :loading="adding" @click="handleAdd">添加</AppButton>
      </div>
    </div>

    <!-- 歌单链接解析 -->
    <div class="add-form">
      <h3>🔗 歌单链接解析</h3>
      <p class="form-hint">粘贴 QQ音乐 或 网易云 歌单链接，自动解析歌曲列表并批量订阅</p>
      <div class="form-row">
        <input
          v-model="playlistUrl"
          placeholder="粘贴歌单链接 (y.qq.com/... 或 music.163.com/...)"
          class="input-keyword"
          @keyup.enter="handleParseUrl"
        />
        <AppButton variant="primary" :loading="parsing" @click="handleParseUrl">解析</AppButton>
      </div>
    </div>

    <!-- 解析结果弹窗 -->
    <AppModal v-if="showParseModal" :title="'🎵 ' + (parsedResult?.title || '歌单解析结果')" @close="showParseModal = false">
      <div class="parse-result">
        <p class="parse-meta">来源: {{ parsedResult?.source }} | 共 {{ parsedResult?.count }} 首</p>
        <div class="parse-songs">
          <div v-for="(song, idx) in parsedResult?.songs" :key="idx" class="parse-song-row">
            <span class="parse-idx">{{ idx + 1 }}</span>
            <span class="parse-song-title">{{ song.title }}</span>
            <span class="parse-song-artist">{{ song.artist }}</span>
          </div>
        </div>
        <div class="parse-actions">
          <AppButton variant="primary" @click="batchSubscribe">✅ 全部订阅 ({{ parsedResult?.count }} 首)</AppButton>
          <AppButton variant="ghost" @click="showParseModal = false">取消</AppButton>
        </div>
      </div>
    </AppModal>

    <!-- 订阅列表 -->
    <div class="subs-list">
      <div v-if="loading" class="loading-text">加载中...</div>
      <div v-else-if="subs.length === 0" class="empty-text">暂无订阅</div>
      <div v-else class="table-wrap">
        <table class="subs-table">
          <thead>
            <tr>
              <th>类型</th>
              <th>关键词</th>
              <th>品质</th>
              <th>状态</th>
              <th>最近搜索</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="sub in subs" :key="sub.id">
              <td><AppBadge :color="typeBadgeColor(sub.type)">{{ sub.type }}</AppBadge></td>
              <td class="keyword-cell">{{ sub.keyword }}</td>
              <td>{{ sub.quality }}</td>
              <td>
                <AppBadge :color="sub.enabled ? 'green' : 'dim'">
                  {{ sub.enabled ? '启用' : '停用' }}
                </AppBadge>
              </td>
              <td class="text-dim">{{ sub.last_search_at ? new Date(sub.last_search_at).toLocaleString() : '-' }}</td>
              <td>
                <div class="action-btns">
                  <button class="icon-btn" @click="handleToggle(sub.id)" :title="sub.enabled ? '停用' : '启用'">
                    {{ sub.enabled ? '⏸' : '▶' }}
                  </button>
                  <button class="icon-btn danger" @click="handleDelete(sub.id)" title="删除">🗑</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.subs-view { padding: 24px; display: flex; flex-direction: column; gap: 24px; overflow-y: auto; height: 100%; }
.add-form { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px; }
.add-form h3 { font-size: 16px; font-weight: 600; margin-bottom: 14px; }
.form-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.input-keyword { flex: 1; min-width: 180px; }
.subs-list { display: flex; flex-direction: column; }
.loading-text, .empty-text { color: var(--text-dim); padding: 20px 0; }
.table-wrap { overflow-x: auto; }
.subs-table { width: 100%; border-collapse: collapse; }
.subs-table th {
  text-align: left; padding: 8px 12px;
  font-size: 12px; font-weight: 600; color: var(--text-dim);
  border-bottom: 1px solid var(--border);
}
.subs-table td { padding: 10px 12px; font-size: 14px; border-bottom: 1px solid var(--border); }
.subs-table tr:hover td { background: var(--surface-hover); }
.keyword-cell { font-weight: 500; }
.action-btns { display: flex; gap: 8px; }
.icon-btn { background: none; border: none; cursor: pointer; font-size: 16px; padding: 4px; border-radius: var(--radius-sm); }
.icon-btn:hover { background: var(--surface-hover); }
.icon-btn.danger:hover { color: var(--danger); }
.form-hint { font-size: 12px; color: var(--text-dim); margin-bottom: 10px; }
.parse-result { display: flex; flex-direction: column; gap: 16px; min-width: 400px; }
.parse-meta { font-size: 13px; color: var(--text-dim); }
.parse-songs { display: flex; flex-direction: column; gap: 4px; max-height: 350px; overflow-y: auto; }
.parse-song-row { display: flex; align-items: center; gap: 10px; padding: 6px 8px; border-radius: var(--radius-sm); font-size: 13px; }
.parse-song-row:hover { background: var(--surface-hover); }
.parse-idx { color: var(--text-muted); min-width: 24px; text-align: right; }
.parse-song-title { font-weight: 500; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.parse-song-artist { color: var(--text-dim); flex-shrink: 0; }
.parse-actions { display: flex; gap: 10px; padding-top: 12px; border-top: 1px solid var(--border); }

@media (max-width: 768px) {
  .parse-result { min-width: unset; }
}
</style>