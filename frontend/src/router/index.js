import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const routes = [
  { path: '/', redirect: '/discover' },
  {
    path: '/discover',
    name: 'discover',
    meta: { title: '发现' },
    component: () => import('@/views/DiscoverView.vue')
  },
  {
    path: '/subs',
    name: 'subs',
    meta: { title: '订阅管理' },
    component: () => import('@/views/SubsView.vue')
  },
  {
    path: '/search',
    name: 'search',
    meta: { title: '搜索' },
    component: () => import('@/views/SearchView.vue')
  },
  {
    path: '/online',
    name: 'online',
    meta: { title: '在线下载' },
    component: () => import('@/views/OnlineView.vue')
  },
  {
    path: '/tasks',
    name: 'tasks',
    meta: { title: '任务列表' },
    component: () => import('@/views/TasksView.vue')
  },
  {
    path: '/library',
    name: 'library',
    meta: { title: '音乐库' },
    component: () => import('@/views/LibraryView.vue')
  },
  {
    path: '/settings',
    name: 'settings',
    meta: { title: '设置' },
    component: () => import('@/views/SettingsView.vue')
  },
  {
    path: '/logs',
    name: 'logs',
    meta: { title: '日志' },
    component: () => import('@/views/LogsView.vue')
  },
  {
    path: '/login',
    name: 'login',
    meta: { title: '登录', noAuth: true },
    component: () => import('@/views/LoginView.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  if (to.name !== 'login' && !auth.isLoggedIn) {
    next({ name: 'login' })
  } else if (to.name === 'login' && auth.isLoggedIn) {
    next({ name: 'discover' })
  } else {
    next()
  }
})

export default router
