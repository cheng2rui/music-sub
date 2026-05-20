import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router/index.js'
import App from './App.vue'
import './styles/global.css'

const isStandalone = window.navigator.standalone === true || window.matchMedia?.('(display-mode: standalone)').matches
if (isStandalone) {
  document.documentElement.classList.add('pwa-standalone')
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')