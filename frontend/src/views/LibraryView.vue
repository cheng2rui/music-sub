<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getLibraryStats, getLibraryAlbums, getLibraryHealth, rescanLibraryMetadata, scanLibrary, rescrapeAlbums, getLibraryJob, getAlbumTracks, getAlbumCover, getFile, rescrapeLibrary, updateFile } from '@/api/index.js'
import LibraryToolsModal from '@/components/LibraryToolsModal.vue'
import MusicCover from '@/components/MusicCover.vue'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppModal from '@/components/AppModal.vue'
import { usePlayerStore } from '@/stores/player.js'

const router = useRouter()
const stats = ref({ total_files: 0, scraped: 0, unscraped: 0, artists: 0, albums: 0 })
const albums = ref([])
const searchQ = ref('')
const sortMode = ref('updated')
const viewMode = ref('grid')
const loading = ref(false)
let searchTimer = null
const loadingMore = ref(false)
const albumLimit = 200
const albumOffset = ref(0)
const hasMoreAlbums = ref(false)

const selectedAlbum = ref(null)
const albumTracks = ref([])
const showAlbumModal = ref(false)

const selectedTrack = ref(null)
const showTrackModal = ref(false)
const trackEdit = ref({})
const savingTrack = ref(false)
const player = usePlayerStore()

const scraping = ref(false)
const scanning = ref(false)
const scanJob = ref(null)
let scanPollTimer = null

const showHealthModal = ref(false)
const showToolsModal = ref(false)
const toolsContext = ref({})
function openToolbox(ctx = {}) {
  toolsContext.value = ctx
  showToolsModal.value = true
}
const healthLoading = ref(false)
const healthRescraping = ref('')
const healthKind = ref('missing_cover')
const healthTotals = ref({ missing_cover: 0, missing_lyrics: 0, missing_duration: 0, unknown_artist: 0, unscraped: 0, cue_candidates: 0 })
const healthItems = ref([])
const healthKinds = [
  { id: 'missing_cover', label: '缺封面' },
  { id: 'missing_lyrics', label: '缺歌词' },
  { id: 'missing_duration', label: '缺时长' },
  { id: 'unknown_artist', label: '艺人异常' },
  { id: 'unscraped', label: '未刮削' },
  { id: 'cue_candidates', label: 'CUE整轨' }
]
const healthLabels = Object.fromEntries(healthKinds.map(k => [k.id, k.label]))
const scanHealthOrder = ['missing_cover', 'missing_lyrics', 'missing_duration', 'unknown_artist', 'unscraped', 'cue_candidates']

async function openHealthModal(kind = healthKind.value) {
  showHealthModal.value = true
  await loadHealth(kind)
}

async function loadHealth(kind) {
  healthKind.value = kind
  healthLoading.value = true
  try {
    const data = await getLibraryHealth({ kind, limit: 200 })
    healthItems.value = Array.isArray(data?.items) ? data.items : []
    if (data?.totals) healthTotals.value = { ...healthTotals.value, ...data.totals }
    else healthTotals.value[kind] = data?.total ?? healthItems.value.length
  } catch (e) { console.error(e) }
  finally { healthLoading.value = false }
}

async function rescrapeHealthAlbum(item) {
  const id = `${item.artist}::${item.album}`
  healthRescraping.value = id
  try {
    await rescrapeLibrary({ album_artist: item.artist, album_name: item.album })
    await Promise.all([loadHealth(healthKind.value), loadStats()])
  } catch (e) { console.error(e) }
  finally { healthRescraping.value = '' }
}

function openHealthAlbum(item) {
  showHealthModal.value = false
  router.push({ name: 'album', query: { artist: item.artist, album: item.album } })
}

const batchBusy = ref(false)
const batchJob = ref(null)
let batchPollTimer = null

async function pollBatchJob(jobId) {
  try {
    batchJob.value = await getLibraryJob(jobId)
  } catch (e) {
    console.warn('poll job failed', e)
    return
  }
  if (batchJob.value && (batchJob.value.status === 'running' || batchJob.value.status === 'queued')) {
    batchPollTimer = setTimeout(() => pollBatchJob(jobId), 1500)
  } else {
    batchBusy.value = false
    await Promise.all([loadHealth(healthKind.value), loadStats()])
  }
}

async function batchRescrapeCurrentKind() {
  if (!healthItems.value.length) return
  if (healthKind.value === 'cue_candidates') {
    openToolbox({ file_ids: healthItems.value.map(it => it.sample_track_id).filter(Boolean), preferred_tool: 'cue_candidates' })
    return
  }
  batchBusy.value = true
  batchJob.value = null
  if (batchPollTimer) { clearTimeout(batchPollTimer); batchPollTimer = null }
  try {
    const albums = healthItems.value.map(it => ({ artist: it.artist, album: it.album }))
    const res = await rescrapeAlbums(albums)
    if (res?.job_id) {
      pollBatchJob(res.job_id)
    } else {
      batchBusy.value = false
      await Promise.all([loadHealth(healthKind.value), loadStats()])
    }
  } catch (e) {
    console.error(e)
    batchBusy.value = false
  }
}

async function batchRescanMissingDuration() {
  batchBusy.value = true
  try {
    await rescanLibraryMetadata({})
    await Promise.all([loadHealth(healthKind.value), loadStats()])
  } catch (e) { console.error(e) }
  finally { batchBusy.value = false }
}

async function pollScanJob(jobId) {
  try {
    scanJob.value = await getLibraryJob(jobId)
  } catch (e) {
    console.warn('poll scan job failed', e)
    scanning.value = false
    return
  }
  if (scanJob.value && (scanJob.value.status === 'running' || scanJob.value.status === 'queued')) {
    scanPollTimer = setTimeout(() => pollScanJob(jobId), 1500)
  } else {
    scanning.value = false
    await Promise.all([loadStats(), loadAlbums(true)])
  }
}

async function runLibraryScan() {
  scanning.value = true
  scanJob.value = null
  if (scanPollTimer) { clearTimeout(scanPollTimer); scanPollTimer = null }
  try {
    const res = await scanLibrary({})
    if (res?.job_id) pollScanJob(res.job_id)
    else scanning.value = false
  } catch (e) {
    console.error(e)
    scanning.value = false
  }
}

function scanHealthValue(key) {
  return scanJob.value?.summary?.health?.[key] ?? 0
}

function hasScanHealthReport() {
  return !!scanJob.value?.summary?.health
}

function openScanHealth(kind) {
  openHealthModal(kind)
}

async function loadStats() {
  try {
    stats.value = await getLibraryStats()
  } catch (e) { console.error(e) }
}

async function loadAlbums(reset = true) {
  if (reset) {
    loading.value = true
    albumOffset.value = 0
  } else {
    loadingMore.value = true
  }
  try {
    const params = { limit: albumLimit, offset: reset ? 0 : albumOffset.value, sort: sortMode.value }
    if (searchQ.value.trim()) params.q = searchQ.value.trim()
    const data = await getLibraryAlbums(params)
    const rows = Array.isArray(data) ? data : []
    albums.value = reset ? rows : albums.value.concat(rows)
    albumOffset.value = albums.value.length
    hasMoreAlbums.value = rows.length === albumLimit
  } catch (e) { console.error(e) }
  finally { loading.value = false; loadingMore.value = false }
}

async function loadMoreAlbums() {
  if (!hasMoreAlbums.value || loadingMore.value) return
  await loadAlbums(false)
}

function openAlbum(artist, album) {
  router.push({ name: 'album', query: { artist, album } })
}

async function rescrapeAlbum() {
  if (!selectedAlbum.value) return
  scraping.value = true
  try {
    await rescrapeLibrary({ album_artist: selectedAlbum.value.artist, album_name: selectedAlbum.value.album })
    albumTracks.value = await getAlbumTracks(selectedAlbum.value.artist, selectedAlbum.value.album)
    await loadStats()
  } catch (e) { console.error(e) }
  finally { scraping.value = false }
}

function playTrack(track) {
  player.playTrack(track)
}

async function openTrack(id) {
  selectedTrack.value = await getFile(id)
  trackEdit.value = {
    title: selectedTrack.value.title,
    artist: selectedTrack.value.artist,
    album: selectedTrack.value.album,
    year: selectedTrack.value.year,
    genre: selectedTrack.value.genre
  }
  showTrackModal.value = true
}

async function saveTrack() {
  if (!selectedTrack.value) return
  savingTrack.value = true
  try {
    await updateFile(selectedTrack.value.id, trackEdit.value)
    selectedTrack.value = await getFile(selectedTrack.value.id)
  } catch (e) { console.error(e) }
  finally { savingTrack.value = false }
}

async function rescrapeTrack() {
  if (!selectedTrack.value) return
  scraping.value = true
  try {
    await rescrapeLibrary({ file_ids: [selectedTrack.value.id] })
    selectedTrack.value = await getFile(selectedTrack.value.id)
    trackEdit.value = { ...selectedTrack.value }
    await loadStats()
  } catch (e) { console.error(e) }
  finally { scraping.value = false }
}

async function handleScrapeUnscraped() {
  scraping.value = true
  try {
    await rescrapeLibrary({})
    await loadStats()
    await loadAlbums()
  } catch (e) { console.error(e) }
  finally { scraping.value = false }
}

function coverUrl(artist, album) {
  return getAlbumCover(artist, album)
}

function debounceLoadAlbums() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => loadAlbums(true), 300)
}

function formatDuration(s) {
  if (!s) return '-'
  const total = Math.floor(s)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const sec = total % 60
  if (h) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
  return `${m}:${sec.toString().padStart(2, '0')}`
}

function formatAlbumMeta(item) {
  const parts = []
  if (item.year) parts.push(item.year)
  parts.push(`${item.track_count} 首`)
  if (item.total_duration) parts.push(formatDuration(item.total_duration))
  if (item.formats?.length) parts.push(item.formats.slice(0, 2).join('/'))
  if (item.avg_bitrate) parts.push(`${item.avg_bitrate}kbps`)
  return parts.join(' · ')
}

onMounted(() => { loadStats(); loadAlbums() })
</script>

<template>
  <div class="library-view">
    <!-- 统计卡片 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-val">{{ stats.total_files }}</div>
        <div class="stat-label">总文件</div>
      </div>
      <div class="stat-card">
        <div class="stat-val text-success">{{ stats.scraped }}</div>
        <div class="stat-label">已刮削</div>
      </div>
      <div class="stat-card">
        <div class="stat-val text-warning">{{ stats.unscraped }}</div>
        <div class="stat-label">未刮削</div>
      </div>
      <div class="stat-card">
        <div class="stat-val">{{ stats.artists }}</div>
        <div class="stat-label">艺术家</div>
      </div>
      <div class="stat-card">
        <div class="stat-val">{{ stats.albums }}</div>
        <div class="stat-label">专辑</div>
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <input v-model="searchQ" placeholder="搜索专辑 / 艺术家 / 歌名..." class="search-input" @input="debounceLoadAlbums" />
      <select v-model="sortMode" class="sort-select" @change="loadAlbums(true)">
        <option value="updated">最近入库</option>
        <option value="name">专辑名</option>
        <option value="artist">艺术家</option>
        <option value="tracks">曲目数</option>
        <option value="year">年份</option>
      </select>
      <div class="view-toggles">
        <button :class="['view-btn', { active: viewMode === 'grid' }]" @click="viewMode = 'grid'">▦</button>
        <button :class="['view-btn', { active: viewMode === 'list' }]" @click="viewMode = 'list'">☰</button>
      </div>
      <AppButton variant="ghost" size="sm" :loading="scraping" @click="handleScrapeUnscraped">
        刮削未完成
      </AppButton>
      <AppButton variant="ghost" size="sm" :loading="scanning" @click="runLibraryScan">
        扫描资料库
      </AppButton>
      <AppButton variant="ghost" size="sm" @click="openHealthModal">
        治理
      </AppButton>
      <AppButton variant="ghost" size="sm" @click="openToolbox()">
        工具箱
      </AppButton>
    </div>

    <div v-if="scanJob" class="scan-status">
      <div class="scan-status-line">
        资料库扫描：{{ scanJob.status }} · {{ scanJob.progress }} / {{ scanJob.total || '?' }}
        <span v-if="scanJob.summary?.created !== undefined"> · 新增 {{ scanJob.summary.created }} · 更新 {{ scanJob.summary.updated }} · 移除 {{ scanJob.summary.removed || 0 }} · 错误 {{ scanJob.summary.errors }}</span>
        <span v-else-if="scanJob.summary?.current"> · {{ scanJob.summary.current }}</span>
      </div>
      <div v-if="hasScanHealthReport()" class="scan-health-report">
        <button
          v-for="key in scanHealthOrder"
          :key="key"
          class="scan-health-chip"
          :class="{ warn: scanHealthValue(key) > 0 }"
          @click="openScanHealth(key)"
        >
          {{ healthLabels[key] }} <strong>{{ scanHealthValue(key) }}</strong>
        </button>
        <span class="scan-health-chip" :class="{ warn: scanJob.summary.health.missing_files > 0 }">文件缺失 <strong>{{ scanJob.summary.health.missing_files || 0 }}</strong></span>
      </div>
      <div v-if="hasScanHealthReport()" class="scan-next-actions">
        <AppButton variant="ghost" size="sm" @click="openHealthModal">打开治理</AppButton>
        <AppButton variant="ghost" size="sm" @click="openToolbox">打开工具箱</AppButton>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-text">加载中...</div>

    <!-- 专辑网格视图 -->
    <div v-else-if="viewMode === 'grid'" class="album-grid">
      <div
        v-for="item in albums"
        :key="item.artist + item.album"
        class="album-card"
        @click="openAlbum(item.artist, item.album)"
      >
        <MusicCover :src="coverUrl(item.artist, item.album)" />
        <div class="album-info">
          <div class="album-name">{{ item.album }}</div>
          <div class="album-artist">{{ item.artist }}</div>
          <div class="album-meta">{{ formatAlbumMeta(item) }}</div>
        </div>
      </div>
    </div>

    <!-- 列表视图 -->
    <div v-else class="album-list">
      <div
        v-for="item in albums"
        :key="item.artist + item.album"
        class="album-row"
        @click="openAlbum(item.artist, item.album)"
      >
        <MusicCover :src="coverUrl(item.artist, item.album)" class="row-cover" />
        <div class="row-info">
          <div class="row-name">{{ item.album }}</div>
          <div class="row-sub">{{ item.artist }} · {{ formatAlbumMeta(item) }}</div>
        </div>
        <div class="row-count">{{ item.track_count }} 首</div>
        <AppBadge :color="item.scraped_count === item.track_count ? 'green' : 'orange'">
          {{ item.scraped_count }}/{{ item.track_count }}
        </AppBadge>
      </div>
    </div>

    <div v-if="!loading && hasMoreAlbums" class="load-more-row">
      <AppButton variant="ghost" size="sm" :loading="loadingMore" @click="loadMoreAlbums">
        加载更多
      </AppButton>
    </div>

    <!-- 专辑详情弹窗 -->
    <AppModal v-if="showAlbumModal" :title="selectedAlbum?.album" @close="showAlbumModal = false">
      <div class="album-modal">
        <img :src="coverUrl(selectedAlbum?.artist, selectedAlbum?.album)" class="modal-cover" />
        <div class="modal-meta">{{ selectedAlbum?.artist }} · {{ selectedAlbum?.album }}</div>
        <div class="modal-actions">
          <AppButton variant="primary" size="sm" @click="albumTracks[0] && playTrack(albumTracks[0])">播放第一首</AppButton>
          <AppButton variant="ghost" size="sm" :loading="scraping" @click="rescrapeAlbum">重新刮削</AppButton>
          <AppButton variant="ghost" size="sm" @click="openToolbox({ album_artist: selectedAlbum?.artist, album_name: selectedAlbum?.album })">工具箱</AppButton>
        </div>
        <div class="track-list">
          <div
            v-for="track in albumTracks"
            :key="track.id"
            class="track-row"
          >
            <div class="track-info" @click="openTrack(track.id)">
              <div class="track-title">{{ track.title }}</div>
              <div class="track-sub">{{ track.artist }} · {{ track.album }}</div>
            </div>
            <div class="track-actions">
              <button class="play-btn" @click.stop="playTrack(track)">{{ player.currentId === track.id ? '正在播放' : '播放' }}</button>
              <AppBadge :color="track.scraped ? 'green' : 'orange'">
                {{ track.scraped ? '已刮削' : '未刮削' }}
              </AppBadge>
            </div>
          </div>
        </div>
      </div>
    </AppModal>

    <!-- 曲目详情弹窗 -->
    <AppModal v-if="showTrackModal && selectedTrack" title="曲目详情" @close="showTrackModal = false">
      <div class="track-modal">
        <div class="detail-actions">
          <AppButton variant="primary" size="sm" @click="playTrack(selectedTrack)">
            {{ player.currentId === selectedTrack.id ? '正在全局播放' : '用全局播放器播放' }}
          </AppButton>
        </div>
        <div class="detail-grid">
          <div class="detail-row"><span class="detail-label">路径</span><span class="detail-val text-dim">{{ selectedTrack.file_path }}</span></div>
          <div class="detail-row"><span class="detail-label">艺人</span><span class="detail-val">{{ selectedTrack.artist }}</span></div>
          <div class="detail-row"><span class="detail-label">专辑</span><span class="detail-val">{{ selectedTrack.album }}</span></div>
          <div class="detail-row"><span class="detail-label">标题</span><span class="detail-val">{{ selectedTrack.title }}</span></div>
          <div class="detail-row"><span class="detail-label">年份</span><span class="detail-val">{{ selectedTrack.year }}</span></div>
          <div class="detail-row"><span class="detail-label">流派</span><span class="detail-val">{{ selectedTrack.genre || '-' }}</span></div>
          <div class="detail-row"><span class="detail-label">格式</span><span class="detail-val">{{ selectedTrack.format }}</span></div>
          <div class="detail-row"><span class="detail-label">比特率</span><span class="detail-val">{{ selectedTrack.bitrate || '-' }}</span></div>
          <div class="detail-row"><span class="detail-label">采样率</span><span class="detail-val">{{ selectedTrack.sample_rate || '-' }}</span></div>
          <div class="detail-row"><span class="detail-label">声道</span><span class="detail-val">{{ selectedTrack.channels || '-' }}</span></div>
          <div class="detail-row"><span class="detail-label">时长</span><span class="detail-val">{{ formatDuration(selectedTrack.duration) }}</span></div>
          <div class="detail-row" v-if="selectedTrack.lyrics"><span class="detail-label">歌词</span><pre class="detail-val lyrics">{{ selectedTrack.lyrics }}</pre></div>
        </div>
        <div class="tag-edit">
          <h4>编辑标签</h4>
          <div class="tag-row">
            <label>标题</label><input v-model="trackEdit.title" />
          </div>
          <div class="tag-row">
            <label>艺人</label><input v-model="trackEdit.artist" />
          </div>
          <div class="tag-row">
            <label>专辑</label><input v-model="trackEdit.album" />
          </div>
          <div class="tag-row">
            <label>年份</label><input v-model="trackEdit.year" type="number" />
          </div>
          <div class="tag-row">
            <label>流派</label><input v-model="trackEdit.genre" />
          </div>
          <div class="tag-actions">
            <AppButton variant="primary" size="sm" :loading="savingTrack" @click="saveTrack">保存</AppButton>
            <AppButton variant="ghost" size="sm" :loading="scraping" @click="rescrapeTrack">重新刮削</AppButton>
          </div>
        </div>
      </div>
    </AppModal>

    <AppModal v-if="showHealthModal" title="音乐库治理" @close="showHealthModal = false">
      <div class="health-modal">
        <div class="health-tabs">
          <button
            v-for="k in healthKinds"
            :key="k.id"
            :class="['health-tab', { active: healthKind === k.id }]"
            @click="loadHealth(k.id)"
          >
            {{ k.label }}
            <span v-if="healthTotals[k.id]" class="health-count">{{ healthTotals[k.id] }}</span>
          </button>
        </div>
        <div class="health-batch-row">
          <AppButton
            v-if="healthKind === 'missing_duration'"
            variant="primary"
            size="sm"
            :loading="batchBusy"
            @click="batchRescanMissingDuration"
          >重读本地元数据</AppButton>
          <AppButton
            variant="ghost"
            size="sm"
            :disabled="!healthItems.length"
            :loading="batchBusy"
            @click="batchRescrapeCurrentKind"
          >{{ healthKind === 'cue_candidates' ? '打开工具箱批量拆分' : `批量重刮削当前 ${healthItems.length} 项` }}</AppButton>
        </div>
        <div v-if="batchJob" class="job-progress">
          <div class="job-progress-head">
            <span>后台任务: {{ batchJob.status }}</span>
            <span>{{ batchJob.progress }} / {{ batchJob.total }}</span>
          </div>
          <div class="job-progress-bar">
            <div :style="`width:${batchJob.total ? Math.round(batchJob.progress * 100 / batchJob.total) : 0}%`"></div>
          </div>
          <div v-if="batchJob.steps?.length" class="job-progress-list">
            <div
              v-for="step in batchJob.steps"
              :key="step.label"
              :class="['job-step', step.status]"
            >
              <span class="job-step-status">{{ step.status }}</span>
              <span class="job-step-label">{{ step.label }}</span>
              <span v-if="step.message" class="job-step-msg">{{ step.message }}</span>
            </div>
          </div>
        </div>
        <div v-if="healthLoading" class="loading-text">扫描中...</div>
        <div v-else-if="!healthItems.length" class="loading-text">该类别暂无问题，干净。</div>
        <div v-else class="health-list">
          <div v-for="item in healthItems" :key="`${item.artist}-${item.album}`" class="health-row">
            <div class="health-info" @click="openHealthAlbum(item)">
              <div class="health-album">{{ item.album }}</div>
              <div class="health-sub">{{ item.artist }} · {{ item.track_count }} 首</div>
            </div>
            <div class="health-actions">
              <AppBadge :color="item.has_cover ? 'green' : 'orange'">
                {{ item.has_cover ? '有封面' : '无封面' }}
              </AppBadge>
              <AppButton
                variant="primary"
                size="sm"
                :loading="healthRescraping === `${item.artist}::${item.album}`"
                @click="healthKind === 'cue_candidates' ? openToolbox({ file_ids: [item.sample_track_id], preferred_tool: 'cue_candidates' }) : rescrapeHealthAlbum(item)"
              >{{ healthKind === 'cue_candidates' ? '拆分' : '重刮削' }}</AppButton>
            </div>
          </div>
        </div>
      </div>
    </AppModal>

    <LibraryToolsModal :open="showToolsModal" :context="toolsContext" @close="showToolsModal = false" />
  </div>
</template>

<style scoped>
.library-view { padding: 24px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; height: 100%; }
.stats-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 16px; text-align: center; }
.stat-val { font-size: 24px; font-weight: 700; }
.stat-label { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.scan-status { margin: 10px 0; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); color: var(--text-dim); font-size: 12px; display: flex; flex-direction: column; gap: 8px; }
.scan-status-line { color: var(--text-dim); }
.scan-health-report { display: flex; gap: 6px; flex-wrap: wrap; }
.scan-health-chip { border: 1px solid var(--border); border-radius: 999px; padding: 5px 9px; background: var(--bg-elevated); color: var(--text-dim); font-size: 12px; cursor: default; }
button.scan-health-chip { cursor: pointer; }
.scan-health-chip.warn { border-color: rgba(255,193,7,.38); color: var(--warning); }
.scan-health-chip strong { margin-left: 4px; color: var(--text); }
.scan-next-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.search-input { flex: 1; min-width: 220px; }
.sort-select { min-width: 120px; background: var(--surface); border: 1px solid var(--border); color: var(--text); border-radius: var(--radius-md); padding: 8px 10px; }
.view-toggles { display: flex; gap: 4px; }
.view-btn { background: none; border: 1px solid var(--border); color: var(--text-dim); cursor: pointer; padding: 6px 10px; border-radius: var(--radius-md); font-size: 14px; }
.view-btn.active { background: var(--accent); color: #000; border-color: var(--accent); }
.loading-text { color: var(--text-dim); padding: 20px 0; }
.load-more-row { display: flex; justify-content: center; padding: 8px 0 24px; }
.album-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; }
.album-card { display: flex; flex-direction: column; gap: 8px; cursor: pointer; }
.album-info { display: flex; flex-direction: column; gap: 2px; }
.album-name { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.album-artist { font-size: 12px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.album-meta { font-size: 11px; color: var(--text-muted); }
.album-list { display: flex; flex-direction: column; gap: 4px; }
.album-row { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-radius: var(--radius-md); cursor: pointer; transition: background 0.15s; }
.album-row:hover { background: var(--surface-hover); }
.row-cover { width: 48px; height: 48px; border-radius: var(--radius-sm); flex-shrink: 0; }
.row-info { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.row-name { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row-sub { font-size: 12px; color: var(--text-dim); }
.row-count { color: var(--text-dim); font-size: 13px; }
.album-modal { display: flex; flex-direction: column; gap: 14px; min-width: 440px; }
.modal-cover { width: 180px; height: 180px; border-radius: var(--radius-lg); object-fit: cover; }
.modal-meta { font-size: 14px; color: var(--text-dim); }
.modal-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.track-list { display: flex; flex-direction: column; gap: 4px; max-height: 350px; overflow-y: auto; }
.track-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 8px; border-radius: var(--radius-sm); cursor: pointer; }
.track-row:hover { background: var(--surface-hover); }
.track-info { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.track-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.play-btn { border: 1px solid var(--border); background: transparent; color: var(--text-dim); border-radius: var(--radius-sm); padding: 4px 8px; cursor: pointer; font-size: 12px; }
.play-btn:hover { color: var(--text); background: var(--surface); }
.track-title { font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.track-sub { font-size: 12px; color: var(--text-dim); }
.track-modal { display: flex; flex-direction: column; gap: 20px; min-width: 460px; }
.detail-actions { display: flex; gap: 8px; }
.detail-grid { display: flex; flex-direction: column; gap: 8px; }
.detail-row { display: flex; gap: 12px; align-items: flex-start; }
.detail-label { font-size: 12px; color: var(--text-dim); min-width: 60px; }
.detail-val { font-size: 14px; }
.lyrics { font-size: 12px; color: var(--text-dim); white-space: pre-wrap; max-height: 120px; overflow-y: auto; background: var(--surface); padding: 8px; border-radius: var(--radius-md); margin: 0; }
.tag-edit { display: flex; flex-direction: column; gap: 10px; border-top: 1px solid var(--border); padding-top: 16px; }
.tag-edit h4 { font-size: 14px; font-weight: 600; }
.tag-row { display: flex; align-items: center; gap: 10px; }
.tag-row label { font-size: 13px; color: var(--text-dim); min-width: 50px; }
.tag-row input { flex: 1; }
.tag-actions { display: flex; gap: 8px; margin-top: 4px; }
.health-modal { display: flex; flex-direction: column; gap: 14px; min-width: 460px; }
.health-tabs { display: flex; flex-wrap: wrap; gap: 6px; }
.health-tab { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; border: 1px solid var(--border); background: transparent; color: var(--text-dim); cursor: pointer; font-size: 12px; }
.health-tab.active { background: var(--accent); border-color: var(--accent); color: #000; }
.health-count { background: rgba(255,255,255,.18); border-radius: 999px; padding: 0 6px; font-size: 11px; }
.health-tab.active .health-count { background: rgba(0,0,0,.18); }
.health-list { display: flex; flex-direction: column; gap: 4px; max-height: 360px; overflow-y: auto; }
.health-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 8px 10px; border-radius: var(--radius-sm); }
.health-row:hover { background: var(--surface-hover); }
.health-info { flex: 1; min-width: 0; cursor: pointer; }
.health-album { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.health-sub { font-size: 12px; color: var(--text-dim); }
.health-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.health-batch-row { display: flex; gap: 8px; flex-wrap: wrap; }
.job-progress { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); }
.job-progress-head { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-dim); }
.job-progress-bar { height: 6px; background: var(--bg-elevated); border-radius: 999px; overflow: hidden; }
.job-progress-bar > div { height: 100%; background: var(--accent); transition: width .25s; }
.job-progress-list { max-height: 180px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
.job-step { display: grid; grid-template-columns: 64px minmax(0,1fr) auto; gap: 8px; align-items: center; font-size: 12px; }
.job-step-status { text-transform: uppercase; font-weight: 700; color: var(--text-muted); }
.job-step.ok .job-step-status { color: var(--success, #4ade80); }
.job-step.failed .job-step-status { color: var(--danger, #f87171); }
.job-step.running .job-step-status { color: var(--accent); }
.job-step-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text); }
.job-step-msg { color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

@media (max-width: 768px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .toolbar { align-items: stretch; }
  .sort-select { width: 100%; }
  .album-grid { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px; }
  .track-modal { min-width: unset; width: 100%; }
  .tag-row { flex-direction: column; align-items: stretch; gap: 4px; }
  .tag-row label { min-width: unset; }
}
</style>