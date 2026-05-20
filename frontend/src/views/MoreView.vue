<script setup>
import { computed } from 'vue'
import { useThemeStore } from '@/stores/theme.js'
import { animalIslandIcons } from '@/utils/animalIsland.js'

const theme = useThemeStore()
const isIsland = computed(() => theme.current === 'island')
const groups = [
  {
    title: '管理',
    items: [
      { to: '/subs', icon: '📡', islandIconSrc: animalIslandIcons.chat, title: '订阅管理', subtitle: '维护订阅源、专辑与规则' },
      { to: '/online', icon: '🎧', islandIconSrc: animalIslandIcons.shopping, title: '在线下载', subtitle: '搜索在线资源并加入下载' },
    ],
  },
  {
    title: '工具',
    items: [
      { to: '/assistant', icon: '🤖', islandIconSrc: animalIslandIcons.nook, title: '智能助手', subtitle: '用自然语言处理音乐订阅' },
      { to: '/logs', icon: '📜', islandIconSrc: animalIslandIcons.recipes, title: '日志', subtitle: '查看运行状态与错误记录' },
    ],
  },
  {
    title: '系统',
    items: [
      { to: '/settings', icon: '⚙️', islandIconSrc: animalIslandIcons.system, title: '设置', subtitle: '配置下载器、路径与系统选项' },
    ],
  },
]
</script>

<template>
  <div class="more-page page-scroll">
    <section v-for="group in groups" :key="group.title" class="more-section">
      <h2 class="section-title">{{ group.title }}</h2>
      <div class="more-list">
        <router-link v-for="item in group.items" :key="item.to" :to="item.to" class="more-card">
          <span class="more-icon" aria-hidden="true"><img v-if="isIsland && item.islandIconSrc" :src="item.islandIconSrc" alt="" class="animal-more-icon" /><span v-else>{{ item.icon }}</span></span>
          <span class="more-copy">
            <span class="more-title">{{ item.title }}</span>
            <span class="more-subtitle">{{ item.subtitle }}</span>
          </span>
          <span class="more-chevron" aria-hidden="true">›</span>
        </router-link>
      </div>
    </section>
  </div>
</template>

<style scoped>
.more-page {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.more-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.section-title {
  margin: 0;
  padding: 0 4px;
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 800;
  letter-spacing: .04em;
}
.more-list {
  display: grid;
  gap: 10px;
}
.more-card {
  min-height: 72px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: var(--bg-elevated);
  color: var(--text);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  transition: transform .15s, border-color .15s, background .15s;
}
.more-card:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--accent) 34%, var(--border));
  background: color-mix(in srgb, var(--accent) 8%, var(--bg-elevated));
}
.more-icon {
  width: 42px;
  height: 42px;
  border-radius: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--surface);
  font-size: 20px;
}
.animal-more-icon { width: 34px; height: 34px; object-fit: contain; filter: drop-shadow(0 3px 2px rgba(61, 52, 40, .16)); }
.more-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.more-title {
  font-size: 15px;
  font-weight: 800;
}
.more-subtitle {
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.more-chevron {
  color: var(--text-muted);
  font-size: 28px;
  line-height: 1;
}

@media (max-width: 768px) {
  .more-page {
    padding: 14px 14px var(--mobile-page-bottom);
    gap: 16px;
  }
  .more-card {
    border-radius: 16px;
  }
}
</style>
