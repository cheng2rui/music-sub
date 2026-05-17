import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getFile, getStreamUrl } from '@/api/index.js'

export const usePlayerStore = defineStore('player', () => {
  const currentTrack = ref(null)
  const queue = ref([])
  const queueIndex = ref(-1)
  const currentId = computed(() => currentTrack.value?.id || null)
  const queueSize = computed(() => queue.value.length)
  const hasPrev = computed(() => queueIndex.value > 0)
  const hasNext = computed(() => queueIndex.value >= 0 && queueIndex.value < queue.value.length - 1)
  const isCollapsed = ref(false)

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
    currentTrack.value = normalized[safeIndex]
    isCollapsed.value = false
  }

  function playNext() {
    if (!hasNext.value) return false
    queueIndex.value += 1
    currentTrack.value = queue.value[queueIndex.value]
    isCollapsed.value = false
    return true
  }

  function playPrev() {
    if (!hasPrev.value) return false
    queueIndex.value -= 1
    currentTrack.value = queue.value[queueIndex.value]
    isCollapsed.value = false
    return true
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
    playTrack,
    playQueue,
    playNext,
    playPrev,
    streamUrl,
    collapse,
    expand,
    toggleCollapsed,
    close,
  }
})
