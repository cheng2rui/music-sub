<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getRecommend, getPersonalized, getPlaylists, getToplist, getPlaylist, addSub, getLibraryStats, getTasks, searchOnlineMusic, downloadOnlineSong } from '@/api/index.js'
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
const actionLoading = ref('')
const showHomeSettings = ref(false)

const HOME_MODULE_STORAGE_KEY = 'music_sub_discover_modules'
const defaultHomeModules = [
  { key: 'hero', label: '顶部主打', desc: '今日主打歌曲和快速搜索入口', enabled: true },
  { key: 'stats', label: '数据概览', desc: '本地曲目、刮削完成率、下载任务', enabled: true },
  { key: 'quick', label: '快捷入口', desc: '搜索、订阅、曲库、任务入口', enabled: true },
  { key: 'recommend', label: '今日推荐', desc: '新歌随机推荐和订阅入口', enabled: true },
  { key: 'charts', label: '热歌排行榜', desc: '热榜歌曲速览', enabled: true },
  { key: 'playlists', label: '推荐歌单', desc: '在线歌单和逐首订阅', enabled: true },
  { key: 'tasks', label: '最近任务', desc: '下载与入库进度速览', enabled: true }
]
const homeModules = ref(loadHomeModules())

const selectedPlaylist = ref(null)
const playlistSongs = ref([])
const showPlaylistModal = ref(false)

const featuredSong = computed(() => recommend.value[0] || toplist.value[0] || null)
const recommendedSongs = computed(() => recommend.value.slice(0, 8))
const featuredPlaylists = computed(() => playlists.value.slice(0, 6))
const chartSongs = computed(() => toplist.value.slice(0, 10))
const recentTasks = computed(() => tasks.value.slice(0, 4))
const activeTaskCount = computed(() => tasks.value.filter(t => ['downloading', 'organized', 'downloaded'].includes(t.status)).length)
const visibleMasonryModules = computed(() => homeModules.value.filter(m => m.enabled && ['recommend', 'charts', 'playlists', 'tasks'].includes(m.key)))
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
      getPersonalized().catch(() => getRecommend()),
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


function loadHomeModules() {
  try {
    const stored = JSON.parse(localStorage.getItem(HOME_MODULE_STORAGE_KEY) || '[]')
    if (Array.isArray(stored)) {
      const storedMap = new Map(stored.map(item => [item.key, item.enabled]))
      return defaultHomeModules.map(item => ({ ...item, enabled: storedMap.has(item.key) ? !!storedMap.get(item.key) : item.enabled }))
    }
  } catch (e) {
    console.warn('Failed to load discover module settings', e)
  }
  return defaultHomeModules.map(item => ({ ...item }))
}

function saveHomeModules() {
  localStorage.setItem(HOME_MODULE_STORAGE_KEY, JSON.stringify(homeModules.value.map(({ key, enabled }) => ({ key, enabled }))))
  showHomeSettings.value = false
}

function resetHomeModules() {
  homeModules.value = defaultHomeModules.map(item => ({ ...item }))
}

function isHomeModuleEnabled(key) {
  return homeModules.value.find(item => item.key === key)?.enabled !== false
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

function songKeyword(item) {
  return [item?.title, item?.artist].filter(Boolean).join(' ').trim()
}

function onlineSource(item) {
  const source = item?.source || ''
  if (source === 'qqmusic') return 'qq'
  if (source === 'netease') return 'netease'
  if (source === 'kuwo') return 'kuwo'
  if (source === 'kugou') return 'kugou'
  if (source === 'migu') return 'migu'
  return source || 'qq'
}

function songPayload(item) {
  const source = onlineSource(item)
  return {
    source,
    song_id: item?.song_id || '',
    title: item?.title || '',
    artist: item?.artist || '',
    album: item?.album || '',
    cover_url: item?.cover || '',
    filename: `${item?.title || 'unknown'} - ${item?.artist || 'unknown'}.${source === 'qq' ? 'flac' : 'mp3'}`,
    format: source === 'qq' ? 'flac' : 'mp3',
    duration: item?.duration || 0,
    url: item?.url || ''
  }
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

async function quickDownload(item) {
  if (!item?.title) return
  const key = `download-${item.source || ''}-${item.song_id || item.title}`
  actionLoading.value = key
  try {
    let song = songPayload(item)
    if (song.source !== 'qq' || !song.song_id) {
      const found = await searchOnlineMusic(songKeyword(item), [song.source], 5)
      const candidate = (found || []).find(x => !x.disabled && (x.url || x.source === 'qq')) || (found || [])[0]
      if (!candidate) throw new Error('没有找到可下载直链')
      song = candidate
    }
    const res = await downloadOnlineSong(song, true)
    alert(res.ok ? '✅ 已下载并整理入库' : '下载失败')
  } catch (e) {
    alert('下载失败: ' + (e.message || e))
  } finally {
    actionLoading.value = ''
  }
}

function quickSearchPt(item) {
  const keyword = songKeyword(item)
  if (!keyword) return
  localStorage.setItem('music_sub_pending_search_keyword', keyword)
  go('/search')
}

async function subscribePlaylistSongs() {
  if (!playlistSongs.value.length) return
  if (!confirm(`批量订阅歌单「${selectedPlaylist.value?.title || ''}」前 ${playlistSongs.value.length} 首歌曲？`)) return
  actionLoading.value = 'playlist-subscribe'
  let ok = 0
  try {
    for (const song of playlistSongs.value.slice(0, 50)) {
      const keyword = songKeyword(song)
      if (!keyword) continue
      try {
        await addSub({ keyword, type: 'song', quality: 'any', sites: 'all' })
        ok += 1
      } catch (e) {
        console.warn('subscribe song failed', keyword, e)
      }
    }
    alert(`✅ 已添加 ${ok} 个歌曲订阅`)
  } finally {
    actionLoading.value = ''
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="discover">
    <section v-if="isHomeModuleEnabled('hero')" class="hero-card">
      <div class="hero-copy">
        <AppBadge color="green">Discover</AppBadge>
        <h1>今天想听点什么？</h1>
        <p>从新歌、热榜、推荐歌单到本地曲库状态，一屏掌握 Music Sub 的日常入口。</p>
        <div class="hero-actions">
          <AppButton size="sm" @click="go('/search')">搜索音乐</AppButton>
          <AppButton variant="ghost" size="sm" :loading="loading" @click="loadAll">刷新发现</AppButton>
          <AppButton variant="ghost" size="sm" @click="showHomeSettings = true">编辑首页</AppButton>
        </div>
      </div>
      <div v-if="featuredSong" class="hero-feature">
        <MusicCover :src="featuredSong.cover" class="hero-cover" show-play />
        <div class="hero-track">
          <span>今日主打</span>
          <strong>{{ featuredSong.title }}</strong>
          <small>{{ featuredSong.artist || featuredSong.album || '未知艺人' }}</small>
          <small v-if="featuredSong.reason" class="song-reason">{{ featuredSong.reason }}</small>
        </div>
        <div class="hero-feature-actions">
          <AppButton variant="primary" size="sm" :loading="actionLoading === `download-${featuredSong.source || ''}-${featuredSong.song_id || featuredSong.title}`" @click="quickDownload(featuredSong)">下载</AppButton>
          <AppButton variant="ghost" size="sm" @click="quickSearchPt(featuredSong)">搜 PT</AppButton>
          <AppButton variant="ghost" size="sm" @click="quickSubscribe(featuredSong.title + ' ' + featuredSong.artist, 'song')">订歌</AppButton>
          <AppButton variant="ghost" size="sm" @click="quickSubscribe(featuredSong.artist, 'artist')">订艺人</AppButton>
        </div>
      </div>
    </section>

    <section v-if="isHomeModuleEnabled('stats')" class="overview-grid">
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

    <section v-if="isHomeModuleEnabled('quick')" class="quick-grid">
      <article v-for="link in quickLinks" :key="link.path" class="quick-card" @click="go(link.path)">
        <div class="quick-icon">{{ link.icon }}</div>
        <div>
          <h3>{{ link.title }}</h3>
          <p>{{ link.desc }}</p>
        </div>
      </article>
    </section>

    <div v-if="visibleMasonryModules.length" class="dashboard-grid">
      <section v-if="isHomeModuleEnabled('recommend')" class="panel panel-wide">
        <div class="section-header">
          <div>
            <h2>今日推荐</h2>
            <p>结合本地曲库、订阅和最近下载生成，已入库会自动标记。</p>
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
              <div v-if="item.reason" class="song-reason">{{ item.in_library ? '已在库 · ' : '' }}{{ item.reason }}</div>
            </div>
            <div class="song-card-actions">
              <AppButton variant="primary" size="sm" :loading="actionLoading === `download-${item.source || ''}-${item.song_id || item.title}`" @click="quickDownload(item)">下</AppButton>
              <AppButton variant="ghost" size="sm" @click="quickSearchPt(item)">PT</AppButton>
              <AppButton variant="ghost" size="sm" @click="quickSubscribe(item.title + ' ' + item.artist, 'song')">订歌</AppButton>
              <AppButton variant="ghost" size="sm" @click="quickSubscribe(item.artist, 'artist')">艺人</AppButton>
            </div>
          </article>
        </div>
      </section>

      <section v-if="isHomeModuleEnabled('charts')" class="panel">
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
              <div v-if="item.reason" class="rank-reason">{{ item.reason }}</div>
            </div>
            <button class="mini-action" title="下载" :disabled="!!actionLoading" @click="quickDownload(item)">↓</button>
            <button class="mini-action" title="搜 PT" @click="quickSearchPt(item)">PT</button>
            <button class="mini-action" title="订阅歌曲" @click="quickSubscribe(item.title + ' ' + item.artist, 'song')">+</button>
          </div>
        </div>
      </section>

      <section v-if="isHomeModuleEnabled('playlists')" class="panel panel-wide">
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

      <section v-if="isHomeModuleEnabled('tasks')" class="panel">
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


    <AppModal v-if="showHomeSettings" title="编辑首页" @close="showHomeSettings = false">
      <div class="home-settings">
        <p class="home-settings-hint">选择首页要显示的内容。关闭的模块不会占位，下方卡片会自动向上吸附。</p>
        <div class="home-module-grid">
          <label v-for="module in homeModules" :key="module.key" class="home-module-item" :class="{ enabled: module.enabled }">
            <input type="checkbox" v-model="module.enabled" />
            <span>
              <strong>{{ module.label }}</strong>
              <small>{{ module.desc }}</small>
            </span>
          </label>
        </div>
        <div class="home-settings-actions">
          <AppButton variant="ghost" size="sm" @click="resetHomeModules">恢复默认</AppButton>
          <AppButton size="sm" @click="saveHomeModules">保存</AppButton>
        </div>
      </div>
    </AppModal>

    <AppModal v-if="showPlaylistModal" :title="selectedPlaylist?.title" @close="showPlaylistModal = false">
      <div class="playlist-detail">
        <img v-if="selectedPlaylist?.cover" :src="selectedPlaylist.cover" class="detail-cover" />
        <p v-if="selectedPlaylist?.desc" class="detail-desc">{{ selectedPlaylist.desc }}</p>
        <div class="playlist-actions">
          <AppButton size="sm" variant="primary" :loading="actionLoading === 'playlist-subscribe'" @click="subscribePlaylistSongs">批量订阅前50首</AppButton>
        </div>
        <div class="song-list">
          <div v-for="song in playlistSongs" :key="song.title + song.artist" class="song-row">
            <div class="song-info">
              <span class="song-title">{{ song.title }}</span>
              <span class="song-sub">{{ song.artist }}</span>
            </div>
            <div class="song-row-actions">
              <AppButton variant="primary" size="sm" :loading="actionLoading === `download-${song.source || ''}-${song.song_id || song.title}`" @click="quickDownload(song)">下</AppButton>
              <AppButton variant="ghost" size="sm" @click="quickSearchPt(song)">PT</AppButton>
              <AppButton variant="ghost" size="sm" @click="quickSubscribe(song.title + ' ' + song.artist, 'song')">订</AppButton>
            </div>
          </div>
        </div>
      </div>
    </AppModal>
  </div>
</template>

<style scoped>
.discover { padding: 24px; padding-bottom: 32px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; height: 100%; }
.discover > * { flex: 0 0 auto; }
.hero-card { position: relative; overflow: hidden; display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.85fr); gap: 18px; align-items: stretch; padding: 24px; border: 1px solid var(--border); border-radius: var(--radius-xl); background: radial-gradient(circle at 16% 0%, var(--accent-soft), transparent 34%), linear-gradient(135deg, var(--bg-elevated), var(--surface)); box-shadow: var(--shadow-card); }
.hero-card::after { content: ''; position: absolute; right: 12px; top: 12px; width: 150px; height: 150px; border-radius: 50%; background: var(--accent-soft); filter: blur(4px); pointer-events: none; opacity: 0.8; }
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
.dashboard-grid { column-count: 2; column-gap: 16px; }
.panel { display: inline-block; width: 100%; margin: 0 0 16px; padding: 16px; min-width: 0; break-inside: avoid; page-break-inside: avoid; }
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
.song-reason, .rank-reason { margin-top: 2px; font-size: 11px; color: var(--accent); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-card-actions { display: flex; gap: 6px; flex-shrink: 0; flex-wrap: wrap; justify-content: flex-end; }
.chart-list, .task-list { display: flex; flex-direction: column; gap: 4px; }
.chart-row { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 8px; border-radius: var(--radius-md); transition: background 0.15s; }
.chart-row:hover { background: var(--surface-hover); }
.rank { font-size: 13px; font-weight: 800; color: var(--text-dim); min-width: 24px; text-align: center; }
.rank-top { color: var(--accent); }
.rank-cover { width: 42px; height: 42px; border-radius: var(--radius-sm); flex-shrink: 0; }
.rank-info { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
.mini-action { display: grid; place-items: center; min-width: 28px; height: 28px; padding: 0 7px; border: 1px solid var(--border); border-radius: 999px; background: transparent; color: var(--text-dim); cursor: pointer; flex: 0 0 auto; font-size: 11px; }
.mini-action:hover { color: var(--text); background: var(--surface); }
.mini-action:disabled { opacity: .5; cursor: wait; }
.playlist-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.playlist-card { display: flex; gap: 10px; align-items: center; min-width: 0; padding: 10px; border-radius: var(--radius-md); background: var(--surface-soft); cursor: pointer; }
.playlist-card:hover { background: var(--surface-hover); }
.playlist-cover { width: 72px; height: 72px; border-radius: var(--radius-md); flex-shrink: 0; }
.playlist-info { min-width: 0; }
.mini-task { padding: 10px; border-radius: var(--radius-md); background: var(--surface-soft); }
.mini-task-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; min-width: 0; }
.mini-task strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.mini-task small { display: block; margin-top: 6px; color: var(--text-muted); }
.home-settings { display: flex; flex-direction: column; gap: 14px; min-width: min(520px, 80vw); }
.home-settings-hint { margin: 0; color: var(--text-dim); font-size: 13px; line-height: 1.5; }
.home-module-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.home-module-item { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px; align-items: flex-start; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface-soft); cursor: pointer; transition: border-color .15s, background .15s; }
.home-module-item.enabled { border-color: var(--accent); background: var(--accent-soft); }
.home-module-item input { margin-top: 2px; accent-color: var(--accent); }
.home-module-item span { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.home-module-item strong { font-size: 14px; }
.home-module-item small { color: var(--text-dim); line-height: 1.35; }
.home-settings-actions { display: flex; justify-content: flex-end; gap: 10px; }
.playlist-detail { display: flex; flex-direction: column; gap: 16px; min-width: 400px; }
.detail-cover { width: 200px; height: 200px; border-radius: var(--radius-lg); object-fit: cover; }
.detail-desc { font-size: 13px; color: var(--text-dim); line-height: 1.6; }
.playlist-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.song-list { display: flex; flex-direction: column; gap: 4px; max-height: 400px; overflow-y: auto; }
.song-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 8px; border-radius: var(--radius-sm); }
.song-row:hover { background: var(--surface-hover); }
.song-info { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
.song-title { font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-sub { font-size: 12px; color: var(--text-dim); }
.song-row-actions { display: flex; gap: 6px; flex-shrink: 0; }

@media (max-width: 1180px) {
  .hero-card { grid-template-columns: 1fr; }
  .dashboard-grid { column-count: 1; }
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
  .home-settings { min-width: 0; }
  .home-module-grid { grid-template-columns: 1fr; }
  .home-settings-actions { flex-direction: column-reverse; }
  .home-settings-actions :deep(.btn) { width: 100%; justify-content: center; }
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
