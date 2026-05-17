<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getLibraryStats, getLibraryAlbums, getAlbumTracks, getAlbumCover, getFile, rescrapeLibrary, updateFile } from '@/api/index.js'
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
  </div>
</template>

<style scoped>
.library-view { padding: 24px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; height: 100%; }
.stats-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 16px; text-align: center; }
.stat-val { font-size: 24px; font-weight: 700; }
.stat-label { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
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