<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'
import AppButton from '@/components/AppButton.vue'
import { useThemeStore } from '@/stores/theme.js'
import { animalIslandIcons } from '@/utils/animalIsland.js'

const router = useRouter()
const auth = useAuthStore()
const theme = useThemeStore()
const isIsland = computed(() => theme.current === 'island')

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function handleLogin() {
  if (!username.value || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    router.push('/discover')
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo"><img v-if="isIsland" :src="animalIslandIcons.home" alt="" /><span v-else>🎵</span></div>
      <h1 class="login-title">音乐订阅管理</h1>
      <form @submit.prevent="handleLogin" class="login-form">
        <div class="form-group">
          <label>用户名</label>
          <input v-model="username" type="text" placeholder="请输入用户名" autocomplete="username" />
        </div>
        <div class="form-group">
          <label>密码</label>
          <input v-model="password" type="password" placeholder="请输入密码" autocomplete="current-password" />
        </div>
        <p v-if="error" class="error-msg">{{ error }}</p>
        <AppButton type="submit" variant="primary" size="md" :loading="loading" style="width:100%;justify-content:center;">
          登录
        </AppButton>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
}
.login-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 48px 40px;
  width: 360px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}
.login-logo { font-size: 56px; display: flex; align-items: center; justify-content: center; }
.login-logo img { width: 78px; height: 78px; object-fit: contain; filter: drop-shadow(0 8px 8px rgba(61, 52, 40, .18)); }
.login-title { font-size: 22px; font-weight: 700; }
.login-form { width: 100%; display: flex; flex-direction: column; gap: 14px; }
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-group label { font-size: 12px; color: var(--text-dim); font-weight: 600; }
.form-group input { width: 100%; }
.error-msg { color: var(--danger); font-size: 13px; text-align: center; margin: 0; }
</style>