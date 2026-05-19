<script setup>
import { computed, ref } from 'vue'
import { useThemeStore } from '@/stores/theme.js'

defineProps({
  src: { type: String, default: '' },
  showPlay: { type: Boolean, default: false }
})

const theme = useThemeStore()
const isIsland = computed(() => theme.current === 'island')
const hovered = ref(false)
const hasError = ref(false)

function onError() { hasError.value = true }
</script>

<template>
  <div class="cover-wrap" @mouseenter="hovered = true" @mouseleave="hovered = false">
    <img v-if="src && !hasError" :src="src" class="cover-img" @error="onError" />
    <div v-else class="cover-placeholder">
      <img v-if="isIsland" src="/animal-island/nook-phone/AppIcons.svg" alt="" class="animal-cover-icon" />
      <span v-else>🎵</span>
    </div>
    <div v-if="showPlay && hovered" class="cover-play-overlay">
      <span class="play-icon">▶</span>
    </div>
  </div>
</template>

<style scoped>
.cover-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 1;
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--surface);
}
.cover-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cover-placeholder {
  width: 100%; height: 100%;
  display: flex; align-items: center; justify-content: center;
  font-size: 32px;
}
.animal-cover-icon {
  width: 42%;
  height: 42%;
  object-fit: contain;
  filter: drop-shadow(0 4px 3px rgba(61, 52, 40, .16));
}
.cover-play-overlay {
  position: absolute; inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-md);
}
.play-icon {
  width: 48px; height: 48px;
  background: var(--accent);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; color: #000;
}
</style>