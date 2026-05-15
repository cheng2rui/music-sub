import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const routes = [
  { path: '/', redirect: '/discover' },
  { path: '/discover', name: 'discover', meta: { title: '发现' } },
  { path: '/subs', name: 'subs', meta: { title: '订阅管理' } },
  { path: '/search', name: 'search', meta: { title: '搜索' } },
  { path: '/tasks', name: 'tasks', meta: { title: '任务列表' } },
  { path: '/library', name: 'library', meta: { title: '音乐库' } },
  { path: '/settings', name: 'settings', meta: { title: '设置' } },
  { path: '/logs', name: 'logs', meta: { title: '日志' } },
  { path: '/login', name: 'login', meta: { title: '登录' } }
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