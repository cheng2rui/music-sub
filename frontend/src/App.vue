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

const navItems = [
  { to: '/discover', icon: '🏠', label: '发现', short: '发现' },
  { to: '/subs', icon: '📡', label: '订阅管理', short: '订阅' },
  { to: '/search', icon: '🔍', label: 'PT 搜索', short: '搜索' },
  { to: '/online', icon: '🎧', label: '在线下载', short: '在线' },
  { to: '/tasks', icon: '⬇️', label: '任务列表', short: '任务' },
  { to: '/assistant', icon: '🤖', label: '智能助手', short: '助手' },
  { to: '/library', icon: '🎶', label: '音乐库', short: '曲库' },
  { to: '/logs', icon: '📜', label: '日志', short: '日志' },
  { to: '/settings', icon: '⚙️', label: '设置', short: '设置' },
]

const pageTitle = computed(() => route.meta?.title || '音乐订阅管理')
const isGlass = computed(() => theme.current.includes('glass'))
const isLoginPage = computed(() => route.name === 'login')

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div v-if="isLoginPage" class="login-wrapper">
    <router-view />
  </div>

  <div v-else class="app-layout" :class="{ 'glass-active': isGlass }" :style="isGlass && theme.backgroundImage ? { backgroundImage: `url(${theme.backgroundImage})` } : {}">
    <aside class="sidebar">
      <div class="sidebar-logo">
        <img src="/logo.svg" alt="Music Sub" class="sidebar-logo-img" />
        <span>Music Sub</span>
      </div>
      <nav class="sidebar-nav" aria-label="主导航">
        <router-link v-for="item in navItems" :key="item.to" :to="item.to" class="nav-link">
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-bottom">
        <ThemeSwitcher />
        <div class="user-info">
          <span>已登录</span>
          <button @click="handleLogout" class="btn-logout">退出</button>
        </div>
        <div class="version-tag">v0.7.2</div>
      </div>
    </aside>

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

    <nav class="bottom-tabs" aria-label="移动端导航">
      <router-link v-for="item in navItems" :key="item.to" :to="item.to" class="bottom-tab" :title="item.label">
        <span class="tab-icon" aria-hidden="true">{{ item.icon }}</span>
        <span class="tab-label">{{ item.short }}</span>
      </router-link>
    </nav>
  </div>
</template>

<style scoped>
.app-layout {
  --mobile-tab-height: 64px;
  display: flex;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--bg);
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
  font-weight: 800;
  padding: 0 20px 20px;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 10px;
  letter-spacing: -0.02em;
}
.sidebar-logo-img {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  flex-shrink: 0;
  filter: drop-shadow(0 0 10px rgba(34, 211, 238, 0.28));
}
.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  padding: 0 10px;
}
.nav-link {
  min-height: 42px;
  padding: 6px 10px;
  color: var(--text-dim);
  border-radius: 14px;
  transition: color 0.15s, background 0.15s, transform 0.15s;
  font-size: 14px;
  font-weight: 650;
  display: flex;
  align-items: center;
  gap: 10px;
}
.nav-link:hover {
  color: var(--text);
  background: var(--surface);
}
.nav-link.router-link-active {
  color: var(--text);
  background: color-mix(in srgb, var(--accent) 14%, var(--surface));
}
.nav-link.router-link-active .nav-icon {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 18%, transparent);
  border-color: color-mix(in srgb, var(--accent) 36%, var(--border));
}
.nav-icon,
.tab-icon {
  width: 30px;
  height: 30px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 16px;
  line-height: 1;
  background: var(--surface);
  border: 1px solid transparent;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
}
.nav-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
  color: var(--text-dim);
}
.btn-logout {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 999px;
}
.btn-logout:hover { color: var(--danger); background: var(--surface); }
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
  flex-shrink: 0;
}
.page-title { font-size: 18px; font-weight: 750; letter-spacing: -0.02em; }
.topbar-right { display: flex; align-items: center; gap: 12px; }
.main-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.login-wrapper {
  min-height: 100vh;
  min-height: 100dvh;
  background: var(--bg);
}
.bottom-tabs { display: none; }
.mobile-theme, .mobile-logout { display: none; }

@media (max-width: 768px) {
  .app-layout { display: block; }
  .sidebar { display: none; }
  .main-wrapper { height: 100%; }
  .topbar {
    height: 50px;
    min-height: 50px;
    padding: 0 max(14px, env(safe-area-inset-right)) 0 max(14px, env(safe-area-inset-left));
    background: color-mix(in srgb, var(--bg-elevated) 94%, transparent);
    backdrop-filter: blur(16px);
  }
  .page-title { font-size: 16px; }
  .main-content {
    overflow: hidden;
    /* Reserve bottom space for the tab bar and the floating player when active. */
    padding-bottom: calc(144px + env(safe-area-inset-bottom));
  }
  .mobile-theme, .mobile-logout { display: flex; }
  .bottom-tabs {
    display: flex;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: calc(var(--mobile-tab-height) + env(safe-area-inset-bottom));
    background: color-mix(in srgb, var(--bg-elevated) 96%, transparent);
    border-top: 1px solid var(--border);
    align-items: stretch;
    justify-content: flex-start;
    z-index: 100;
    padding: 6px max(8px, env(safe-area-inset-right)) calc(6px + env(safe-area-inset-bottom)) max(8px, env(safe-area-inset-left));
    gap: 4px;
    overflow-x: auto;
    overscroll-behavior-x: contain;
    -webkit-overflow-scrolling: touch;
    backdrop-filter: blur(18px);
    scrollbar-width: none;
  }
  .bottom-tabs::-webkit-scrollbar { display: none; }
  .bottom-tab {
    min-width: 54px;
    height: 52px;
    border-radius: 16px;
    color: var(--text-dim);
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    transition: color .15s, background .15s, transform .15s;
    -webkit-tap-highlight-color: transparent;
  }
  .tab-icon {
    width: 28px;
    height: 28px;
    border-radius: 11px;
    font-size: 15px;
    background: transparent;
  }
  .tab-label {
    font-size: 10px;
    line-height: 1;
    font-weight: 700;
    white-space: nowrap;
  }
  .bottom-tab.router-link-active {
    color: var(--text);
    background: color-mix(in srgb, var(--accent) 13%, var(--surface));
  }
  .bottom-tab.router-link-active .tab-icon {
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 16%, transparent);
  }
}
</style>
