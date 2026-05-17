<script setup>
import { computed, ref, watch } from 'vue'
import { getAlbumCover, getFile } from '@/api/index.js'
import { usePlayerStore } from '@/stores/player.js'

const player = usePlayerStore()

const title = computed(() => player.currentTrack?.title || '正在播放')
const subtitle = computed(() => [player.currentTrack?.artist, player.currentTrack?.album].filter(Boolean).join(' · '))
const queueLabel = computed(() => player.queueSize > 1 ? `${player.queueIndex + 1}/${player.queueSize}` : '队列')
const isNowOpen = ref(false)
const detailLoading = ref(false)
const trackDetail = ref(null)
const detailTrack = computed(() => trackDetail.value || player.currentTrack || {})
const coverUrl = computed(() => {
  const t = detailTrack.value
  return t.artist && t.album ? getAlbumCover(t.artist, t.album) : ''
})
const audioMeta = computed(() => {
  const t = trackDetail.value || {}
  return [
    t.format ? String(t.format).toUpperCase() : '',
    t.bitrate ? `${t.bitrate} kbps` : '',
    t.sample_rate ? `${Math.round(t.sample_rate / 1000)} kHz` : '',
    t.channels ? `${t.channels}ch` : '',
  ].filter(Boolean).join(' · ')
})

async function loadTrackDetail() {
  if (!player.currentId) return
  detailLoading.value = true
  try {
    trackDetail.value = await getFile(player.currentId)
  } catch (err) {
    console.warn('load track detail failed', err)
    trackDetail.value = null
  } finally {
    detailLoading.value = false
  }
}

function toggleQueuePanel() {
  isNowOpen.value = false
  player.toggleQueue()
}

async function toggleNowPanel() {
  isNowOpen.value = !isNowOpen.value
  if (isNowOpen.value) {
    player.closeQueue()
    await loadTrackDetail()
  }
}

watch(() => player.currentId, () => {
  trackDetail.value = null
  if (isNowOpen.value) loadTrackDetail()
})

function formatDuration(seconds) {
  if (!seconds) return '--:--'
  const total = Math.floor(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m}:${s.toString().padStart(2, '0')}`
}
</script>

<template>
  <div v-if="player.currentTrack" :class="['global-player', { collapsed: player.isCollapsed }]">
    <button class="collapse-toggle" :title="player.isCollapsed ? '展开播放器' : '缩小播放器'" @click="player.toggleCollapsed">
      {{ player.isCollapsed ? '▴' : '▾' }}
    </button>

    <div class="player-info" @click="player.expand">
      <div class="player-title">{{ title }}</div>
      <div class="player-sub">{{ subtitle || '未知来源' }}</div>
    </div>

    <div v-show="!player.isCollapsed" class="transport">
      <button class="transport-btn" title="上一首" :disabled="!player.hasPrev" @click="player.playPrev">⏮</button>
      <button class="transport-btn" title="下一首" :disabled="!player.hasNext" @click="player.playNext">⏭</button>
    </div>

    <audio
      v-show="!player.isCollapsed"
      :key="player.currentId"
      class="player-audio"
      controls
      autoplay
      :src="player.streamUrl()"
      @ended="player.playNext"
    />

    <div v-if="player.isCollapsed" class="mini-duration">{{ formatDuration(player.currentTrack?.duration) }}</div>

    <button
      v-show="!player.isCollapsed"
      :class="['panel-toggle', { active: isNowOpen }]"
      title="正在播放详情"
      @click="toggleNowPanel"
    >
      ♪ 详情
    </button>

    <button
      v-show="!player.isCollapsed"
      :class="['panel-toggle', { active: player.isQueueOpen }]"
      title="播放队列"
      @click="toggleQueuePanel"
    >
      ☰ {{ queueLabel }}
    </button>

    <button class="player-close" title="关闭播放器" @click="player.close">×</button>

    <div v-if="isNowOpen && !player.isCollapsed" class="now-panel">
      <div class="now-cover-wrap">
        <img v-if="coverUrl" :src="coverUrl" class="now-cover" />
        <div v-else class="now-cover placeholder">♪</div>
      </div>
      <div class="now-content">
        <div class="now-head">
          <div>
            <strong>{{ detailTrack.title || title }}</strong>
            <span>{{ [detailTrack.artist, detailTrack.album].filter(Boolean).join(' · ') || subtitle || '未知来源' }}</span>
          </div>
          <button class="queue-close" @click="isNowOpen = false">×</button>
        </div>
        <div class="now-meta">
          <span>{{ formatDuration(detailTrack.duration) }}</span>
          <span v-if="audioMeta">{{ audioMeta }}</span>
          <span v-if="trackDetail?.year">{{ trackDetail.year }}</span>
          <span v-if="trackDetail?.genre">{{ trackDetail.genre }}</span>
        </div>
        <div v-if="detailLoading" class="lyrics-box muted">加载曲目信息中...</div>
        <pre v-else-if="trackDetail?.lyrics" class="lyrics-box">{{ trackDetail.lyrics }}</pre>
        <div v-else class="lyrics-box muted">暂无歌词。可以在专辑详情里重新刮削补齐歌词。</div>
      </div>
    </div>

    <div v-if="player.isQueueOpen && !player.isCollapsed" class="queue-panel">
      <div class="queue-head">
        <div>
          <strong>播放队列</strong>
          <span>{{ player.queueSize }} 首</span>
        </div>
        <button class="queue-close" @click="player.closeQueue">×</button>
      </div>
      <div class="queue-list">
        <button
          v-for="(track, index) in player.queue"
          :key="`${track.id}-${index}`"
          :class="['queue-item', { active: index === player.queueIndex }]"
          @click="player.playAt(index)"
        >
          <span class="queue-index">{{ index + 1 }}</span>
          <span class="queue-main">
            <strong>{{ track.title }}</strong>
            <em>{{ [track.artist, track.album].filter(Boolean).join(' · ') }}</em>
          </span>
          <span class="queue-duration">{{ formatDuration(track.duration) }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.global-player {
  position: fixed;
  left: 264px;
  right: 24px;
  bottom: 20px;
  z-index: 160;
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 66px;
  padding: 12px 14px;
  background: color-mix(in srgb, var(--bg-elevated) 94%, transparent);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: 0 18px 46px rgba(0, 0, 0, 0.36);
  backdrop-filter: blur(16px);
}
.global-player.collapsed {
  left: auto;
  right: 24px;
  bottom: 20px;
  width: min(360px, calc(100vw - 48px));
  min-height: 48px;
  padding: 8px 10px;
}
.collapse-toggle,
.player-close,
.transport-btn,
.queue-close {
  flex-shrink: 0;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-dim);
  border-radius: 999px;
  width: 32px;
  height: 32px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  line-height: 1;
}
.collapse-toggle:hover,
.player-close:hover,
.transport-btn:hover:not(:disabled),
.queue-close:hover { color: var(--text); background: var(--surface-hover); }
.transport-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.player-close:hover { color: var(--danger); }
.transport { display: flex; gap: 6px; align-items: center; }
.player-info {
  min-width: 180px;
  max-width: 360px;
  overflow: hidden;
  cursor: pointer;
}
.player-title {
  font-size: 14px;
  font-weight: 800;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.player-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.player-audio {
  flex: 1;
  min-width: 260px;
}
.mini-duration {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-muted);
}
.panel-toggle {
  flex-shrink: 0;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-dim);
  border-radius: 999px;
  height: 32px;
  padding: 0 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
}
.panel-toggle:hover, .panel-toggle.active { color: var(--text); background: var(--surface-hover); }
.queue-panel,
.now-panel {
  position: absolute;
  right: 12px;
  bottom: calc(100% + 10px);
  width: min(420px, calc(100vw - 48px));
  max-height: min(460px, calc(100vh - 160px));
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg-elevated) 98%, transparent);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: 0 18px 48px rgba(0,0,0,.42);
  overflow: hidden;
}
.queue-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 14px 10px; border-bottom: 1px solid var(--border); }

.now-panel {
  width: min(680px, calc(100vw - 48px));
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 16px;
  padding: 16px;
}
.now-cover { width: 190px; height: 190px; object-fit: cover; border-radius: 18px; background: var(--surface); box-shadow: 0 16px 36px rgba(0,0,0,.35); }
.now-cover.placeholder { display: flex; align-items: center; justify-content: center; color: var(--text-muted); font-size: 56px; border: 1px solid var(--border); }
.now-content { min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.now-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.now-head div { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.now-head strong { font-size: 18px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.now-head span { font-size: 13px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.now-meta { display: flex; flex-wrap: wrap; gap: 8px; color: var(--text-muted); font-size: 12px; }
.now-meta span:not(:last-child)::after { content: '·'; margin-left: 8px; color: var(--text-muted); }
.lyrics-box { min-height: 128px; max-height: 220px; overflow-y: auto; margin: 0; padding: 12px; border-radius: 14px; background: var(--surface); color: var(--text-dim); font-size: 12px; line-height: 1.75; white-space: pre-wrap; word-break: break-word; }
.lyrics-box.muted { display: flex; align-items: center; justify-content: center; text-align: center; color: var(--text-muted); }
.queue-head div { display: flex; flex-direction: column; gap: 2px; }
.queue-head strong { font-size: 14px; }
.queue-head span { font-size: 12px; color: var(--text-dim); }
.queue-list { overflow-y: auto; padding: 6px; }
.queue-item { width: 100%; display: grid; grid-template-columns: 28px minmax(0,1fr) auto; gap: 10px; align-items: center; border: 0; background: transparent; color: var(--text-dim); border-radius: 12px; padding: 9px 10px; cursor: pointer; text-align: left; }
.queue-item:hover, .queue-item.active { background: var(--surface-hover); color: var(--text); }
.queue-index, .queue-duration { font-size: 12px; color: var(--text-muted); }
.queue-main { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.queue-main strong, .queue-main em { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.queue-main strong { font-size: 13px; color: var(--text); }
.queue-main em { font-style: normal; font-size: 12px; color: var(--text-dim); }

@media (max-width: 768px) {
  .global-player {
    left: 12px;
    right: 12px;
    bottom: 68px;
    min-height: 62px;
    gap: 8px;
    padding: 10px;
    border-radius: 16px;
  }
  .global-player.collapsed {
    left: 12px;
    right: 12px;
    bottom: 68px;
    width: auto;
  }
  .player-info { min-width: 0; max-width: none; flex: 1; }
  .player-audio { min-width: 120px; }
  .panel-toggle { padding: 0 9px; }
  .queue-panel { left: 0; right: 0; width: auto; max-height: min(420px, calc(100vh - 180px)); }
  .now-panel { left: 0; right: 0; width: auto; grid-template-columns: 92px minmax(0, 1fr); max-height: min(520px, calc(100vh - 180px)); overflow-y: auto; }
  .now-cover { width: 92px; height: 92px; border-radius: 14px; }
  .now-head strong { font-size: 15px; }
  .lyrics-box { grid-column: 1 / -1; max-height: 180px; }
}
</style>
