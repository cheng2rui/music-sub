import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getFile, getStreamUrl } from '@/api/index.js'

export const usePlayerStore = defineStore('player', () => {
  const currentTrack = ref(null)
  const currentId = computed(() => currentTrack.value?.id || null)
  const isCollapsed = ref(false)

  async function playTrack(trackOrId) {
    const track = typeof trackOrId === 'object' ? trackOrId : await getFile(trackOrId)
    currentTrack.value = {
      id: track.id,
      title: track.title || track.file_path || '未知曲目',
      artist: track.artist || '未知艺人',
      album: track.album || '未知专辑',
      duration: track.duration || 0,
    }
    isCollapsed.value = false
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
    isCollapsed.value = false
  }

  return {
    currentTrack,
    currentId,
    isCollapsed,
    playTrack,
    streamUrl,
    collapse,
    expand,
    toggleCollapsed,
    close,
  }
})
