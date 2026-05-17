<script setup>
import { computed } from 'vue'
import { usePlayerStore } from '@/stores/player.js'

const player = usePlayerStore()

const title = computed(() => player.currentTrack?.title || '正在播放')
const subtitle = computed(() => [player.currentTrack?.artist, player.currentTrack?.album].filter(Boolean).join(' · '))

function formatDuration(seconds) {
  if (!seconds) return '--:--'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
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
    <div v-else-if="player.queueSize > 1" class="queue-hint">{{ player.queueIndex + 1 }}/{{ player.queueSize }}</div>

    <button class="player-close" title="关闭播放器" @click="player.close">×</button>
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
.transport-btn {
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
.transport-btn:hover:not(:disabled) { color: var(--text); background: var(--surface-hover); }
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
.mini-duration,
.queue-hint {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-muted);
}

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
}
</style>
