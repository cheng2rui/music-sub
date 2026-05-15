<script setup>
import { useThemeStore } from '@/stores/theme.js'

const theme = useThemeStore()
const labels = { dark: '🌙 深色', light: '☀️ 浅色', 'dark-glass': '🔮 深色毛玻璃', 'light-glass': '☁️ 浅色毛玻璃' }
</script>

<template>
  <div class="theme-switcher">
    <span class="theme-label">主题</span>
    <div class="theme-options">
      <button
        v-for="t in theme.THEMES"
        :key="t"
        class="theme-btn"
        :class="{ active: theme.current === t }"
        @click="theme.setTheme(t)"
      >{{ labels[t] }}</button>
    </div>
  </div>
</template>

<style scoped>
.theme-switcher { display: flex; flex-direction: column; gap: 6px; }
.theme-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }
.theme-options { display: flex; flex-wrap: wrap; gap: 4px; }
.theme-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-dim);
  border-radius: var(--radius-sm);
  padding: 4px 8px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}
.theme-btn:hover { background: var(--surface-hover); color: var(--text); }
.theme-btn.active { background: var(--accent); color: #000; border-color: var(--accent); }
</style>