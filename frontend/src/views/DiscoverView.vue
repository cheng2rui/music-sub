<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getRecommend, getPlaylists, getToplist, getPlaylist, addSub, getLibraryStats, getTasks } from '@/api/index.js'
import MusicCover from '@/components/MusicCover.vue'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppModal from '@/components/AppModal.vue'

const router = useRouter()

const recommend = ref([])
const playlists = ref([])
const toplist = ref([])
const libraryStats = ref({ total_files: 0, scraped: 0, unscraped: 0, artists: 0, albums: 0 })
const tasks = ref([])
const loading = ref(false)

const selectedPlaylist = ref(null)
const playlistSongs = ref([])
const showPlaylistModal = ref(false)

const featuredSong = computed(() => recommend.value[0] || toplist.value[0] || null)
const recommendedSongs = computed(() => recommend.value.slice(0, 8))
const featuredPlaylists = computed(() => playlists.value.slice(0, 6))
const chartSongs = computed(() => toplist.value.slice(0, 10))
const recentTasks = computed(() => tasks.value.slice(0, 4))
const activeTaskCount = computed(() => tasks.value.filter(t => ['downloading', 'organized', 'downloaded'].includes(t.status)).length)
const libraryTotal = computed(() => libraryStats.value.total_files || libraryStats.value.tracks || 0)
const scrapedRate = computed(() => {
  const total = libraryTotal.value
  if (!total) return '0%'
  return Math.round(((libraryStats.value.scraped || 0) / total) * 100) + '%'
})

const quickLinks = [
  { icon: '🔎', title: '搜索资源', desc: '按歌名 / 艺人找 PT 或在线音乐', path: '/search' },
  { icon: '➕', title: '订阅管理', desc: '持续追踪艺人、专辑、歌曲', path: '/subs' },
  { icon: '🎶', title: '音乐库', desc: '浏览专辑与整理刮削结果', path: '/library' },
  { icon: '⬇️', title: '任务列表', desc: '查看下载、整理、入库进度', path: '/tasks' }
]

async function loadAll() {
  loading.value = true
  try {
    const [rec, pls, top, stats, taskList] = await Promise.allSettled([
      getRecommend(),
      getPlaylists(),
      getToplist(),
      getLibraryStats(),
      getTasks()
    ])
    recommend.value = rec.status === 'fulfilled' ? (rec.value.items || []) : []
    playlists.value = pls.status === 'fulfilled' ? (pls.value.items || []) : []
    toplist.value = top.status === 'fulfilled' ? (top.value.items || []) : []
    libraryStats.value = stats.status === 'fulfilled' ? (stats.value || {}) : libraryStats.value
    tasks.value = taskList.status === 'fulfilled' ? (Array.isArray(taskList.value) ? taskList.value : []) : []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function openPlaylist(id) {
  const data = await getPlaylist(id)
  selectedPlaylist.value = { id, title: data.title, cover: data.cover, desc: data.desc }
  playlistSongs.value = data.songs || []
  showPlaylistModal.value = true
}

function formatPlayCount(n) {
  if (!n) return '0'
  if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return String(n)
}

function formatDate(value) {
  if (!value) return '-'
  return new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function statusLabel(status) {
  const map = {
    downloading: { label: '下载中', color: 'blue' },
    downloaded: { label: '待整理', color: 'orange' },
    organized: { label: '整理中', color: 'orange' },
    scraped: { label: '已入库', color: 'green' },
    failed: { label: '失败', color: 'red' },
    paused: { label: '暂停', color: 'dim' },
    missing: { label: '缺失', color: 'red' }
  }
  return map[status] || { label: status || '未知', color: 'dim' }
}

function go(path) {
  router.push(path)
}

async function quickSubscribe(keyword, type) {
  if (!keyword) return
  const labels = { artist: '艺人', song: '歌曲', album: '专辑' }
  if (!confirm(`订阅${labels[type] || ''}: ${keyword}?`)) return
  try {
    await addSub({ keyword, type: type || 'artist', quality: 'any', sites: 'all' })
    alert(`✅ 已添加订阅: ${keyword}`)
  } catch (e) { alert('订阅失败: ' + e.message) }
}

onMounted(loadAll)
</script>

<template>
  <div class="discover">
    <section class="hero-card">
      <div class="hero-copy">
        <AppBadge color="green">Discover</AppBadge>
        <h1>今天想听点什么？</h1>
        <p>从新歌、热榜、推荐歌单到本地曲库状态，一屏掌握 Music Sub 的日常入口。</p>
        <div class="hero-actions">
          <AppButton size="sm" @click="go('/search')">搜索音乐</AppButton>
          <AppButton variant="ghost" size="sm" :loading="loading" @click="loadAll">刷新发现</AppButton>
        </div>
      </div>
      <div v-if="featuredSong" class="hero-feature">
        <MusicCover :src="featuredSong.cover" class="hero-cover" show-play />
        <div class="hero-track">
          <span>今日主打</span>
          <strong>{{ featuredSong.title }}</strong>
          <small>{{ featuredSong.artist || featuredSong.album || '未知艺人' }}</small>
        </div>
        <div class="hero-feature-actions">
          <AppButton variant="ghost" size="sm" @click="quickSubscribe(featuredSong.title + ' ' + featuredSong.artist, 'song')">订歌</AppButton>
          <AppButton variant="ghost" size="sm" @click="quickSubscribe(featuredSong.artist, 'artist')">订艺人</AppButton>
        </div>
      </div>
    </section>

    <section class="overview-grid">
      <article class="stat-card">
        <span class="stat-label">本地曲目</span>
        <strong>{{ libraryTotal }}</strong>
        <small>{{ libraryStats.artists || 0 }} 位艺人 · {{ libraryStats.albums || 0 }} 张专辑</small>
      </article>
      <article class="stat-card">
        <span class="stat-label">刮削完成</span>
        <strong>{{ scrapedRate }}</strong>
        <small>{{ libraryStats.scraped || 0 }} 已完成 · {{ libraryStats.unscraped || 0 }} 待处理</small>
      </article>
      <article class="stat-card">
        <span class="stat-label">下载任务</span>
        <strong>{{ activeTaskCount }}</strong>
        <small>活跃任务 / 近期 {{ tasks.length }} 条</small>
      </article>
    </section>

    <section class="quick-grid">
      <article v-for="link in quickLinks" :key="link.path" class="quick-card" @click="go(link.path)">
        <div class="quick-icon">{{ link.icon }}</div>
        <div>
          <h3>{{ link.title }}</h3>
          <p>{{ link.desc }}</p>
        </div>
      </article>
    </section>

    <div class="dashboard-grid">
      <section class="panel panel-wide">
        <div class="section-header">
          <div>
            <h2>今日推荐</h2>
            <p>新歌随机推荐，适合一键订阅追踪。</p>
          </div>
          <AppButton variant="ghost" size="sm" @click="loadAll">换一批</AppButton>
        </div>
        <div v-if="loading" class="loading-text">加载中...</div>
        <div v-else class="song-card-grid">
          <article v-for="item in recommendedSongs" :key="item.title + item.artist" class="song-card">
            <MusicCover :src="item.cover" class="song-cover" show-play />
            <div class="song-card-info">
              <div class="song-card-title">{{ item.title }}</div>
              <div class="song-card-sub">{{ item.artist }}</div>
              <div v-if="item.album" class="song-card-album">{{ item.album }}</div>
            </div>
            <div class="song-card-actions">
              <AppButton variant="ghost" size="sm" @click="quickSubscribe(item.title + ' ' + item.artist, 'song')">订歌</AppButton>
              <AppButton variant="ghost" size="sm" @click="quickSubscribe(item.artist, 'artist')">艺人</AppButton>
            </div>
          </article>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h2>热歌排行榜</h2>
            <p>飙升榜 / 热歌榜更新。</p>
          </div>
        </div>
        <div v-if="loading" class="loading-text">加载中...</div>
        <div v-else class="chart-list">
          <div v-for="(item, idx) in chartSongs" :key="idx" class="chart-row">
            <span class="rank" :class="{ 'rank-top': idx < 3 }">{{ idx + 1 }}</span>
            <MusicCover :src="item.cover" class="rank-cover" />
            <div class="rank-info">
              <div class="rank-title">{{ item.title }}</div>
              <div class="rank-sub">{{ item.artist }}</div>
            </div>
            <button class="mini-action" title="订阅歌曲" @click="quickSubscribe(item.title + ' ' + item.artist, 'song')">+</button>
          </div>
        </div>
      </section>

      <section class="panel panel-wide">
        <div class="section-header">
          <div>
            <h2>推荐歌单</h2>
            <p>打开歌单后可逐首订阅。</p>
          </div>
        </div>
        <div v-if="loading" class="loading-text">加载中...</div>
        <div v-else class="playlist-grid">
          <article v-for="item in featuredPlaylists" :key="item.id" class="playlist-card" @click="openPlaylist(item.id)">
            <MusicCover :src="item.cover" class="playlist-cover" show-play />
            <div class="playlist-info">
              <div class="cover-title">{{ item.title }}</div>
              <div class="cover-sub">{{ formatPlayCount(item.play_count) }} 播放</div>
            </div>
          </article>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h2>最近任务</h2>
            <p>下载与入库进度速览。</p>
          </div>
          <AppButton variant="ghost" size="sm" @click="go('/tasks')">查看</AppButton>
        </div>
        <div v-if="recentTasks.length === 0" class="empty-state">暂无近期任务</div>
        <div v-else class="task-list">
          <article v-for="task in recentTasks" :key="task.id" class="mini-task">
            <div class="mini-task-head">
              <strong :title="task.torrent_name">{{ task.torrent_name }}</strong>
              <AppBadge :color="statusLabel(task.status).color">{{ statusLabel(task.status).label }}</AppBadge>
            </div>
            <small>{{ task.site || (task.external_qb ? 'qB' : '-') }} · {{ formatDate(task.created_at) }}</small>
          </article>
        </div>
      </section>
    </div>

    <AppModal v-if="showPlaylistModal" :title="selectedPlaylist?.title" @close="showPlaylistModal = false">
      <div class="playlist-detail">
        <img v-if="selectedPlaylist?.cover" :src="selectedPlaylist.cover" class="detail-cover" />
        <p v-if="selectedPlaylist?.desc" class="detail-desc">{{ selectedPlaylist.desc }}</p>
        <div class="song-list">
          <div v-for="song in playlistSongs" :key="song.title + song.artist" class="song-row">
            <div class="song-info">
              <span class="song-title">{{ song.title }}</span>
              <span class="song-sub">{{ song.artist }}</span>
            </div>
            <AppButton variant="ghost" size="sm" @click="quickSubscribe(song.title + ' ' + song.artist, 'song')">订</AppButton>
          </div>
        </div>
      </div>
    </AppModal>
  </div>
</template>

<style scoped>
.discover { padding: 24px; padding-bottom: 32px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; height: 100%; }
.hero-card { position: relative; overflow: hidden; display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.85fr); gap: 18px; align-items: stretch; padding: 24px; border: 1px solid var(--border); border-radius: var(--radius-xl); background: radial-gradient(circle at 16% 0%, var(--accent-soft), transparent 34%), linear-gradient(135deg, var(--bg-elevated), var(--surface)); box-shadow: var(--shadow-card); }
.hero-card::after { content: ''; position: absolute; right: -80px; top: -120px; width: 260px; height: 260px; border-radius: 50%; background: var(--accent-soft); filter: blur(4px); pointer-events: none; }
.hero-copy { position: relative; z-index: 1; display: flex; flex-direction: column; align-items: flex-start; justify-content: center; gap: 12px; min-width: 0; }
.hero-copy h1 { margin: 0; font-size: clamp(28px, 4vw, 44px); line-height: 1.1; letter-spacing: -0.04em; }
.hero-copy p { margin: 0; max-width: 560px; color: var(--text-dim); line-height: 1.6; }
.hero-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 4px; }
.hero-feature { position: relative; z-index: 1; display: grid; grid-template-columns: 104px minmax(0, 1fr); gap: 14px; align-items: center; padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface-soft); min-width: 0; }
.hero-cover { width: 104px; height: 104px; border-radius: var(--radius-lg); box-shadow: var(--shadow-soft); }
.hero-track { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.hero-track span { color: var(--accent); font-size: 12px; font-weight: 700; }
.hero-track strong { font-size: 18px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hero-track small { color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hero-feature-actions { grid-column: 1 / -1; display: flex; gap: 8px; justify-content: flex-end; }
.overview-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.stat-card, .quick-card, .panel { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-elevated); box-shadow: var(--shadow-card); }
.stat-card { display: flex; flex-direction: column; gap: 5px; padding: 16px; min-width: 0; }
.stat-label { color: var(--text-dim); font-size: 12px; font-weight: 700; }
.stat-card strong { font-size: 28px; line-height: 1; }
.stat-card small { color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.quick-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.quick-card { display: flex; gap: 12px; align-items: center; padding: 14px; cursor: pointer; transition: transform 0.15s, background 0.15s, border-color 0.15s; min-width: 0; }
.quick-card:hover { transform: translateY(-2px); background: var(--surface); border-color: var(--border-strong); }
.quick-icon { display: grid; place-items: center; width: 40px; height: 40px; flex: 0 0 auto; border-radius: var(--radius-md); background: var(--accent-soft); font-size: 20px; }
.quick-card h3 { margin: 0 0 4px; font-size: 14px; }
.quick-card p { margin: 0; color: var(--text-dim); font-size: 12px; line-height: 1.35; }
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(320px, 0.9fr); gap: 16px; align-items: start; }
.panel { padding: 16px; min-width: 0; }
.panel-wide { min-width: 0; }
.section-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.section-header h2 { margin: 0 0 4px; font-size: 20px; font-weight: 800; }
.section-header p { margin: 0; color: var(--text-dim); font-size: 13px; }
.section-header.compact h2 { font-size: 18px; }
.loading-text, .empty-state { color: var(--text-dim); padding: 22px 0; text-align: center; }
.song-card-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.song-card { display: grid; grid-template-columns: 60px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 10px; border-radius: var(--radius-md); background: var(--surface-soft); min-width: 0; }
.song-card:hover { background: var(--surface-hover); }
.song-cover { width: 60px; height: 60px; border-radius: var(--radius-md); }
.song-card-info { min-width: 0; }
.song-card-title, .cover-title, .rank-title { font-size: 14px; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-card-sub, .cover-sub, .rank-sub { font-size: 12px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-card-album { margin-top: 2px; font-size: 11px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-card-actions { display: flex; gap: 6px; flex-shrink: 0; }
.chart-list, .task-list { display: flex; flex-direction: column; gap: 4px; }
.chart-row { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 8px; border-radius: var(--radius-md); transition: background 0.15s; }
.chart-row:hover { background: var(--surface-hover); }
.rank { font-size: 13px; font-weight: 800; color: var(--text-dim); min-width: 24px; text-align: center; }
.rank-top { color: var(--accent); }
.rank-cover { width: 42px; height: 42px; border-radius: var(--radius-sm); flex-shrink: 0; }
.rank-info { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
.mini-action { display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid var(--border); border-radius: 999px; background: transparent; color: var(--text-dim); cursor: pointer; flex: 0 0 auto; }
.mini-action:hover { color: var(--text); background: var(--surface); }
.playlist-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.playlist-card { display: flex; gap: 10px; align-items: center; min-width: 0; padding: 10px; border-radius: var(--radius-md); background: var(--surface-soft); cursor: pointer; }
.playlist-card:hover { background: var(--surface-hover); }
.playlist-cover { width: 72px; height: 72px; border-radius: var(--radius-md); flex-shrink: 0; }
.playlist-info { min-width: 0; }
.mini-task { padding: 10px; border-radius: var(--radius-md); background: var(--surface-soft); }
.mini-task-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; min-width: 0; }
.mini-task strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.mini-task small { display: block; margin-top: 6px; color: var(--text-muted); }
.playlist-detail { display: flex; flex-direction: column; gap: 16px; min-width: 400px; }
.detail-cover { width: 200px; height: 200px; border-radius: var(--radius-lg); object-fit: cover; }
.detail-desc { font-size: 13px; color: var(--text-dim); line-height: 1.6; }
.song-list { display: flex; flex-direction: column; gap: 4px; max-height: 400px; overflow-y: auto; }
.song-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 8px; border-radius: var(--radius-sm); }
.song-row:hover { background: var(--surface-hover); }
.song-info { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
.song-title { font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-sub { font-size: 12px; color: var(--text-dim); }

@media (max-width: 1180px) {
  .dashboard-grid { grid-template-columns: 1fr; }
  .quick-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 768px) {
  .discover { padding: 14px; padding-bottom: calc(92px + env(safe-area-inset-bottom)); gap: 14px; overflow-x: hidden; }
  .hero-card { grid-template-columns: 1fr; padding: 18px; border-radius: var(--radius-lg); }
  .hero-copy h1 { font-size: 28px; }
  .hero-feature { grid-template-columns: 78px minmax(0, 1fr); padding: 10px; }
  .hero-cover { width: 78px; height: 78px; }
  .hero-track strong { font-size: 16px; }
  .overview-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .stat-card { padding: 12px 10px; }
  .stat-card strong { font-size: 22px; }
  .stat-card small { font-size: 11px; }
  .quick-grid { grid-template-columns: 1fr; gap: 10px; }
  .quick-card { padding: 12px; }
  .panel { padding: 12px; border-radius: var(--radius-lg); }
  .section-header { align-items: flex-start; margin-bottom: 10px; }
  .section-header h2 { font-size: 18px; }
  .section-header p { font-size: 12px; }
  .song-card-grid { grid-template-columns: 1fr; }
  .song-card { grid-template-columns: 54px minmax(0, 1fr); }
  .song-cover { width: 54px; height: 54px; }
  .song-card-actions { grid-column: 1 / -1; justify-content: flex-end; }
  .playlist-grid { grid-template-columns: 1fr; }
  .playlist-cover { width: 58px; height: 58px; }
  .chart-row { padding: 7px 2px; gap: 8px; }
  .rank-cover { width: 38px; height: 38px; }
  .playlist-detail { min-width: 0; }
  .detail-cover { width: 132px; height: 132px; }
}

@media (max-width: 420px) {
  .overview-grid { grid-template-columns: 1fr; }
  .hero-actions, .hero-feature-actions { width: 100%; }
}
</style>
