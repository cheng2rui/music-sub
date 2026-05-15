<script setup>
import { useThemeStore } from '@/stores/theme.js'

const theme = useThemeStore()
const options = [
  { value: 'dark', label: '🌙 深色' },
  { value: 'light', label: '☀️ 浅色' },
  { value: 'dark-glass', label: '🔮 深色毛玻璃' },
  { value: 'light-glass', label: '☁️ 浅色毛玻璃' }
]
</script>

<template>
  <div class="theme-switcher">
    <select :value="theme.current" @change="theme.setTheme($event.target.value)" class="theme-select">
      <option v-for="opt in options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
    </select>
  </div>
</template>

<style scoped>
.theme-switcher { display: flex; align-items: center; }
.theme-select {
  width: 100%;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: var(--radius-md);
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
  outline: none;
  transition: border-color 0.2s;
  appearance: auto;
}
.theme-select:focus { border-color: var(--accent); }
</style>
