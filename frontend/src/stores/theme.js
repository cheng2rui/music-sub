import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const THEMES = ['dark', 'light', 'dark-glass', 'light-glass']

export const useThemeStore = defineStore('theme', () => {
  const stored = localStorage.getItem('music_sub_theme')
  const current = ref(stored && THEMES.includes(stored) ? stored : 'dark')
  const backgroundImage = ref(localStorage.getItem('music_sub_bg_image') || '')

  watch(current, (val) => {
    localStorage.setItem('music_sub_theme', val)
    document.documentElement.setAttribute('data-theme', val)
  })

  watch(backgroundImage, (val) => {
    localStorage.setItem('music_sub_bg_image', val)
    document.documentElement.setAttribute('data-bg-image', val)
  })

  function setTheme(theme) {
    if (THEMES.includes(theme)) current.value = theme
  }

  function setBackgroundImage(url) {
    backgroundImage.value = url
  }

  // init on load
  document.documentElement.setAttribute('data-theme', current.value)
  if (backgroundImage.value) {
    document.documentElement.setAttribute('data-bg-image', backgroundImage.value)
  }

  return { current, backgroundImage, setTheme, setBackgroundImage, THEMES }
})