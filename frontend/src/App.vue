<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useThemeStore } from '@/stores/theme.js'
import { useAuthStore } from '@/stores/auth.js'
import ThemeSwitcher from '@/components/ThemeSwitcher.vue'

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
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-logo">🎵 音乐订阅</div>
      <nav class="sidebar-nav">
        <router-link to="/discover">发现</router-link>
        <router-link to="/subs">订阅管理</router-link>
        <router-link to="/search">搜索</router-link>
        <router-link to="/tasks">任务列表</router-link>
        <router-link to="/library">音乐库</router-link>
        <router-link to="/logs">日志</router-link>
        <router-link to="/settings">设置</router-link>
      </nav>
      <div class="sidebar-bottom">
        <ThemeSwitcher />
        <div class="user-info">
          <span>{{ auth.token ? '已登录' : '' }}</span>
          <button @click="handleLogout" class="btn-logout">退出</button>
        </div>
      </div>
    </aside>

    <!-- Main -->
    <div class="main-wrapper">
      <header class="topbar">
        <h1 class="page-title">{{ pageTitle }}</h1>
        <div class="topbar-right">
          <span class="text-dim">{{ auth.token ? '已登录' : '' }}</span>
        </div>
      </header>
      <main class="main-content">
        <router-view />
      </main>
    </div>
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
}
.sidebar-nav a {
  padding: 10px 20px;
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
  padding: 0;
}
.btn-logout:hover { color: var(--danger); }
.main-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
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
}
.login-wrapper {
  min-height: 100vh;
  background: var(--bg);
}
</style>