<script setup>
import { ref, onMounted } from 'vue'
import { getRecommend, getPlaylists, getToplist, getPlaylist, addSub } from '@/api/index.js'
import MusicCover from '@/components/MusicCover.vue'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppModal from '@/components/AppModal.vue'

const recommend = ref([])
const playlists = ref([])
const toplist = ref([])
const loading = ref(false)

const selectedPlaylist = ref(null)
const playlistSongs = ref([])
const showPlaylistModal = ref(false)

async function loadAll() {
  loading.value = true
  try {
    const [rec, pls, top] = await Promise.all([getRecommend(), getPlaylists(), getToplist()])
    recommend.value = rec.items || []
    playlists.value = pls.items || []
    toplist.value = top.items || []
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
    <!-- 今日推荐 -->
    <section class="section">
      <div class="section-header">
        <h2>今日推荐</h2>
        <AppButton variant="ghost" size="sm" @click="loadAll">换一批</AppButton>
      </div>
      <div v-if="loading" class="loading-text">加载中...</div>
      <div v-else class="cover-grid">
        <div
          v-for="item in recommend"
          :key="item.title + item.artist"
          class="cover-item"
        >
          <MusicCover :src="item.cover" show-play />
          <div class="cover-info">
            <div class="cover-title">{{ item.title }}</div>
            <div class="cover-sub">{{ item.artist }}</div>
            <div class="cover-actions">
              <AppButton variant="ghost" size="sm" @click="quickSubscribe(item.title + ' ' + item.artist, 'song')">订歌</AppButton>
              <AppButton variant="ghost" size="sm" @click="quickSubscribe(item.artist, 'artist')">订艺人</AppButton>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 推荐歌单 -->
    <section class="section">
      <div class="section-header">
        <h2>推荐歌单</h2>
      </div>
      <div v-if="loading" class="loading-text">加载中...</div>
      <div v-else class="cover-grid">
        <div
          v-for="item in playlists"
          :key="item.id"
          class="cover-item clickable"
          @click="openPlaylist(item.id)"
        >
          <MusicCover :src="item.cover" show-play />
          <div class="cover-info">
            <div class="cover-title">{{ item.title }}</div>
            <div class="cover-sub">{{ formatPlayCount(item.play_count) }} 播放</div>
          </div>
        </div>
      </div>
    </section>

    <!-- 热歌排行榜 -->
    <section class="section">
      <div class="section-header">
        <h2>热歌排行榜</h2>
      </div>
      <div v-if="loading" class="loading-text">加载中...</div>
      <div v-else class="toplist-table">
        <div
          v-for="(item, idx) in toplist"
          :key="idx"
          class="toplist-row"
        >
          <span class="rank" :class="{ 'rank-top': idx < 3 }">{{ idx + 1 }}</span>
          <MusicCover :src="item.cover" class="rank-cover" />
          <div class="rank-info">
            <div class="rank-title">{{ item.title }}</div>
            <div class="rank-sub">{{ item.artist }}</div>
          </div>
          <div class="rank-actions">
            <AppButton variant="ghost" size="sm" @click="quickSubscribe(item.title + ' ' + item.artist, 'song')">订歌</AppButton>
            <AppButton variant="ghost" size="sm" @click="quickSubscribe(item.artist, 'artist')">订艺人</AppButton>
          </div>
        </div>
      </div>
    </section>

    <!-- 歌单弹窗 -->
    <AppModal v-if="showPlaylistModal" :title="selectedPlaylist?.title" @close="showPlaylistModal = false">
      <div class="playlist-detail">
        <img v-if="selectedPlaylist?.cover" :src="selectedPlaylist.cover" class="detail-cover" />
        <p v-if="selectedPlaylist?.desc" class="detail-desc">{{ selectedPlaylist.desc }}</p>
        <div class="song-list">
          <div v-for="song in playlistSongs" :key="song.title" class="song-row">
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
.discover { padding: 24px; display: flex; flex-direction: column; gap: 36px; overflow-y: auto; height: 100%; }
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.section-header h2 { font-size: 20px; font-weight: 700; }
.loading-text { color: var(--text-dim); padding: 20px 0; }
.cover-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; }
.cover-item { display: flex; flex-direction: column; gap: 8px; cursor: default; }
.cover-item.clickable { cursor: pointer; }
.cover-info { display: flex; flex-direction: column; gap: 2px; }
.cover-title { font-size: 14px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cover-sub { font-size: 12px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cover-actions { display: flex; gap: 4px; margin-top: 4px; }
.toplist-table { display: flex; flex-direction: column; gap: 2px; }
.toplist-row { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-radius: var(--radius-md); transition: background 0.15s; }
.toplist-row:hover { background: var(--surface-hover); }
.rank { font-size: 14px; font-weight: 700; color: var(--text-dim); min-width: 28px; text-align: center; }
.rank-top { color: var(--accent); }
.rank-cover { width: 44px; height: 44px; border-radius: var(--radius-sm); flex-shrink: 0; }
.rank-info { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
.rank-actions { display: flex; gap: 4px; flex-shrink: 0; }
.rank-title { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rank-sub { font-size: 12px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.playlist-detail { display: flex; flex-direction: column; gap: 16px; min-width: 400px; }
.detail-cover { width: 200px; height: 200px; border-radius: var(--radius-lg); object-fit: cover; }
.detail-desc { font-size: 13px; color: var(--text-dim); line-height: 1.6; }
.song-list { display: flex; flex-direction: column; gap: 4px; max-height: 400px; overflow-y: auto; }
.song-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 8px; border-radius: var(--radius-sm); }
.song-row:hover { background: var(--surface-hover); }
.song-info { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
.song-title { font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.song-sub { font-size: 12px; color: var(--text-dim); }
</style>