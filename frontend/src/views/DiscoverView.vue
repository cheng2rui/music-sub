<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getPersonalized, getLibraryStats, getTasks } from '@/api/index.js'
import { usePlayerStore } from '@/stores/player.js'
import MusicCover from '@/components/MusicCover.vue'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppModal from '@/components/AppModal.vue'

const router = useRouter()
const player = usePlayerStore()

const recommend = ref([])
const libraryStats = ref({ total_files: 0, scraped: 0, unscraped: 0, artists: 0, albums: 0 })
const tasks = ref([])
const loading = ref(false)
const showHomeSettings = ref(false)

const HOME_MODULE_STORAGE_KEY = 'music_sub_discover_local_modules'
const defaultHomeModules = [
  { key: 'hero', label: '顶部主打', desc: '本地今日主打和快捷入口', enabled: true },
  { key: 'stats', label: '数据概览', desc: '本地曲目、刮削完成率、下载任务', enabled: true },
  { key: 'quick', label: '快捷入口', desc: '搜索、订阅、曲库、任务入口', enabled: true },
  { key: 'recommend', label: '今日推荐', desc: '只基于本地音乐库生成', enabled: true },
  { key: 'tasks', label: '最近任务', desc: '下载与入库进度速览', enabled: true }
]
const homeModules = ref(loadHomeModules())

const featuredSong = computed(() => recommend.value[0] || null)
const recommendedSongs = computed(() => recommend.value.slice(0, 12))
const recentTasks = computed(() => tasks.value.slice(0, 4))
const activeTaskCount = computed(() => tasks.value.filter(t => ['downloading', 'organized', 'downloaded'].includes(t.status)).length)
const visibleMasonryModules = computed(() => homeModules.value.filter(m => m.enabled && ['recommend', 'tasks'].includes(m.key)))
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
    const [rec, stats, taskList] = await Promise.allSettled([
      getPersonalized(),
      getLibraryStats(),
      getTasks()
    ])
    recommend.value = rec.status === 'fulfilled' ? (rec.value.items || []) : []
    libraryStats.value = stats.status === 'fulfilled' ? (stats.value || {}) : libraryStats.value
    tasks.value = taskList.status === 'fulfilled' ? (Array.isArray(taskList.value) ? taskList.value : []) : []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
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

function formatDate(value) {
  if (!value) return '-'
  return new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatDuration(seconds) {
  const n = Number(seconds || 0)
  if (!n) return '-'
  return `${Math.floor(n / 60)}:${String(Math.floor(n % 60)).padStart(2, '0')}`
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

function normalizePlayable(item) {
  return {
    id: item.file_id || item.id || item.song_id,
    title: item.title,
    artist: item.artist,
    album: item.album,
    duration: item.duration || 0,
  }
}

function playLocalSong(item) {
  if (!item?.file_id && !item?.id) return
  const queue = recommendedSongs.value
    .filter(song => song?.file_id || song?.id)
    .map(normalizePlayable)
  const idx = queue.findIndex(song => String(song.id) === String(item.file_id || item.id || item.song_id))
  if (queue.length) player.playQueue(queue, idx >= 0 ? idx : 0)
  else player.playTrack(normalizePlayable(item))
}

onMounted(loadAll)
</script>

<template>
  <div class="discover">
    <section v-if="isHomeModuleEnabled('hero')" class="hero-card">
      <div class="hero-copy">
        <AppBadge color="green">Local Discover</AppBadge>
        <h1>今天从本地库听点什么？</h1>
        <p>今日推荐只基于你的本地音乐库生成，不再请求外部热榜、歌单或推荐 API。</p>
        <div class="hero-actions">
          <AppButton size="sm" @click="go('/library')">打开音乐库</AppButton>
          <AppButton variant="ghost" size="sm" :loading="loading" @click="loadAll">换一批</AppButton>
          <AppButton variant="ghost" size="sm" @click="showHomeSettings = true">编辑首页</AppButton>
        </div>
      </div>
      <div v-if="featuredSong" class="hero-feature" @click="playLocalSong(featuredSong)">
        <MusicCover :src="featuredSong.cover" class="hero-cover" show-play />
        <div class="hero-track">
          <span>本地今日主打</span>
          <strong>{{ featuredSong.title }}</strong>
          <small>{{ featuredSong.artist || featuredSong.album || '未知艺人' }}</small>
          <small v-if="featuredSong.reason" class="song-reason">{{ featuredSong.reason }}</small>
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

    <div v-if="visibleMasonryModules.length" class="dashboard-grid" :class="{ single: visibleMasonryModules.length === 1 }">
      <section v-if="isHomeModuleEnabled('recommend')" class="panel panel-wide">
        <div class="section-header">
          <div>
            <h2>今日推荐</h2>
            <p>纯本地推荐：最近入库、高频艺人和随机发现。</p>
          </div>
          <AppButton variant="ghost" size="sm" :loading="loading" @click="loadAll">换一批</AppButton>
        </div>
        <div v-if="loading" class="loading-text">加载中...</div>
        <div v-else-if="recommendedSongs.length === 0" class="empty-state">本地音乐库为空，暂无推荐</div>
        <div v-else class="song-card-grid">
          <article v-for="item in recommendedSongs" :key="item.file_id || item.title + item.artist" class="song-card" @click="playLocalSong(item)">
            <MusicCover :src="item.cover" class="song-cover" show-play />
            <div class="song-card-info">
              <div class="song-card-title">{{ item.title }}</div>
              <div class="song-card-sub">{{ item.artist }}</div>
              <div v-if="item.album" class="song-card-album">{{ item.album }}</div>
              <div v-if="item.reason" class="song-reason">{{ item.reason }}</div>
            </div>
            <div class="song-card-meta">
              <span>{{ item.format || 'LOCAL' }}</span>
              <small>{{ formatDuration(item.duration) }}</small>
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
        <p class="home-settings-hint">选择首页要显示的本地内容。外部热榜和推荐歌单已移除。</p>
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
  </div>
</template>

<style scoped>
.discover { padding: 24px; padding-bottom: 32px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; height: 100%; }
.discover > * { flex: 0 0 auto; }
.hero-card { position: relative; overflow: hidden; display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.85fr); gap: 18px; align-items: stretch; padding: 24px; border: 1px solid var(--border); border-radius: var(--radius-xl); background: radial-gradient(circle at 16% 0%, var(--accent-soft), transparent 34%), linear-gradient(135deg, var(--bg-elevated), var(--surface)); box-shadow: var(--shadow-card); }
.hero-copy { position: relative; z-index: 1; display: flex; flex-direction: column; align-items: flex-start; justify-content: center; gap: 12px; min-width: 0; }
.hero-copy h1 { margin: 0; font-size: clamp(28px, 4vw, 44px); line-height: 1.1; letter-spacing: -0.04em; }
.hero-copy p { margin: 0; max-width: 560px; color: var(--text-dim); line-height: 1.6; }
.hero-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 4px; }
.hero-feature { position: relative; z-index: 1; display: grid; grid-template-columns: 104px minmax(0, 1fr); gap: 14px; align-items: center; padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface-soft); min-width: 0; cursor: pointer; }
.hero-feature:hover { background: var(--surface-hover); }
.hero-cover { width: 104px; height: 104px; border-radius: var(--radius-lg); box-shadow: var(--shadow-soft); }
.hero-track { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.hero-track span { color: var(--accent); font-size: 12px; font-weight: 700; }
.hero-track strong { font-size: 18px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hero-track small { color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 380px); gap: 16px; align-items: start; }
.dashboard-grid.single { grid-template-columns: 1fr; }
.panel { width: 100%; padding: 16px; min-width: 0; }
.panel-wide { min-width: 0; }
.section-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.section-header h2 { margin: 0 0 4px; font-size: 20px; font-weight: 800; }
.section-header p { margin: 0; color: var(--text-dim); font-size: 13px; }
.section-header.compact h2 { font-size: 18px; }
.loading-text, .empty-state { color: var(--text-dim); padding: 22px 0; text-align: center; }
.song-card-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.song-card { display: grid; grid-template-columns: 60px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 10px; border-radius: var(--radius-md); background: var(--surface-soft); min-width: 0; cursor: pointer; }
.song-card:hover { background: var(--surface-hover); }
.song-cover { width: 60px; height: 60px; border-radius: var(--radius-md); }
.song-card-info { min-width: 0; }
.song-card-title { font-size: 14px; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-card-sub { font-size: 12px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-card-album { margin-top: 2px; font-size: 11px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-reason { margin-top: 2px; font-size: 11px; color: var(--accent); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-card-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 3px; color: var(--text-dim); font-size: 11px; }
.song-card-meta span { color: var(--accent); font-weight: 700; }
.task-list { display: flex; flex-direction: column; gap: 4px; }
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
@media (max-width: 1180px) {
  .hero-card { grid-template-columns: 1fr; }
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
  .song-card { grid-template-columns: 54px minmax(0, 1fr) auto; }
  .song-cover { width: 54px; height: 54px; }
  .home-settings { min-width: 0; }
  .home-module-grid { grid-template-columns: 1fr; }
  .home-settings-actions { flex-direction: column-reverse; }
  .home-settings-actions :deep(.btn) { width: 100%; justify-content: center; }
}
@media (max-width: 420px) {
  .overview-grid { grid-template-columns: 1fr; }
  .hero-actions { width: 100%; }
}
</style>
