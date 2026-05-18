<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useThemeStore } from '@/stores/theme.js'
import { useAuthStore } from '@/stores/auth.js'
import ThemeSwitcher from '@/components/ThemeSwitcher.vue'
import GlobalPlayer from '@/components/GlobalPlayer.vue'

const route = useRoute()
const router = useRouter()
const theme = useThemeStore()
const auth = useAuthStore()

const pageTitle = computed(() => route.meta?.title || '音乐订阅管理')
const isGlass = computed(() => theme.current.includes('glass'))
const isLoginPage = computed(() => route.name === 'login')

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <!-- Login page: no sidebar -->
  <div v-if="isLoginPage" class="login-wrapper">
    <router-view />
  </div>

  <!-- Main layout with sidebar -->
  <div v-else class="app-layout" :class="{ 'glass-active': isGlass }" :style="isGlass && theme.backgroundImage ? { backgroundImage: `url(${theme.backgroundImage})` } : {}">
    <!-- Sidebar (desktop) -->
    <aside class="sidebar">
      <div class="sidebar-logo">🎵 音乐订阅</div>
      <nav class="sidebar-nav">
        <router-link to="/discover">🏠 发现</router-link>
        <router-link to="/subs">📡 订阅管理</router-link>
        <router-link to="/search">🔍 PT搜索</router-link>
        <router-link to="/online">🎧 在线下载</router-link>
        <router-link to="/tasks">⬇️ 任务列表</router-link>
        <router-link to="/library">🎶 音乐库</router-link>
        <router-link to="/logs">📜 日志</router-link>
        <router-link to="/settings">⚙️ 设置</router-link>
      </nav>
      <div class="sidebar-bottom">
        <ThemeSwitcher />
        <div class="user-info">
          <span>已登录</span>
          <button @click="handleLogout" class="btn-logout">退出</button>
        </div>
        <div class="version-tag">v0.6.16</div>
      </div>
    </aside>

    <!-- Main -->
    <div class="main-wrapper">
      <header class="topbar">
        <h1 class="page-title">{{ pageTitle }}</h1>
        <div class="topbar-right">
          <ThemeSwitcher class="mobile-theme" />
          <button @click="handleLogout" class="btn-logout mobile-logout">退出</button>
        </div>
      </header>
      <main class="main-content">
        <router-view />
      </main>
    </div>

    <GlobalPlayer />

    <!-- Bottom tab bar (mobile) -->
    <nav class="bottom-tabs">
      <router-link to="/discover" title="发现">🏠</router-link>
      <router-link to="/subs" title="订阅">📡</router-link>
      <router-link to="/search" title="PT搜索">🔍</router-link>
      <router-link to="/online" title="在线下载">🎧</router-link>
      <router-link to="/tasks" title="任务">⬇️</router-link>
      <router-link to="/library" title="音乐库">🎶</router-link>
      <router-link to="/logs" title="日志">📜</router-link>
      <router-link to="/settings" title="设置">⚙️</router-link>
    </nav>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.app-layout.glass-active {
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
}
.sidebar {
  width: 240px;
  min-width: 240px;
  background: var(--bg-elevated);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 16px 0;
}
.sidebar-logo {
  font-size: 18px;
  font-weight: 700;
  padding: 0 20px 20px;
  color: var(--text);
}
.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  padding: 0 8px;
}
.sidebar-nav a {
  padding: 10px 12px;
  color: var(--text-dim);
  border-radius: var(--radius-md);
  transition: all 0.15s;
  font-size: 14px;
}
.sidebar-nav a:hover {
  color: var(--text);
  background: var(--surface);
}
.sidebar-nav a.router-link-active {
  color: var(--text);
  background: var(--surface);
}
.sidebar-bottom {
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.user-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
}
.btn-logout {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 12px;
  padding: 4px 8px;
}
.btn-logout:hover { color: var(--danger); }
.version-tag {
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
  margin-top: 4px;
}
.main-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}
.topbar {
  height: 56px;
  min-height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-elevated);
}
.page-title { font-size: 18px; font-weight: 600; }
.topbar-right { display: flex; align-items: center; gap: 12px; }
.main-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  padding-bottom: 112px;
}
.login-wrapper {
  min-height: 100vh;
  background: var(--bg);
}

/* Bottom tab bar - hidden on desktop */
.bottom-tabs {
  display: none;
}

/* Mobile theme/logout in topbar - hidden on desktop */
.mobile-theme, .mobile-logout {
  display: none;
}

/* ===== Mobile ===== */
@media (max-width: 768px) {
  .sidebar {
    display: none;
  }
  .topbar {
    padding: 0 16px;
    height: 48px;
    min-height: 48px;
  }
  .page-title { font-size: 16px; }
  .main-content {
    padding: 16px;
    padding-bottom: 144px; /* space for player + bottom tabs */
  }
  .mobile-theme, .mobile-logout {
    display: flex;
  }
  .bottom-tabs {
    display: flex;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 56px;
    background: var(--bg-elevated);
    border-top: 1px solid var(--border);
    align-items: center;
    justify-content: space-around;
    z-index: 100;
    padding: 0 8px;
  }
  .bottom-tabs a {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 44px;
    border-radius: var(--radius-md);
    font-size: 18px;
    color: var(--text-dim);
    transition: all 0.15s;
  }
  .bottom-tabs a.router-link-active {
    color: var(--accent);
    background: var(--surface);
  }
}
</style>