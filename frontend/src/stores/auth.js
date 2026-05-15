import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('music_sub_token') || '')

  const isLoggedIn = computed(() => !!token.value)

  async function login(username, password) {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || err.message || '登录失败')
    }
    const data = await res.json()
    token.value = data.token
    localStorage.setItem('music_sub_token', data.token)
  }

  function logout() {
    token.value = ''
    localStorage.removeItem('music_sub_token')
  }

  return { token, isLoggedIn, login, logout }
})