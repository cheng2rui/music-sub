<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getLibraryFiles, getAlbumTracks, getAlbumCover, getFile, rescrapeLibrary, updateFile, completeAlbum, applyLibraryTool } from '@/api/index.js'
import { usePlayerStore } from '@/stores/player.js'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppModal from '@/components/AppModal.vue'

const route = useRoute()
const router = useRouter()
const player = usePlayerStore()

const artist = computed(() => String(route.query.artist || ''))
const album = computed(() => String(route.query.album || ''))
const tracks = ref([])
const loading = ref(false)
const trackPage = ref(0)
const trackPageSize = 50
const trackTotal = ref(0)
const trackPagedMode = ref(false)
const trackFiles = ref([])
const trackLoading = ref(false)
const trackPageCount = computed(() => Math.max(1, Math.ceil((trackTotal.value || 0) / trackPageSize)))
const trackPageNumbers = computed(() => {
  const total = trackPageCount.value
  const current = trackPage.value + 1
  const nums = new Set([1, total])
  for (let i = current - 2; i <= current + 2; i += 1) {
    if (i >= 1 && i <= total) nums.add(i)
  }
  const sorted = Array.from(nums).sort((a, b) => a - b)
  const out = []
  sorted.forEach((n, idx) => {
    if (idx && n - sorted[idx - 1] > 1) out.push('...')
    out.push(n)
  })
  return out
})
const displayTracks = computed(() => trackPagedMode.value ? trackFiles.value : tracks.value)
const scraping = ref(false)
const selectedTrack = ref(null)
const showTrackModal = ref(false)
const trackEdit = ref({})
const savingTrack = ref(false)
const completingAlbum = ref(false)
const completeResult = ref(null)

const scrapedCount = computed(() => tracks.value.filter(t => t.scraped).length)
const totalDuration = computed(() => tracks.value.reduce((sum, t) => sum + (Number(t.duration) || 0), 0))
const formats = computed(() => [...new Set(tracks.value.map(t => (t.format || '').toUpperCase()).filter(Boolean))])

async function loadTracks() {
  if (!artist.value || !album.value) return
  loading.value = true
  trackLoading.value = true
  try {
    const probe = await getLibraryFiles({ album_artist: artist.value, album_name: album.value, limit: 1, offset: 0, sort: 'track' })
    trackTotal.value = probe.total || 0
    if (trackTotal.value <= 200) {
      trackPagedMode.value = false
      tracks.value = await getAlbumTracks(artist.value, album.value)
      trackTotal.value = tracks.value.length
    } else {
      trackPagedMode.value = true
      trackPage.value = 0
      trackFiles.value = []
      await loadTrackPage(0)
    }
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
    trackLoading.value = false
  }
}

async function loadTrackPage(page = 0) {
  const target = Math.min(Math.max(0, page), trackPageCount.value - 1)
  trackLoading.value = true
  try {
    const data = await getLibraryFiles({
      album_artist: artist.value,
      album_name: album.value,
      limit: trackPageSize,
      offset: target * trackPageSize,
      sort: 'track'
    })
    trackTotal.value = data.total || 0
    trackFiles.value = data.items || []
    trackPage.value = target
  } catch (e) {
    console.error(e)
  } finally {
    trackLoading.value = false
  }
}

async function changeTrackPage(page) {
  const target = Math.min(Math.max(0, page), trackPageCount.value - 1)
  if (target === trackPage.value || trackLoading.value) return
  await loadTrackPage(target)
}

function coverUrl() {
  return getAlbumCover(artist.value, album.value)
}

async function getAlbumQueueTracks() {
  // 播放队列必须是整张专辑：分页/局部列表场景下补一次全量专辑曲目，避免只把当前歌曲塞进队列。
  if (!tracks.value.length || trackPagedMode.value) {
    tracks.value = await getAlbumTracks(artist.value, album.value)
    if (!trackTotal.value) trackTotal.value = tracks.value.length
  }
  return tracks.value.length ? tracks.value : displayTracks.value
}

async function playAll(startIndex = 0) {
  const queueTracks = await getAlbumQueueTracks()
  player.playQueue(queueTracks, startIndex)
}

async function playTrack(track) {
  const queueTracks = await getAlbumQueueTracks()
  const idx = queueTracks.findIndex(t => String(t.id) === String(track.id))
  player.playQueue(queueTracks, idx >= 0 ? idx : 0)
}

async function completeMissingAlbum() {
  if (!artist.value || !album.value) return
  if (!confirm(`自动搜索并补齐「${artist.value} - ${album.value}」缺失曲目？会优先选择无损资源。`)) return
  completingAlbum.value = true
  completeResult.value = null
  try {
    const preview = await completeAlbum({ artist: artist.value, album: album.value, dry_run: true, limit: 40 })
    const count = preview.candidates?.length || 0
    if (!count) {
      completeResult.value = { message: preview.reason || '没有发现可补齐的新曲目' }
      return
    }
    if (!confirm(`找到 ${count} 首疑似缺失曲目，是否开始下载并自动入库？`)) {
      completeResult.value = { message: `已预览 ${count} 首，未下载`, candidates: preview.candidates }
      return
    }
    completeResult.value = await completeAlbum({ artist: artist.value, album: album.value, dry_run: false, limit: 40 })
    await loadTracks()
  } catch (e) {
    completeResult.value = { message: e.message || '补齐失败' }
  } finally {
    completingAlbum.value = false
  }
}

async function rescrapeAlbum() {
  scraping.value = true
  try {
    await rescrapeLibrary({ album_artist: artist.value, album_name: album.value })
    if (trackPagedMode.value) await loadTrackPage(trackPage.value)
    else await loadTracks()
  } finally {
    scraping.value = false
  }
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
    await loadTracks()
  } finally {
    savingTrack.value = false
  }
}

async function deleteTrack(track) {
  if (!track || !confirm(`确认删除「${track.title || track.file_path}」？\n会把本地音频文件移入音乐库 .trash 回收站，并清理空目录；库记录会同步移除。`)) return
  await applyLibraryTool('delete_files', {
    file_ids: [track.id],
    options: { delete_files: true, delete_empty_dirs: true, delete_missing_db_rows: true, mode: 'trash' },
    async: false
  })
  showTrackModal.value = false
  await loadTracks()
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

watch(() => route.fullPath, loadTracks)
onMounted(loadTracks)
</script>

<template>
  <div class="album-view">
    <button class="back-btn" @click="router.push('/library')">← 返回音乐库</button>

    <div class="hero-card">
      <img :src="coverUrl()" class="hero-cover" />
      <div class="hero-info">
        <div class="eyebrow">专辑</div>
        <h2>{{ album }}</h2>
        <div class="artist-line">{{ artist }}</div>
        <div class="meta-line">
          <span v-if="!trackPagedMode">{{ tracks.length }} 首</span>
          <span v-else>第 {{ trackPage + 1 }} / {{ trackPageCount }} 页 · 共 {{ trackTotal }} 首</span>
          <span>{{ formatDuration(totalDuration) }}</span>
          <span v-if="formats.length">{{ formats.join('/') }}</span>
          <span>{{ scrapedCount }}/{{ tracks.length }} 已刮削</span>
        </div>
        <div class="hero-actions">
          <AppButton variant="primary" size="sm" :disabled="!trackTotal && !displayTracks.length" @click="playAll(0)">播放整张</AppButton>
          <AppButton variant="ghost" size="sm" :loading="completingAlbum" @click="completeMissingAlbum">补齐缺失</AppButton>
          <AppButton variant="ghost" size="sm" :loading="scraping" @click="rescrapeAlbum">重新刮削</AppButton>
        </div>
      </div>
    </div>

    <div v-if="completeResult" class="complete-result">
      {{ completeResult.message || `已下载 ${completeResult.downloaded?.length || 0} 首，失败 ${completeResult.errors?.length || 0} 首` }}
    </div>

    <div v-if="loading" class="loading-text">加载曲目中...</div>
    <div v-else class="track-table">
      <div class="table-head">
        <span>#</span><span>歌曲</span><span>格式</span><span>时长</span><span>状态</span><span></span>
      </div>
      <div
        v-for="(track, index) in displayTracks"
        :key="track.id"
        :class="['track-row', { active: player.currentId === track.id, 'is-unscraped': !track.scraped }]"
        @click="openTrack(track.id)"
      >
        <div class="track-index">{{ track.track_number || index + 1 }}</div>
        <div class="track-main">
          <div class="track-title">{{ track.title || track.file_path?.split('/').pop() || '未命名曲目' }}</div>
          <div class="track-sub">{{ [track.artist, track.album].filter(Boolean).join(' · ') || '待完善元数据' }}</div>
        </div>
        <div class="track-format">{{ track.format || '-' }}</div>
        <div class="track-duration">{{ formatDuration(track.duration) }}</div>
        <AppBadge :color="track.scraped ? 'green' : 'orange'">{{ track.scraped ? '已刮削' : '未刮削' }}</AppBadge>
        <button class="play-btn" @click.stop="playTrack(track)">{{ player.currentId === track.id ? '播放中' : '播放' }}</button>
      </div>
    </div>

    <AppModal v-if="showTrackModal && selectedTrack" title="曲目详情" @close="showTrackModal = false">
      <div class="track-modal">
        <div class="detail-grid">
          <div class="detail-row"><span>路径</span><em>{{ selectedTrack.file_path }}</em></div>
          <div class="detail-row"><span>艺人</span><em>{{ selectedTrack.artist }}</em></div>
          <div class="detail-row"><span>专辑</span><em>{{ selectedTrack.album }}</em></div>
          <div class="detail-row"><span>标题</span><em>{{ selectedTrack.title }}</em></div>
          <div class="detail-row"><span>格式</span><em>{{ selectedTrack.format || '-' }}</em></div>
          <div class="detail-row"><span>时长</span><em>{{ formatDuration(selectedTrack.duration) }}</em></div>
        </div>
        <div class="tag-edit">
          <h4>编辑标签</h4>
          <label>标题<input v-model="trackEdit.title" /></label>
          <label>艺人<input v-model="trackEdit.artist" /></label>
          <label>专辑<input v-model="trackEdit.album" /></label>
          <label>年份<input v-model="trackEdit.year" type="number" /></label>
          <label>流派<input v-model="trackEdit.genre" /></label>
          <div class="tag-actions">
            <AppButton variant="primary" size="sm" :loading="savingTrack" @click="saveTrack">保存</AppButton>
            <AppButton variant="danger" size="sm" @click="deleteTrack(selectedTrack)">移入回收站</AppButton>
          </div>
        </div>
        <div class="pager" v-if="trackPagedMode && trackPageCount > 1">
          <button :disabled="trackPage === 0 || trackLoading" @click="changeTrackPage(0)">&lt;&lt;</button>
          <button :disabled="trackPage === 0 || trackLoading" @click="changeTrackPage(trackPage - 1)">&lt;</button>
          <template v-for="p in trackPageNumbers" :key="p + '-track-page'">
            <span v-if="p === '...'" class="pager-ellipsis">...</span>
            <button v-else :class="{ active: p === trackPage + 1 }" :disabled="trackLoading" @click="changeTrackPage(p - 1)">{{ p }}</button>
          </template>
          <button :disabled="trackPage >= trackPageCount - 1 || trackLoading" @click="changeTrackPage(trackPage + 1)">&gt;</button>
          <button :disabled="trackPage >= trackPageCount - 1 || trackLoading" @click="changeTrackPage(trackPageCount - 1)">&gt;&gt;</button>
        </div>
      </div>
    </AppModal>
  </div>
</template>

<style scoped>
.album-view { padding: 24px; display: flex; flex-direction: column; gap: 18px; overflow-y: auto; height: 100%; padding-bottom: 120px; }
.back-btn { align-self: flex-start; border: 1px solid var(--border); background: var(--surface); color: var(--text-dim); border-radius: var(--radius-md); padding: 8px 12px; cursor: pointer; }
.back-btn:hover { color: var(--text); background: var(--surface-hover); }
.hero-card { display: flex; gap: 24px; align-items: flex-end; background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 18%, var(--surface)), var(--surface)); border: 1px solid var(--border); border-radius: 24px; padding: 24px; }
.hero-cover { width: 220px; height: 220px; object-fit: cover; border-radius: 20px; box-shadow: 0 20px 48px rgba(0,0,0,.35); background: var(--bg-elevated); }
.hero-info { min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.eyebrow { font-size: 12px; color: var(--text-dim); font-weight: 700; letter-spacing: .08em; }
h2 { font-size: clamp(28px, 5vw, 56px); line-height: 1; margin: 0; word-break: break-word; }
.artist-line { font-size: 18px; color: var(--text); font-weight: 700; }
.meta-line { display: flex; flex-wrap: wrap; gap: 8px; color: var(--text-dim); font-size: 13px; }
.meta-line span:not(:last-child)::after { content: '·'; margin-left: 8px; color: var(--text-muted); }
.hero-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 4px; }
.loading-text { color: var(--text-dim); }
.complete-result { padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface-soft); color: var(--text-dim); font-size: 13px; }
.pager { display: flex; gap: 6px; align-items: center; justify-content: center; flex-wrap: wrap; }
.pager button { min-width: 30px; height: 28px; padding: 0 8px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-elevated); color: var(--text-dim); cursor: pointer; }
.pager button:hover:not(:disabled), .pager button.active { border-color: var(--accent); color: var(--text); background: var(--surface-hover); }
.pager button:disabled { opacity: .45; cursor: not-allowed; }
.pager-ellipsis { color: var(--text-muted); padding: 0 2px; }
.track-table { display: flex; flex-direction: column; gap: 4px; }
.table-head, .track-row { display: grid; grid-template-columns: 44px minmax(0, 1fr) 80px 80px 88px 72px; align-items: center; gap: 10px; }
.table-head { padding: 0 12px 8px; color: var(--text-muted); font-size: 12px; border-bottom: 1px solid var(--border); }
.track-row { padding: 10px 12px; border-radius: var(--radius-md); cursor: pointer; }
.track-row:hover, .track-row.active { background: var(--surface-hover); }
.track-row.is-unscraped { opacity: 0.95; }
.track-row.is-unscraped .track-title { color: var(--text); }
.track-index, .track-format, .track-duration { color: var(--text-dim); font-size: 13px; }
.track-main { min-width: 0; cursor: pointer; }
.track-title { font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.track-sub { color: var(--text-dim); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.play-btn { border: 1px solid var(--border); background: transparent; color: var(--text-dim); border-radius: var(--radius-sm); padding: 5px 8px; cursor: pointer; font-size: 12px; }
.play-btn:hover { color: var(--text); background: var(--surface); }
.track-modal { min-width: 460px; display: flex; flex-direction: column; gap: 18px; }
.detail-grid { display: flex; flex-direction: column; gap: 8px; }
.detail-row { display: flex; gap: 12px; }
.detail-row span { min-width: 48px; color: var(--text-dim); font-size: 12px; }
.detail-row em { font-style: normal; word-break: break-all; }
.tag-edit { border-top: 1px solid var(--border); padding-top: 14px; display: flex; flex-direction: column; gap: 10px; }
.tag-edit h4 { margin: 0; }
.tag-edit label { display: flex; gap: 10px; align-items: center; color: var(--text-dim); font-size: 13px; }
.tag-edit input { flex: 1; }
.tag-actions { display: flex; gap: 8px; flex-wrap: wrap; }

@media (max-width: 768px) {
  .album-view { padding: 16px; padding-bottom: 150px; }
  .hero-card { align-items: flex-start; flex-direction: column; padding: 18px; border-radius: 18px; }
  .hero-cover { width: 150px; height: 150px; align-self: center; border-radius: 18px; }
  h2 { font-size: clamp(24px, 9vw, 34px); line-height: 1.08; }
  .artist-line { font-size: 15px; }
  .hero-actions { width: 100%; }
  .hero-actions button { flex: 1; }
  .table-head { display: none; }
  .track-row { grid-template-columns: 30px minmax(0, 1fr) 58px; padding: 9px 8px; gap: 8px; }
  .track-format, .track-duration, .track-row :deep(.badge) { display: none; }
  .track-modal { min-width: unset; width: 100%; }
  .detail-row { flex-direction: column; gap: 2px; }
  .tag-edit label { flex-direction: column; align-items: stretch; }
  .tag-actions { flex-direction: column; }
}
</style>
