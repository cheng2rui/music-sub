<script setup>
import { computed, ref, onMounted, watch } from 'vue'
import { getSubs, addSub, addSubsBatch, updateSub, deleteSub, deleteSubsBatch, toggleSub, parsePlaylistUrl } from '@/api/index.js'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppModal from '@/components/AppModal.vue'
import { useThemeStore } from '@/stores/theme.js'
import { animalIslandIcons } from '@/utils/animalIsland.js'

const theme = useThemeStore()
const isIsland = computed(() => theme.current === 'island')
const parseModalTitle = computed(() => `${isIsland.value ? '' : '🎵 '}${parsedResult.value?.title || '歌单解析结果'}`)
const subs = ref([])
const loading = ref(false)
const selectedIds = ref(new Set())
const filterText = ref('')
const filterType = ref('all')
const page = ref(1)
const pageSize = ref(100)
const deletingBatch = ref(false)

const filteredSubs = computed(() => subs.value.filter(sub => {
  const kw = filterText.value.trim().toLowerCase()
  if (kw && !String(sub.keyword || '').toLowerCase().includes(kw)) return false
  if (filterType.value !== 'all' && sub.type !== filterType.value) return false
  return true
}))
const totalPages = computed(() => Math.max(1, Math.ceil(filteredSubs.value.length / pageSize.value)))
const pagedSubs = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredSubs.value.slice(start, start + pageSize.value)
})
const selectedCount = computed(() => selectedIds.value.size)
const pageAllSelected = computed(() => pagedSubs.value.length > 0 && pagedSubs.value.every(s => selectedIds.value.has(s.id)))
watch([filterText, filterType, pageSize], () => { page.value = 1 })
watch(totalPages, n => { if (page.value > n) page.value = n })

// New sub form
const newSub = ref({ keyword: '', type: 'artist', quality: 'any', sites: [], source_preference: 'pt' })
const adding = ref(false)
const editingSub = ref(null)
const editForm = ref({ keyword: '', type: 'artist', quality: 'any', sites: 'all', source_preference: 'pt', enabled: true })
const savingEdit = ref(false)

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
const sourcePreferenceOptions = [
  { label: 'PT 优先', value: 'pt' },
  { label: '在线优先', value: 'online_first' },
  { label: '仅在线', value: 'online_only' },
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
      sites: newSub.value.sites,
      source_preference: newSub.value.source_preference,
    })
    newSub.value = { keyword: '', type: 'artist', quality: 'any', sites: [], source_preference: 'pt' }
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

function openEdit(sub) {
  editingSub.value = sub
  editForm.value = {
    keyword: sub.keyword,
    type: sub.type,
    quality: sub.quality,
    sites: sub.sites || 'all',
    source_preference: sub.source_preference || 'pt',
    enabled: sub.enabled,
  }
}

async function handleSaveEdit() {
  if (!editingSub.value || !editForm.value.keyword.trim()) return
  savingEdit.value = true
  try {
    await updateSub(editingSub.value.id, {
      keyword: editForm.value.keyword.trim(),
      type: editForm.value.type,
      quality: editForm.value.quality,
      sites: editForm.value.sites || 'all',
      source_preference: editForm.value.source_preference,
      enabled: editForm.value.enabled,
    })
    editingSub.value = null
    await loadSubs()
  } catch (e) {
    alert(e.message || '保存失败')
  } finally {
    savingEdit.value = false
  }
}

async function handleDelete(id) {
  if (!confirm('确认删除这个订阅？')) return
  try {
    await deleteSub(id)
    selectedIds.value.delete(id)
    selectedIds.value = new Set(selectedIds.value)
    await loadSubs()
  } catch (e) {
    console.error(e)
  }
}

function toggleSelect(id) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

function toggleSelectPage() {
  const next = new Set(selectedIds.value)
  if (pageAllSelected.value) pagedSubs.value.forEach(s => next.delete(s.id))
  else pagedSubs.value.forEach(s => next.add(s.id))
  selectedIds.value = next
}

function selectFiltered() {
  selectedIds.value = new Set(filteredSubs.value.map(s => s.id))
}

function clearSelection() {
  selectedIds.value = new Set()
}

async function handleBatchDeleteSelected() {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  if (!confirm(`确认删除选中的 ${ids.length} 个订阅？`)) return
  deletingBatch.value = true
  try {
    const res = await deleteSubsBatch({ ids })
    alert(`已删除 ${res.deleted || 0} 个订阅`)
    clearSelection()
    await loadSubs()
  } catch (e) {
    alert(e.message || '批量删除失败')
  } finally {
    deletingBatch.value = false
  }
}

async function handleDeleteFiltered() {
  const count = filteredSubs.value.length
  if (!count) return
  if (!confirm(`确认删除当前筛选的 ${count} 个订阅？这个操作不可撤销。`)) return
  deletingBatch.value = true
  try {
    const payload = {
      keyword_contains: filterText.value.trim(),
      type: filterType.value === 'all' ? '' : filterType.value,
      delete_all: !filterText.value.trim() && filterType.value === 'all',
    }
    const res = await deleteSubsBatch(payload)
    alert(`已删除 ${res.deleted || 0} 个订阅`)
    clearSelection()
    await loadSubs()
  } catch (e) {
    alert(e.message || '批量删除失败')
  } finally {
    deletingBatch.value = false
  }
}

function changePage(next) {
  page.value = Math.min(Math.max(1, next), totalPages.value)
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
  const items = parsedResult.value.songs.map(song => ({
    keyword: `${song.title} ${song.artist}`.trim(),
    type: 'song',
    quality: 'any',
    sites: 'all',
    source_preference: 'online_first',
  }))
  try {
    const res = await addSubsBatch(items, true)
    alert(`✅ 已添加 ${res.added || 0} 个订阅，跳过 ${res.skipped || 0} 个`)
    showParseModal.value = false
    playlistUrl.value = ''
    await loadSubs()
  } catch (e) {
    alert(e.message || '批量订阅失败')
  }
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
        <select v-model="newSub.source_preference">
          <option v-for="o in sourcePreferenceOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <AppButton variant="primary" :loading="adding" @click="handleAdd">添加</AppButton>
      </div>
    </div>

    <!-- 歌单链接解析 -->
    <div class="add-form">
      <h3 class="animal-page-title"><img v-if="isIsland" :src="animalIslandIcons.chat" alt="" /><span v-else>🔗</span><span>歌单链接解析</span></h3>
      <p class="form-hint">粘贴 QQ音乐 或 网易云 歌单链接，自动解析歌曲列表并批量订阅。歌单生成的歌曲订阅默认“在线优先”，在线失败时再回退 PT。</p>
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
    <AppModal v-if="showParseModal" :title="parseModalTitle" @close="showParseModal = false">
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

    <!-- 编辑订阅弹窗 -->
    <AppModal v-if="editingSub" title="编辑订阅" @close="editingSub = null">
      <div class="edit-form">
        <label>关键词</label>
        <input v-model="editForm.keyword" placeholder="关键词" />
        <label>类型</label>
        <select v-model="editForm.type">
          <option v-for="o in typeOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <label>品质</label>
        <select v-model="editForm.quality">
          <option v-for="o in qualityOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <label>站点</label>
        <input v-model="editForm.sites" placeholder="all 或 mteam,opencd" />
        <label>下载规则</label>
        <select v-model="editForm.source_preference">
          <option v-for="o in sourcePreferenceOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <label class="checkbox-row"><input type="checkbox" v-model="editForm.enabled" /> 启用</label>
        <div class="parse-actions">
          <AppButton variant="primary" :loading="savingEdit" @click="handleSaveEdit">保存</AppButton>
          <AppButton variant="ghost" @click="editingSub = null">取消</AppButton>
        </div>
      </div>
    </AppModal>

    <!-- 订阅列表 -->
    <div class="subs-list">
      <div class="subs-toolbar">
        <div class="subs-filter-row">
          <input v-model="filterText" placeholder="筛选关键词，例：歌手/歌名" />
          <select v-model="filterType">
            <option value="all">全部类型</option>
            <option v-for="o in typeOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <select v-model.number="pageSize">
            <option :value="50">每页 50</option>
            <option :value="100">每页 100</option>
            <option :value="200">每页 200</option>
            <option :value="500">每页 500</option>
          </select>
        </div>
        <div class="subs-bulk-row">
          <span>总 {{ subs.length }} 个，筛选 {{ filteredSubs.length }} 个，已选 {{ selectedCount }} 个</span>
          <AppButton size="sm" variant="ghost" @click="selectFiltered">选择当前筛选</AppButton>
          <AppButton size="sm" variant="ghost" :disabled="!selectedCount" @click="clearSelection">清空选择</AppButton>
          <AppButton size="sm" variant="danger" :disabled="!selectedCount" :loading="deletingBatch" @click="handleBatchDeleteSelected">删除选中</AppButton>
          <AppButton size="sm" variant="danger" :disabled="!filteredSubs.length" :loading="deletingBatch" @click="handleDeleteFiltered">删除当前筛选</AppButton>
        </div>
      </div>
      <div v-if="loading" class="loading-text">加载中...</div>
      <div v-else-if="subs.length === 0" class="empty-text">暂无订阅</div>
      <div v-else class="subs-results">
        <div class="table-wrap">
          <table class="subs-table">
          <thead>
            <tr>
              <th><input type="checkbox" :checked="pageAllSelected" @change="toggleSelectPage" /></th>
              <th>类型</th>
              <th>关键词</th>
              <th>品质</th>
              <th>规则</th>
              <th>状态</th>
              <th>最近搜索</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="sub in pagedSubs" :key="sub.id">
              <td><input type="checkbox" :checked="selectedIds.has(sub.id)" @change="toggleSelect(sub.id)" /></td>
              <td><AppBadge :color="typeBadgeColor(sub.type)">{{ sub.type }}</AppBadge></td>
              <td class="keyword-cell">{{ sub.keyword }}</td>
              <td>{{ sub.quality }}</td>
              <td>{{ sourcePreferenceOptions.find(o => o.value === (sub.source_preference || 'pt'))?.label || 'PT 优先' }}</td>
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
                  <button class="icon-btn" @click="openEdit(sub)" title="编辑">✏️</button>
                  <button class="icon-btn danger" @click="handleDelete(sub.id)" title="删除">🗑</button>
                </div>
              </td>
            </tr>
          </tbody>
          </table>
        </div>

        <div class="sub-cards">
          <article v-for="sub in pagedSubs" :key="`card-${sub.id}`" class="sub-card" :class="{ selected: selectedIds.has(sub.id) }">
            <label class="card-select"><input type="checkbox" :checked="selectedIds.has(sub.id)" @change="toggleSelect(sub.id)" /> 选择</label>
            <div class="sub-card-head">
              <h3>{{ sub.keyword }}</h3>
              <AppBadge :color="sub.enabled ? 'green' : 'dim'">
                {{ sub.enabled ? '启用' : '停用' }}
              </AppBadge>
            </div>
            <div class="sub-chip-row">
              <AppBadge :color="typeBadgeColor(sub.type)">{{ sub.type }}</AppBadge>
              <span class="sub-chip">{{ sub.quality }}</span>
              <span class="sub-chip">{{ sourcePreferenceOptions.find(o => o.value === (sub.source_preference || 'pt'))?.label || 'PT 优先' }}</span>
            </div>
            <div class="sub-last-search">
              <span>最近搜索</span>
              {{ sub.last_search_at ? new Date(sub.last_search_at).toLocaleString() : '-' }}
            </div>
            <div class="action-btns mobile">
              <button class="icon-btn" @click="handleToggle(sub.id)" :title="sub.enabled ? '停用' : '启用'">
                {{ sub.enabled ? '⏸ 停用' : '▶ 启用' }}
              </button>
              <button class="icon-btn" @click="openEdit(sub)" title="编辑">✏️ 编辑</button>
              <button class="icon-btn danger" @click="handleDelete(sub.id)" title="删除">🗑 删除</button>
            </div>
          </article>
        </div>
        <div v-if="filteredSubs.length > pageSize" class="pager">
          <AppButton variant="ghost" size="sm" :disabled="page <= 1" @click="changePage(page - 1)">上一页</AppButton>
          <span>第 {{ page }} / {{ totalPages }} 页</span>
          <AppButton variant="ghost" size="sm" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</AppButton>
        </div>
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
.subs-list { display: flex; flex-direction: column; gap: 12px; }
.subs-toolbar { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.subs-filter-row, .subs-bulk-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.subs-filter-row input { flex: 1; min-width: 180px; }
.subs-filter-row select { min-width: 110px; }
.subs-bulk-row { color: var(--text-dim); font-size: 13px; }
.loading-text, .empty-text { color: var(--text-dim); padding: 20px 0; }
.subs-results { display: block; }
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
.edit-form { display: grid; grid-template-columns: 80px minmax(240px, 1fr); gap: 12px; align-items: center; min-width: 420px; }
.edit-form label { color: var(--text-dim); font-size: 13px; }
.checkbox-row { grid-column: 2; display: flex; align-items: center; gap: 8px; color: var(--text); }
.edit-form .parse-actions { grid-column: 2; }
.parse-meta { font-size: 13px; color: var(--text-dim); }
.parse-songs { display: flex; flex-direction: column; gap: 4px; max-height: 350px; overflow-y: auto; }
.parse-song-row { display: flex; align-items: center; gap: 10px; padding: 6px 8px; border-radius: var(--radius-sm); font-size: 13px; }
.parse-song-row:hover { background: var(--surface-hover); }
.parse-idx { color: var(--text-muted); min-width: 24px; text-align: right; }
.parse-song-title { font-weight: 500; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.parse-song-artist { color: var(--text-dim); flex-shrink: 0; }
.parse-actions { display: flex; gap: 10px; padding-top: 12px; border-top: 1px solid var(--border); }
.sub-cards { display: none; }
.sub-card { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-elevated); padding: 14px; }
.sub-card.selected { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--bg-elevated)); }
.card-select { display: inline-flex; align-items: center; gap: 6px; color: var(--text-dim); font-size: 12px; margin-bottom: 8px; }
.sub-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.sub-card-head h3 { min-width: 0; margin: 0; font-size: 15px; line-height: 1.35; font-weight: 700; overflow-wrap: anywhere; }
.sub-chip-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; }
.sub-chip { border: 1px solid var(--border); border-radius: 999px; padding: 3px 8px; color: var(--text-dim); background: var(--surface); font-size: 12px; }
.sub-last-search { margin-top: 12px; color: var(--text-dim); font-size: 13px; }
.sub-last-search span { display: block; color: var(--text-muted); font-size: 11px; margin-bottom: 2px; }
.action-btns.mobile { margin-top: 12px; flex-wrap: wrap; }
.action-btns.mobile .icon-btn { border: 1px solid var(--border); background: var(--surface); padding: 6px 9px; font-size: 13px; }
.pager { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 14px 0; color: var(--text-dim); font-size: 13px; }

@media (max-width: 768px) {
  .add-form { padding: 14px; border-radius: 16px; }
  .form-row, .subs-filter-row, .subs-bulk-row { flex-direction: column; align-items: stretch; }
  .input-keyword { min-width: 0; width: 100%; }
  .parse-result { min-width: unset; }
  .edit-form { min-width: 0; grid-template-columns: 1fr; gap: 6px; }
  .checkbox-row, .edit-form .parse-actions { grid-column: auto; }
  .parse-actions { flex-wrap: wrap; }
  .parse-song-row { align-items: flex-start; }
  .parse-song-artist { display: none; }
  .table-wrap { display: none; }
  .sub-cards { display: flex; flex-direction: column; gap: 12px; }
}
@media (max-width: 420px) {
  .subs-view { padding: 16px; }
}

</style>