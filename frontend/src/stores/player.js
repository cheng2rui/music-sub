import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getFile, getStreamUrl } from '@/api/index.js'

export const usePlayerStore = defineStore('player', () => {
  const currentTrack = ref(null)
  const queue = ref([])
  const queueIndex = ref(-1)
  const currentId = computed(() => currentTrack.value?.id || null)
  const queueSize = computed(() => queue.value.length)
  const playbackMode = ref('order') // order | shuffle | repeat
  const hasPrev = computed(() => queueIndex.value > 0 || (playbackMode.value === 'repeat' && queue.value.length > 1))
  const hasNext = computed(() => queueIndex.value >= 0 && (queueIndex.value < queue.value.length - 1 || playbackMode.value !== 'order'))
  const isCollapsed = ref(false)
  const isQueueOpen = ref(false)
  const currentTime = ref(0)

  function normalizeTrack(track) {
    return {
      id: track.id,
      title: track.title || track.file_path || '未知曲目',
      artist: track.artist || '未知艺人',
      album: track.album || '未知专辑',
      duration: track.duration || 0,
    }
  }

  async function playTrack(trackOrId) {
    const track = typeof trackOrId === 'object' ? trackOrId : await getFile(trackOrId)
    const normalized = normalizeTrack(track)
    currentTime.value = 0
    currentTrack.value = normalized
    const existingIndex = queue.value.findIndex(t => t.id === normalized.id)
    if (existingIndex >= 0) {
      queueIndex.value = existingIndex
    } else {
      queue.value = [normalized]
      queueIndex.value = 0
    }
    isCollapsed.value = false
  }

  function playQueue(tracks, startIndex = 0) {
    const normalized = (tracks || []).filter(t => t?.id).map(normalizeTrack)
    if (!normalized.length) return
    const safeIndex = Math.max(0, Math.min(startIndex, normalized.length - 1))
    queue.value = normalized
    queueIndex.value = safeIndex
    currentTime.value = 0
    currentTrack.value = normalized[safeIndex]
    isCollapsed.value = false
  }

  function randomQueueIndex() {
    if (queue.value.length <= 1) return queueIndex.value
    let next = queueIndex.value
    while (next === queueIndex.value) next = Math.floor(Math.random() * queue.value.length)
    return next
  }

  function playNext() {
    if (!queue.value.length || queueIndex.value < 0) return false
    if (playbackMode.value === 'shuffle') {
      queueIndex.value = randomQueueIndex()
    } else if (queueIndex.value < queue.value.length - 1) {
      queueIndex.value += 1
    } else if (playbackMode.value === 'repeat') {
      queueIndex.value = 0
    } else {
      return false
    }
    currentTime.value = 0
    currentTrack.value = queue.value[queueIndex.value]
    return true
  }

  function playPrev() {
    if (!queue.value.length || queueIndex.value < 0) return false
    if (playbackMode.value === 'shuffle') {
      queueIndex.value = randomQueueIndex()
    } else if (queueIndex.value > 0) {
      queueIndex.value -= 1
    } else if (playbackMode.value === 'repeat') {
      queueIndex.value = queue.value.length - 1
    } else {
      return false
    }
    currentTime.value = 0
    currentTrack.value = queue.value[queueIndex.value]
    return true
  }

  function playAt(index) {
    if (index < 0 || index >= queue.value.length) return false
    queueIndex.value = index
    currentTime.value = 0
    currentTrack.value = queue.value[index]
    isCollapsed.value = false
    return true
  }

  function setCurrentTime(t) {
    currentTime.value = Number(t) || 0
  }

  function setPlaybackMode(mode) {
    if (['order', 'shuffle', 'repeat'].includes(mode)) playbackMode.value = mode
  }

  function togglePlaybackMode() {
    const modes = ['order', 'shuffle', 'repeat']
    const idx = modes.indexOf(playbackMode.value)
    playbackMode.value = modes[(idx + 1) % modes.length]
  }

  function toggleQueue() {
    isQueueOpen.value = !isQueueOpen.value
  }

  function closeQueue() {
    isQueueOpen.value = false
  }

  function streamUrl(id = currentId.value) {
    return id ? getStreamUrl(id) : ''
  }

  function collapse() {
    isCollapsed.value = true
  }

  function expand() {
    isCollapsed.value = false
  }

  function toggleCollapsed() {
    isCollapsed.value = !isCollapsed.value
  }

  function close() {
    currentTrack.value = null
    queue.value = []
    queueIndex.value = -1
    isCollapsed.value = false
    isQueueOpen.value = false
    currentTime.value = 0
  }

  return {
    currentTrack,
    queue,
    queueIndex,
    currentId,
    queueSize,
    hasPrev,
    hasNext,
    isCollapsed,
    isQueueOpen,
    currentTime,
    playbackMode,
    playTrack,
    playQueue,
    playNext,
    playPrev,
    playAt,
    toggleQueue,
    closeQueue,
    setCurrentTime,
    setPlaybackMode,
    togglePlaybackMode,
    streamUrl,
    collapse,
    expand,
    toggleCollapsed,
    close,
  }
})
