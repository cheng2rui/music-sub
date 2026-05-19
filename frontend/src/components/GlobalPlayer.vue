<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { getAlbumCover, getFile } from '@/api/index.js'
import { usePlayerStore } from '@/stores/player.js'

const player = usePlayerStore()

const title = computed(() => player.currentTrack?.title || '正在播放')
const subtitle = computed(() => [player.currentTrack?.artist, player.currentTrack?.album].filter(Boolean).join(' · '))
const queueLabel = computed(() => player.queueSize > 1 ? `${player.queueIndex + 1}/${player.queueSize}` : '队列')
const playbackModes = [
  { key: 'order', label: '顺序', title: '顺序播放', icon: '↦' },
  { key: 'shuffle', label: '随机', title: '随机播放', icon: '⤨' },
  { key: 'repeat', label: '循环', title: '循环播放', icon: '↻' },
]
const playbackModeMeta = computed(() => playbackModes.find(mode => mode.key === player.playbackMode) || playbackModes[0])
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

async function openNowPanel() {
  player.expand()
  player.closeQueue()
  isNowOpen.value = true
  await loadTrackDetail()
}

async function toggleNowPanel() {
  if (isNowOpen.value) {
    isNowOpen.value = false
    return
  }
  player.expand()
  player.closeQueue()
  isNowOpen.value = true
  await loadTrackDetail()
}

async function handleTitleClick() {
  await toggleNowPanel()
}

watch(() => player.currentId, () => {
  trackDetail.value = null
  duration.value = 0
  seekValue.value = 0
  isSeeking.value = false
  isPlaying.value = false
  player.setCurrentTime(0)
  if (isNowOpen.value || player.isCollapsed) loadTrackDetail()
})

watch(() => player.isCollapsed, (collapsed) => {
  if (collapsed && player.currentId) loadTrackDetail()
})

const audioRef = ref(null)
const lyricsListRef = ref(null)
const isPlaying = ref(false)
const duration = ref(0)
const isSeeking = ref(false)
const seekValue = ref(0)
const effectiveDuration = computed(() => duration.value || Number(player.currentTrack?.duration) || 0)
const seekPercent = computed(() => {
  const d = effectiveDuration.value
  if (!d) return 0
  return Math.max(0, Math.min(100, ((isSeeking.value ? seekValue.value : player.currentTime) / d) * 100))
})
const parsedLyrics = computed(() => parseLrc(trackDetail.value?.lyrics))
const activeLyricIndex = computed(() => {
  const lines = parsedLyrics.value
  if (!lines.length) return -1
  const t = player.currentTime
  let idx = -1
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].time <= t + 0.05) idx = i
    else break
  }
  return idx
})

const collapsedLyricWindow = computed(() => {
  const lines = parsedLyrics.value
  const idx = activeLyricIndex.value
  if (!lines.length || idx < 0) {
    return [
      { key: 'title', text: title.value, active: true },
      { key: 'subtitle', text: subtitle.value || '未知来源', active: false },
    ].filter(line => line.text)
  }
  return [idx - 1, idx, idx + 1]
    .filter(i => i >= 0 && i < lines.length)
    .map(i => ({ key: `${lines[i].time}-${i}`, text: lines[i].text, active: i === idx }))
})

function parseLrc(text) {
  if (!text || typeof text !== 'string') return []
  const lines = []
  const re = /\[(\d+):(\d+(?:[.:]\d+)?)\]/g
  for (const raw of text.split(/\r?\n/)) {
    if (!raw) continue
    const matches = [...raw.matchAll(re)]
    if (!matches.length) continue
    const content = raw.replace(re, '').trim()
    if (!content) continue
    for (const m of matches) {
      const min = Number(m[1])
      const sec = Number(String(m[2]).replace(':', '.'))
      if (Number.isFinite(min) && Number.isFinite(sec)) {
        lines.push({ time: min * 60 + sec, text: content })
      }
    }
  }
  return lines.sort((a, b) => a.time - b.time)
}

function onTimeUpdate(e) {
  const time = e.target.currentTime || 0
  if (!isSeeking.value) {
    player.setCurrentTime(time)
    seekValue.value = time
  }
}

function onLoadedMeta(e) {
  const audio = e.target
  duration.value = Number.isFinite(audio.duration) ? audio.duration : (Number(player.currentTrack?.duration) || 0)
  player.setCurrentTime(audio.currentTime || 0)
  seekValue.value = audio.currentTime || 0
}

async function togglePlay() {
  const audio = audioRef.value
  if (!audio) return
  if (audio.paused) {
    try { await audio.play() } catch (err) { console.warn('play failed', err) }
  } else {
    audio.pause()
  }
}

function valueToTime(value) {
  const raw = Number(value) || 0
  const max = effectiveDuration.value || 0
  // 兼容旧前端缓存/浏览器行为：如果传入像百分比一样的 0-100 值，也能转成时间。
  if (max > 100 && raw <= 100) return raw * max / 100
  return raw
}

function beginSeek() {
  isSeeking.value = true
  seekValue.value = player.currentTime
}

function inputSeek(value) {
  const time = valueToTime(value)
  seekValue.value = time
  player.setCurrentTime(time)
}

function commitSeek(value = seekValue.value) {
  const time = Math.max(0, Math.min(valueToTime(value), effectiveDuration.value || Number.MAX_SAFE_INTEGER))
  seekValue.value = time
  player.setCurrentTime(time)
  if (audioRef.value) audioRef.value.currentTime = time
  isSeeking.value = false
}

function seekByPointer(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const clientX = event.touches?.[0]?.clientX ?? event.clientX
  const ratio = rect.width ? Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)) : 0
  const time = ratio * (effectiveDuration.value || 0)
  commitSeek(time)
}

function seekTo(time) {
  if (audioRef.value && Number.isFinite(time)) {
    commitSeek(time)
    audioRef.value.play?.()
  }
}

async function handleEnded() {
  if (player.playbackMode === 'repeat' && player.queueSize <= 1 && audioRef.value) {
    audioRef.value.currentTime = 0
    player.setCurrentTime(0)
    try { await audioRef.value.play() } catch (err) { console.warn('repeat play failed', err) }
    return
  }
  player.playNext()
}

watch(activeLyricIndex, async (idx) => {
  if (idx < 0 || !lyricsListRef.value) return
  await nextTick()
  const el = lyricsListRef.value.querySelector(`[data-lyric-index='${idx}']`)
  if (el && typeof el.scrollIntoView === 'function') {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
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
      {{ player.isCollapsed ? '‹' : '⌄' }}
    </button>

    <button class="player-info" type="button" title="查看正在播放详情" @click="handleTitleClick">
      <div class="player-title">
        <span class="player-title-text">{{ title }}</span>
      </div>
      <div class="player-sub">{{ subtitle || '未知来源' }}</div>
    </button>

    <div v-show="!player.isCollapsed" class="transport">
      <button class="transport-btn side" title="上一首" :disabled="!player.hasPrev" @click="player.playPrev">⏮</button>
      <button :class="['transport-btn', 'play-main', { playing: isPlaying }]" :title="isPlaying ? '暂停' : '播放'" @click="togglePlay">
        <span aria-hidden="true">{{ isPlaying ? 'Ⅱ' : '▶' }}</span>
      </button>
      <button class="transport-btn side" title="下一首" :disabled="!player.hasNext" @click="player.playNext">⏭</button>
    </div>

    <div v-show="!player.isCollapsed" class="seek-wrap">
      <span class="seek-time">{{ formatDuration(player.currentTime) }}</span>
      <div
        class="seek-track"
        :class="{ disabled: !effectiveDuration }"
        @click="seekByPointer"
        @pointerdown="seekByPointer"
        @touchstart.prevent="seekByPointer"
      >
        <div class="seek-fill" :style="{ width: seekPercent + '%' }"></div>
        <div class="seek-thumb" :style="{ left: seekPercent + '%' }"></div>
      </div>
      <input
        class="seek-range"
        type="range"
        min="0"
        max="100"
        step="0.1"
        :value="seekPercent"
        :disabled="!effectiveDuration"
        aria-label="播放进度"
        @pointerdown="beginSeek"
        @touchstart="beginSeek"
        @input="inputSeek($event.target.value)"
        @change="commitSeek($event.target.value)"
        @pointerup="commitSeek($event.target.value)"
        @touchend="commitSeek($event.target.value)"
        @keyup.enter="commitSeek($event.target.value)"
      />
      <span class="seek-time">{{ formatDuration(effectiveDuration) }}</span>
    </div>

    <audio
      ref="audioRef"
      :key="player.currentId"
      class="player-audio"
      autoplay
      :src="player.streamUrl()"
      @ended="handleEnded"
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onLoadedMeta"
      @play="isPlaying = true"
      @pause="isPlaying = false"
    />

    <div v-if="player.isCollapsed" class="collapsed-lyrics" aria-label="当前歌词">
      <TransitionGroup name="mini-lyric" tag="div" class="collapsed-lyrics-window">
        <div
          v-for="line in collapsedLyricWindow"
          :key="line.key"
          :class="['collapsed-lyric-line', { active: line.active }]"
        >{{ line.text }}</div>
      </TransitionGroup>
    </div>

    <button
      v-show="!player.isCollapsed"
      :class="['mode-toggle', { active: player.playbackMode !== 'order' }]"
      :title="playbackModeMeta.title"
      aria-label="切换播放模式"
      @click="player.togglePlaybackMode"
    >
      <span aria-hidden="true">{{ playbackModeMeta.icon }}</span>
      <em>{{ playbackModeMeta.label }}</em>
    </button>

    <button
      v-show="!player.isCollapsed"
      :class="['panel-toggle', { active: player.isQueueOpen }]"
      title="播放队列"
      aria-label="播放队列"
      @click="toggleQueuePanel"
    >
      <span class="panel-icon" aria-hidden="true">☰</span>
      <span class="panel-label">{{ queueLabel }}</span>
    </button>

    <button class="player-close" title="关闭播放器" @click="player.close">×</button>

    <div v-show="!player.isCollapsed" class="mobile-progress" aria-hidden="true">
      <div :style="{ width: seekPercent + '%' }"></div>
    </div>

    <Transition name="player-panel">
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
          <div v-else-if="parsedLyrics.length" ref="lyricsListRef" class="lyrics-box lyrics-list">
            <button
              v-for="(line, idx) in parsedLyrics"
              :key="`${line.time}-${idx}`"
              :data-lyric-index="idx"
              :class="['lyric-line', { active: idx === activeLyricIndex }]"
              @click="seekTo(line.time)"
            >{{ line.text }}</button>
          </div>
          <pre v-else-if="trackDetail?.lyrics" class="lyrics-box">{{ trackDetail.lyrics }}</pre>
          <div v-else class="lyrics-box muted">暂无歌词。可以在专辑详情里重新刮削补齐歌词。</div>
        </div>
      </div>
    </Transition>

    <Transition name="player-panel">
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
    </Transition>
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
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(max(16px, var(--blur-strength))) saturate(1.2);
  -webkit-backdrop-filter: blur(max(16px, var(--blur-strength))) saturate(1.2);
  transition: left .28s cubic-bezier(.2,.8,.2,1), right .28s cubic-bezier(.2,.8,.2,1), bottom .28s cubic-bezier(.2,.8,.2,1), width .28s cubic-bezier(.2,.8,.2,1), min-height .28s cubic-bezier(.2,.8,.2,1), padding .28s cubic-bezier(.2,.8,.2,1), border-radius .28s cubic-bezier(.2,.8,.2,1), transform .28s cubic-bezier(.2,.8,.2,1), opacity .2s ease;
}
.global-player.collapsed {
  left: auto;
  right: 24px;
  bottom: 20px;
  width: min(360px, calc(100vw - 48px));
  min-height: 48px;
  padding: 8px 10px;
}
.global-player.collapsed .player-info,
.global-player.collapsed .transport,
.global-player.collapsed .seek-wrap,
.global-player.collapsed .mode-toggle,
.global-player.collapsed .panel-toggle,
.global-player.collapsed .mobile-progress {
  display: none;
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
.play-main {
  width: 42px;
  height: 42px;
  border: 0;
  color: white;
  background: radial-gradient(circle at 30% 20%, color-mix(in srgb, white 24%, var(--accent)), var(--accent));
  box-shadow: 0 10px 24px color-mix(in srgb, var(--accent) 34%, transparent), inset 0 1px 0 rgba(255,255,255,.28);
  transform: translateZ(0);
}
.play-main span { transform: translateX(1px); font-size: 18px; font-weight: 900; line-height: 1; }
.play-main.playing span { transform: none; letter-spacing: -0.12em; }
.play-main:hover:not(:disabled) { color: white; background: var(--accent-hover); transform: translateY(-1px) scale(1.03); }
.transport-btn.side { background: transparent; border-color: transparent; }
.transport-btn.side:hover:not(:disabled) { border-color: var(--border); }
.player-info {
  min-width: 180px;
  max-width: 360px;
  overflow: hidden;
  cursor: pointer;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  font: inherit;
  padding: 0;
  -webkit-tap-highlight-color: transparent;
}
.player-info:hover .player-title-text { color: var(--accent); }
.player-title {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 800;
  white-space: nowrap;
}
.player-title-text {
  min-width: 0;
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
.seek-wrap {
  flex: 1;
  min-width: 260px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.seek-time {
  width: 42px;
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: center;
}
.seek-track {
  position: relative;
  flex: 1;
  height: 18px;
  min-width: 120px;
  cursor: pointer;
  display: flex;
  align-items: center;
}
.seek-track::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  height: 6px;
  border-radius: 999px;
  background: var(--surface);
  border: 1px solid var(--border);
}
.seek-fill {
  position: absolute;
  left: 0;
  height: 6px;
  border-radius: 999px;
  background: var(--accent);
  pointer-events: none;
}
.seek-thumb {
  position: absolute;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--text);
  border: 2px solid var(--accent);
  transform: translateX(-50%);
  box-shadow: 0 2px 8px rgba(0,0,0,.35);
  pointer-events: none;
}
.seek-track.disabled { opacity: .45; cursor: not-allowed; pointer-events: none; }
.seek-range {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}
.seek-range:disabled { opacity: 0; }
.player-audio {
  display: none;
}
.collapsed-lyrics { flex: 1; min-width: 0; height: 36px; overflow: hidden; display: flex; align-items: center; }
.collapsed-lyrics-window { width: 100%; display: flex; flex-direction: column; align-items: flex-start; justify-content: center; gap: 1px; }
.collapsed-lyric-line { width: 100%; color: var(--text-muted); font-size: 11px; line-height: 1.15; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; opacity: .62; transform: translateY(0); }
.collapsed-lyric-line.active { color: var(--text); font-size: 13px; font-weight: 800; opacity: 1; }
.mini-lyric-move, .mini-lyric-enter-active, .mini-lyric-leave-active { transition: all .32s cubic-bezier(.2,.8,.2,1); }
.mini-lyric-enter-from { opacity: 0; transform: translateY(10px); }
.mini-lyric-leave-to { opacity: 0; transform: translateY(-10px); }
.mini-lyric-leave-active { position: absolute; }
.mode-toggle { display: inline-flex; align-items: center; gap: 4px; height: 32px; padding: 0 9px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface); color: var(--text-dim); cursor: pointer; font-size: 12px; font-weight: 800; }
.mode-toggle em { font-style: normal; font-size: 11px; }
.mode-toggle:hover, .mode-toggle.active { color: var(--text); background: var(--surface-hover); border-color: var(--accent); }
.mode-toggle.active span { color: var(--accent); }
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
.panel-icon { font-size: 14px; line-height: 1; }
.panel-label { line-height: 1; }
.mobile-progress { display: none; }
.queue-panel,
.now-panel {
  position: absolute;
  right: 12px;
  bottom: calc(100% + 10px);
  width: min(420px, calc(100vw - 48px));
  max-height: min(460px, calc(100vh - 160px));
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg-elevated) 99%, transparent);
  border: 1px solid var(--border-strong, var(--border));
  border-radius: 18px;
  box-shadow: var(--shadow-soft);
  overflow: hidden;
  backdrop-filter: blur(max(18px, var(--blur-strength))) saturate(1.2);
  -webkit-backdrop-filter: blur(max(18px, var(--blur-strength))) saturate(1.2);
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
.lyrics-box.muted { display: flex; align-items: center; justify-content: center; text-align: center; color: var(--text-dim); border: 1px dashed var(--border); }
.lyrics-list { display: flex; flex-direction: column; gap: 4px; padding: 12px 12px; }
.lyric-line { width: 100%; text-align: center; border: 0; background: transparent; color: var(--text-muted); padding: 4px 6px; cursor: pointer; font-size: 13px; line-height: 1.6; transition: color .15s, transform .15s; }
.lyric-line:hover { color: var(--text-dim); }
.lyric-line.active { color: var(--text); font-weight: 800; transform: scale(1.04); }

.player-panel-enter-active,
.player-panel-leave-active {
  transition: opacity .22s ease, transform .24s cubic-bezier(.2,.8,.2,1), filter .22s ease;
}
.player-panel-enter-from,
.player-panel-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(.98);
  filter: blur(4px);
}

.queue-head div { display: flex; flex-direction: column; gap: 2px; }
.queue-head strong { font-size: 14px; }
.queue-head span { font-size: 12px; color: var(--text-dim); }
.queue-list { overflow-y: auto; padding: 6px; }
.queue-item { width: 100%; display: grid; grid-template-columns: 28px minmax(0,1fr) auto; gap: 10px; align-items: center; border: 0; background: transparent; color: var(--text-dim); border-radius: 12px; padding: 9px 10px; cursor: pointer; text-align: left; }
.queue-item:hover, .queue-item.active { background: var(--surface-hover); color: var(--text); }
.queue-index, .queue-duration { font-size: 12px; color: var(--text-dim); }
.queue-main { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.queue-main strong, .queue-main em { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.queue-main strong { font-size: 13px; color: var(--text); }
.queue-main em { font-style: normal; font-size: 12px; color: var(--text-dim); }

@media (max-width: 768px) {
  .global-player {
    left: max(10px, env(safe-area-inset-left));
    right: max(10px, env(safe-area-inset-right));
    bottom: var(--mobile-player-bottom, calc(64px + env(safe-area-inset-bottom)));
    min-height: 60px;
    gap: 8px;
    padding: 9px 10px;
    border-radius: 18px;
  }
  .global-player.collapsed {
    left: max(10px, env(safe-area-inset-left));
    right: max(10px, env(safe-area-inset-right));
    bottom: var(--mobile-player-bottom, calc(64px + env(safe-area-inset-bottom)));
    width: auto;
    min-width: 0;
    min-height: 44px;
    height: 44px;
    padding: 5px 10px;
    border-radius: 999px;
    justify-content: flex-start;
    gap: 8px;
  }
  .global-player.collapsed .collapse-toggle {
    width: 34px;
    height: 34px;
    border: 0;
    color: white;
    background: linear-gradient(135deg, var(--accent), var(--accent-hover));
    box-shadow: 0 10px 28px color-mix(in srgb, var(--accent) 36%, transparent);
    font-size: 22px;
    font-weight: 900;
  }
  .global-player.collapsed .player-info,
  .global-player.collapsed .transport,
  .global-player.collapsed .seek-wrap,
  .global-player.collapsed .panel-toggle,
  .global-player.collapsed .mobile-progress {
    display: none !important;
  }
  .collapse-toggle, .player-close, .transport-btn, .queue-close {
    width: 30px;
    height: 30px;
    font-size: 14px;
  }
  .play-main { width: 38px; height: 38px; }
  .play-main span { font-size: 17px; }
  .player-info { min-width: 0; max-width: none; flex: 1; }
  .player-title { font-size: 13px; }
  .player-sub { font-size: 11px; }
  .transport { gap: 4px; }
  .seek-wrap { display: none; }
  .panel-toggle, .mode-toggle { height: 30px; padding: 0 9px; display: inline-flex; align-items: center; gap: 5px; }
  .mode-toggle em { display: none; }
  .mobile-progress { display: block; position: absolute; left: 14px; right: 14px; bottom: 5px; height: 3px; border-radius: 999px; background: var(--surface); overflow: hidden; }
  .mobile-progress > div { height: 100%; border-radius: inherit; background: var(--accent); transition: width .2s linear; }
  .queue-panel { left: 0; right: 0; width: auto; max-height: min(420px, calc(100dvh - 180px)); }
  .now-panel { left: 0; right: 0; width: auto; grid-template-columns: 92px minmax(0, 1fr); max-height: min(520px, calc(100dvh - 180px)); overflow-y: auto; }
  .now-cover { width: 92px; height: 92px; border-radius: 14px; }
  .now-head strong { font-size: 15px; }
  .lyrics-box { grid-column: 1 / -1; max-height: 180px; }
}

@media (max-width: 430px) {
  .global-player { gap: 6px; padding: 9px 8px 11px; }
  .panel-toggle, .mode-toggle { width: 30px; padding: 0; justify-content: center; overflow: hidden; white-space: nowrap; }
  .panel-label { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; overflow: hidden; }
  .transport-btn[title="上一首"], .transport-btn[title="下一首"] { display: none; }
}
</style>
