<script setup>
import { computed, ref, onMounted } from 'vue'
import { getSettings, updateSettings, testQb, testTelegram, testNotifyChannel, getNotifyStatus, getNotifyEvents, getQqbotGatewayStatus, restartQqbotGateway, getWechatClawStatus, refreshWechatClawQrcode, restartWechatClaw, logoutWechatClaw, testSite, getScheduler, runScheduler, changePasswordApi, getAssistantProviders, getAssistantTools, testAssistantProvider } from '@/api/index.js'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'
import { useThemeStore } from '@/stores/theme.js'
import { animalIslandIcons } from '@/utils/animalIsland.js'

const theme = useThemeStore()
const isIsland = computed(() => theme.current === 'island')

const settings = ref({
  sites: {
    mteam: { enabled: false, url: '', api_key: '', token: '', cookie: '' },
    opencd: { enabled: false, url: '', api_key: '', token: '', cookie: '' },
    ptclub: { enabled: false, url: '', api_key: '', token: '', cookie: '' },
    dismusic: { enabled: false, url: '', api_key: '', token: '', cookie: '' }
  },
  qbittorrent: { host: '', username: '', password: '', category: 'music', save_path: '/downloads/music', tag: 'music-sub' },
  paths: { library: '/music', structure: '{artist}/{album}', downloads: '/downloads/music' },
  scraper: { sources: ['qqmusic', 'netease', 'kugou', 'migu', 'kuwo', 'musicbrainz'], embed_cover: true, save_cover_file: true, save_lyrics: true, save_nfo: false, rename_file: false, overwrite_tag: false, tag_write_mode: 'fill_missing', break_hardlink_before_tag: true },
  scheduler: { search_interval_minutes: 30, check_complete_interval_minutes: 5, cleanup_scan_enabled: true, cleanup_scan_interval_hours: 24 },
  notify: {
    webhook_token: '',
    telegram: { enabled: false, bot_token: '', chat_id: '', on_download_added: false, on_download_complete: true, on_scrape_complete: true, on_error: true, on_cleanup_candidates: true, assistant_chat: true },
    wecom: { enabled: false, corp_id: '', agent_id: '', app_secret: '', to_user: '@all', proxy: 'https://qyapi.weixin.qq.com', on_download_added: false, on_download_complete: true, on_scrape_complete: true, on_error: true, on_cleanup_candidates: true, assistant_chat: true },
    qqbot: { enabled: false, app_id: '', app_secret: '', user_openid: '', group_openid: '', enable_gateway: false, on_download_added: false, on_download_complete: true, on_scrape_complete: true, on_error: true, on_cleanup_candidates: true, assistant_chat: true },
    wechatbot: { enabled: false, webhook_url: '', token: '', enable_claw: false, claw_base_url: 'https://ilinkai.weixin.qq.com', claw_default_target: '', claw_poll_timeout: 25, on_download_added: false, on_download_complete: true, on_scrape_complete: true, on_error: true, on_cleanup_candidates: true, assistant_chat: true }
  },
  assistant: {
    enabled: false,
    provider: { provider: 'openai_compatible', runtime: 'openai_compatible', base_url: '', api_key: '', model: '', temperature: 0.2, timeout_seconds: 60 },
    max_history_messages: 20,
    require_confirm_for_download: true,
    require_confirm_for_delete: true,
    require_confirm_for_apply_tools: true,
    allow_online_download: false,
    allow_library_write: true,
    allow_task_delete: false,
    enabled_tools: []
  }
})
const loading = ref(false)
const saving = ref(false)
const testingQb = ref(false)
const testingTg = ref(false)
const testingNotify = ref('')
const notifyStatus = ref(null)
const notifyRuntimeEvents = ref([])
const refreshingNotifyRuntime = ref(false)
const restartingQqGateway = ref(false)
const qqGatewayStatus = ref(null)
const wechatClawStatus = ref(null)
const wechatClawBusy = ref('')
const testingSite = ref('')
const scheduler = ref([])
const assistantProviders = ref([])
const assistantTools = ref([])
const testingAssistant = ref(false)
const settingsTabs = [
  { key: 'sites', label: 'PT站', icon: '📡', islandIconSrc: animalIslandIcons.chat },
  { key: 'downloader', label: '下载器', icon: '⬇️', islandIconSrc: animalIslandIcons.helicopter },
  { key: 'paths', label: '媒体库/路径', icon: '📁', islandIconSrc: animalIslandIcons.app },
  { key: 'scraper', label: '刮削', icon: '🎵', islandIconSrc: animalIslandIcons.recipes },
  { key: 'automation', label: '自动化', icon: '⏰', islandIconSrc: animalIslandIcons.home },
  { key: 'notify', label: '通知', icon: '📢', islandIconSrc: animalIslandIcons.camera },
  { key: 'assistant', label: '助手', icon: '🤖', islandIconSrc: animalIslandIcons.nook },
  { key: 'security', label: '安全', icon: '🔐', islandIconSrc: animalIslandIcons.system }
]
const activeSettingsTab = ref('sites')
const tabMeta = (key) => settingsTabs.find(tab => tab.key === key) || {}
const islandIconFor = (key) => tabMeta(key).islandIconSrc || ''

// Password change
const pwdForm = ref({ old_password: '', new_username: '', new_password: '' })
const pwdSaving = ref(false)

async function loadAll() {
  loading.value = true
  try {
    const data = await getSettings()
    if (data) {
    // deep merge to avoid overwriting missing keys
    for (const key of Object.keys(settings.value)) {
      if (data[key] !== undefined) {
        settings.value[key] = { ...settings.value[key], ...data[key] }
      }
    }
    }
    scheduler.value = await getScheduler()
    const providerData = await getAssistantProviders()
    assistantProviders.value = providerData.providers || []
    const toolData = await getAssistantTools()
    assistantTools.value = toolData.tools || []
    await loadNotifyRuntime()
    await loadQqGatewayStatus()
    await loadWechatClawStatus(false, false)
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function handleSave() {
  saving.value = true
  try {
    const res = await updateSettings(settings.value)
    if (res?.warnings?.length) {
      alert(`⚠️ 设置已保存\n${res.warnings.join('\n')}`)
    }
  } catch (e) { console.error(e) }
  finally { saving.value = false }
}

async function handleTestQb() {
  testingQb.value = true
  try {
    const res = await testQb()
    alert(res.ok ? '✅ qBittorrent 连接成功' : '❌ 连接失败: ' + (res.message || ''))
  } catch (e) { alert('❌ 连接失败: ' + e.message) }
  finally { testingQb.value = false }
}

async function handleTestSite(name) {
  testingSite.value = name
  try {
    const res = await testSite(name)
    alert(res.ok ? `✅ ${name}: ${res.message}` : `❌ ${name}: ${res.message}`)
  } catch (e) { alert(`❌ ${name}: ` + e.message) }
  finally { testingSite.value = '' }
}

async function handleTestTg() {
  testingTg.value = true
  try {
    const res = await testTelegram()
    alert(res.ok ? 'Telegram 消息发送成功' : '发送失败: ' + (res.message || res.error || ''))
  } catch (e) { alert('发送失败: ' + e.message) }
  finally { testingTg.value = false }
}

async function handleTestNotify(channel) {
  testingNotify.value = channel
  try {
    const res = await testNotifyChannel(channel)
    await loadNotifyRuntime()
    alert(res.ok ? `${channel} 消息发送成功` : `发送失败: ${res.message || res.error || ''}`)
  } catch (e) { alert('发送失败: ' + e.message) }
  finally { testingNotify.value = '' }
}

async function loadNotifyRuntime() {
  refreshingNotifyRuntime.value = true
  try {
    notifyStatus.value = await getNotifyStatus()
    const events = await getNotifyEvents(30)
    notifyRuntimeEvents.value = events.items || []
  } catch (e) { console.warn('load notify runtime failed', e) }
  finally { refreshingNotifyRuntime.value = false }
}

async function loadQqGatewayStatus() {
  try { qqGatewayStatus.value = await getQqbotGatewayStatus() }
  catch (e) { console.warn('load qq gateway failed', e) }
}

async function handleRestartQqGateway() {
  restartingQqGateway.value = true
  try { qqGatewayStatus.value = await restartQqGateway() }
  catch (e) { alert('重启 Gateway 失败: ' + e.message) }
  finally { restartingQqGateway.value = false }
}

async function loadWechatClawStatus(refresh = false, autoQrcode = false) {
  try { wechatClawStatus.value = await getWechatClawStatus(refresh, autoQrcode) }
  catch (e) { console.warn('load wechat claw failed', e) }
}

async function handleWechatClawQrcode() {
  wechatClawBusy.value = 'qrcode'
  try { wechatClawStatus.value = await refreshWechatClawQrcode() }
  catch (e) { alert('获取二维码失败: ' + e.message) }
  finally { wechatClawBusy.value = '' }
}

async function handleWechatClawRefresh() {
  wechatClawBusy.value = 'refresh'
  try { await loadWechatClawStatus(true, false) }
  finally { wechatClawBusy.value = '' }
}

async function handleWechatClawRestart() {
  wechatClawBusy.value = 'restart'
  try { wechatClawStatus.value = await restartWechatClaw() }
  catch (e) { alert('重启轮询失败: ' + e.message) }
  finally { wechatClawBusy.value = '' }
}

async function handleWechatClawLogout() {
  if (!confirm('确认退出微信 Claw 登录？')) return
  wechatClawBusy.value = 'logout'
  try { wechatClawStatus.value = await logoutWechatClaw() }
  finally { wechatClawBusy.value = '' }
}

const notifyEvents = [
  ['on_download_added', '开始下载'],
  ['on_download_complete', '下载完成'],
  ['on_scrape_complete', '刮削完成'],
  ['on_error', '错误告警'],
  ['on_cleanup_candidates', '清理候选提醒'],
  ['assistant_chat', '允许和智能助手对话']
]
const notifyChannelLabels = { telegram: 'Telegram', wecom: '企业微信', qqbot: 'QQBot', wechatbot: '微信 Claw' }

function notifyChannelColor(name, ch) {
  if (ch?.last_error) return 'red'
  if (name === 'qqbot' && ch?.gateway?.running) return 'green'
  if (name === 'wechatbot' && ch?.claw?.connected) return 'green'
  if (ch?.enabled) return 'orange'
  return 'dim'
}

function notifyChannelLabel(name, ch) {
  if (name === 'qqbot' && ch?.gateway?.running) return 'Gateway 运行中'
  if (name === 'wechatbot' && ch?.claw?.connected) return 'Claw 已登录'
  if (ch?.enabled) return '已启用'
  return '未启用'
}

function formatTime(ts) {
  return ts ? new Date(ts).toLocaleString() : '-'
}

function randomSecret(bytes = 24) {
  const arr = new Uint8Array(bytes)
  crypto.getRandomValues(arr)
  return Array.from(arr, b => b.toString(16).padStart(2, '0')).join('')
}

const notifyWebhookToken = computed(() => settings.value.notify.webhook_token || '')
const notifyWebhookTokenReady = computed(() => Boolean(notifyWebhookToken.value) && !notifyWebhookToken.value.includes('***'))
const notifyWebhookBase = computed(() => {
  if (typeof window === 'undefined') return ''
  return `${window.location.origin}/api/notify`
})
const notifyWebhookUrls = computed(() => {
  const token = encodeURIComponent(notifyWebhookToken.value || '<入站密钥>')
  return [
    { key: 'generic', label: '通用入站', desc: '外部代理或自定义脚本推送标准 JSON', url: `${notifyWebhookBase.value}/incoming?token=${token}` },
    { key: 'wecom', label: '企业微信代理模式', desc: '外部已解密/转发时使用；原生企业微信回调见下方说明', url: `${notifyWebhookBase.value}/webhook/wecom?token=${token}` },
    { key: 'qqbot', label: 'QQBot Webhook', desc: 'QQBot HTTP 回调或转发器推送', url: `${notifyWebhookBase.value}/webhook/qqbot?token=${token}` },
    { key: 'wechatbot', label: 'WeChatBot Webhook', desc: 'WeChatBot / iLink / 自建微信转发器推送', url: `${notifyWebhookBase.value}/webhook/wechatbot?token=${token}` },
  ]
})
const wecomNativeCallbackUrl = computed(() => `${notifyWebhookBase.value}/webhook/wecom`)

function generateWebhookToken() {
  settings.value.notify.webhook_token = randomSecret(24)
}

async function copyText(text, label = '内容') {
  try {
    await navigator.clipboard.writeText(text)
    alert(`已复制${label}`)
  } catch (e) {
    window.prompt(`复制${label}`, text)
  }
}

async function handleRunScheduler(id) {
  try { await runScheduler(id) } catch (e) { console.error(e) }
}

function selectedAssistantProvider() {
  return assistantProviders.value.find(p => p.id === settings.value.assistant.provider.provider)
}

function applyAssistantProviderDefaults() {
  const provider = selectedAssistantProvider()
  if (!provider) return
  settings.value.assistant.provider.runtime = provider.runtime || 'openai_compatible'
  settings.value.assistant.provider.base_url = provider.default_base_url || ''
  if (!settings.value.assistant.provider.model && provider.default_model) settings.value.assistant.provider.model = provider.default_model
}

function applyAssistantPreset(presetId) {
  const provider = selectedAssistantProvider()
  const preset = provider?.presets?.find(p => p.id === presetId)
  if (!preset) return
  settings.value.assistant.provider.base_url = preset.base_url
  settings.value.assistant.provider.runtime = preset.runtime || provider.runtime || 'openai_compatible'
}

function activeAssistantTools() {
  const selected = settings.value.assistant.enabled_tools || []
  if (selected.includes('__none__')) return []
  if (!selected.length) return assistantTools.value.map(t => t.name)
  return selected
}

function isAssistantToolEnabled(name) {
  return activeAssistantTools().includes(name)
}

function toggleAssistantTool(name) {
  const all = assistantTools.value.map(t => t.name)
  let selected = activeAssistantTools()
  if (selected.includes(name)) selected = selected.filter(n => n !== name)
  else selected = [...selected, name]
  selected = selected.filter(n => all.includes(n))
  settings.value.assistant.enabled_tools = selected.length ? selected : ['__none__']
}

function selectAllAssistantTools() {
  settings.value.assistant.enabled_tools = assistantTools.value.map(t => t.name)
}

function resetAssistantToolsDefault() {
  settings.value.assistant.enabled_tools = []
}

function riskColor(risk) {
  return risk === 'high' ? 'red' : risk === 'medium' ? 'orange' : 'green'
}

async function handleTestAssistant() {
  testingAssistant.value = true
  try {
    const res = await testAssistantProvider(settings.value.assistant.enabled, settings.value.assistant.provider)
    alert(res.ok ? `✅ 模型测试成功\n${res.reply_preview || ''}\n耗时 ${res.duration_ms || '-'} ms` : `❌ 模型测试失败：${res.message || '未知错误'}`)
  } catch (e) {
    alert('❌ 模型测试失败：' + e.message)
  } finally {
    testingAssistant.value = false
  }
}

async function handleChangePassword() {
  if (!pwdForm.value.old_password) return alert('请输入旧密码')
  pwdSaving.value = true
  try {
    await changePasswordApi(pwdForm.value.old_password, pwdForm.value.new_username, pwdForm.value.new_password)
    alert('密码修改成功')
    pwdForm.value = { old_password: '', new_username: '', new_password: '' }
  } catch (e) { alert('修改失败: ' + e.message) }
  finally { pwdSaving.value = false }
}

function schedulerStatus(s) {
  if (!s.last_run) return { label: '未执行', color: 'dim' }
  const ok = s.last_success !== false
  return { label: ok ? '成功' : '失败', color: ok ? 'green' : 'red' }
}

onMounted(loadAll)
</script>

<template>
  <div class="settings-view">
    <div v-if="loading" class="loading-text">加载中...</div>
    <template v-else>
      <div class="settings-tabs" role="tablist" aria-label="设置分组">
        <button
          v-for="tab in settingsTabs"
          :key="tab.key"
          type="button"
          class="settings-tab"
          :class="{ active: activeSettingsTab === tab.key }"
          role="tab"
          :aria-selected="activeSettingsTab === tab.key"
          @click="activeSettingsTab = tab.key"
        >
          <span class="settings-tab-icon">
            <img v-if="isIsland && tab.islandIconSrc" :src="tab.islandIconSrc" alt="" class="animal-settings-icon" />
            <span v-else>{{ tab.icon }}</span>
          </span>
          <span>{{ tab.label }}</span>
        </button>
      </div>

      <div class="settings-content">
      <!-- PT站配置 -->
      <div v-show="activeSettingsTab === 'sites'" class="settings-section">
        <h3 class="animal-section-title"><img v-if="isIsland" :src="islandIconFor('sites')" alt="" /><span v-else>📡</span><span>PT站配置</span></h3>
        <div class="site-grid">
          <!-- M-Team -->
          <div class="site-card">
            <div class="site-header">
              <span class="site-name">🍚 M-Team 馒头</span>
              <label class="toggle-label"><input type="checkbox" v-model="settings.sites.mteam.enabled" /><span>启用</span></label>
            </div>
            <div v-if="settings.sites.mteam.enabled" class="site-fields">
              <input v-model="settings.sites.mteam.url" placeholder="站点地址 (https://kp.m-team.cc)" />
              <input v-model="settings.sites.mteam.api_key" placeholder="API Key" />
              <input v-model="settings.sites.mteam.token" placeholder="Token (JWT)" />
              <AppButton variant="ghost" size="sm" :loading="testingSite==='mteam'" @click="handleTestSite('mteam')">测试连接</AppButton>
            </div>
          </div>
          <!-- Open.CD -->
          <div class="site-card">
            <div class="site-header">
              <span class="site-name">👑 Open.CD 皇后</span>
              <label class="toggle-label"><input type="checkbox" v-model="settings.sites.opencd.enabled" /><span>启用</span></label>
            </div>
            <div v-if="settings.sites.opencd.enabled" class="site-fields">
              <input v-model="settings.sites.opencd.url" placeholder="站点地址 (https://open.cd)" />
              <input v-model="settings.sites.opencd.cookie" placeholder="Cookie (F12 复制)" />
              <AppButton variant="ghost" size="sm" :loading="testingSite==='opencd'" @click="handleTestSite('opencd')">测试连接</AppButton>
            </div>
          </div>
          <!-- PTClub -->
          <div class="site-card">
            <div class="site-header">
              <span class="site-name">🐱 PTClub 猫站</span>
              <label class="toggle-label"><input type="checkbox" v-model="settings.sites.ptclub.enabled" /><span>启用</span></label>
            </div>
            <div v-if="settings.sites.ptclub.enabled" class="site-fields">
              <input v-model="settings.sites.ptclub.url" placeholder="站点地址" />
              <input v-model="settings.sites.ptclub.cookie" placeholder="Cookie (F12 复制)" />
              <AppButton variant="ghost" size="sm" :loading="testingSite==='ptclub'" @click="handleTestSite('ptclub')">测试连接</AppButton>
            </div>
          </div>
          <!-- Dis.Music -->
          <div class="site-card">
            <div class="site-header">
              <span class="site-name">🐬 Dic.Music 海豚</span>
              <label class="toggle-label"><input type="checkbox" v-model="settings.sites.dismusic.enabled" /><span>启用</span></label>
            </div>
            <div v-if="settings.sites.dismusic.enabled" class="site-fields">
              <input v-model="settings.sites.dismusic.url" placeholder="站点地址" />
              <input v-model="settings.sites.dismusic.cookie" placeholder="Cookie (F12 复制)" />
              <AppButton variant="ghost" size="sm" :loading="testingSite==='dismusic'" @click="handleTestSite('dismusic')">测试连接</AppButton>
            </div>
          </div>
        </div>
      </div>

      <!-- qBittorrent -->
      <div v-show="activeSettingsTab === 'downloader'" class="settings-section">
        <h3 class="animal-section-title"><img v-if="isIsland" :src="islandIconFor('downloader')" alt="" /><span v-else>⬇️</span><span>qBittorrent</span></h3>
        <div class="fields-row">
          <div class="field flex-1">
            <label>地址</label>
            <input v-model="settings.qbittorrent.host" placeholder="http://localhost:8080" />
          </div>
          <div class="field">
            <label>用户名</label>
            <input v-model="settings.qbittorrent.username" />
          </div>
          <div class="field">
            <label>密码</label>
            <input v-model="settings.qbittorrent.password" type="password" />
          </div>
        </div>
        <div class="fields-row">
          <div class="field">
            <label>分类</label>
            <input v-model="settings.qbittorrent.category" placeholder="music" />
          </div>
          <div class="field flex-1">
            <label>保存路径</label>
            <input v-model="settings.qbittorrent.save_path" placeholder="/downloads/music" />
          </div>
          <div class="field">
            <label>Tag</label>
            <input v-model="settings.qbittorrent.tag" placeholder="music-sub" />
          </div>
          <AppButton variant="ghost" size="sm" :loading="testingQb" @click="handleTestQb">测试连接</AppButton>
        </div>
      </div>

      <!-- 路径配置 -->
      <div v-show="activeSettingsTab === 'paths'" class="settings-section">
        <h3 class="animal-section-title"><img v-if="isIsland" :src="islandIconFor('paths')" alt="" /><span v-else>📁</span><span>路径配置</span></h3>
        <div class="fields-row">
          <div class="field flex-1">
            <label>音乐库目录</label>
            <input v-model="settings.paths.library" placeholder="/music" />
          </div>
          <div class="field flex-1">
            <label>下载目录</label>
            <input v-model="settings.paths.downloads" placeholder="/downloads/music" />
          </div>
          <div class="field flex-1">
            <label>目录结构</label>
            <input v-model="settings.paths.structure" placeholder="{artist}/{album}" />
          </div>
        </div>
      </div>

      <!-- 刮削配置 -->
      <div v-show="activeSettingsTab === 'scraper'" class="settings-section">
        <h3 class="animal-section-title"><img v-if="isIsland" :src="islandIconFor('scraper')" alt="" /><span v-else>🎵</span><span>刮削配置</span></h3>
        <div class="toggle-list">
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.embed_cover" /><span>嵌入封面到音频标签</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.save_cover_file" /><span>保存 cover.jpg 到专辑目录</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.save_lyrics" /><span>保存歌词</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.save_nfo" /><span>生成 album.nfo (Kodi/Jellyfin)</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.rename_file" /><span>按模板重命名文件</span></label>
          <div class="field">
            <label>写标签策略</label>
            <select v-model="settings.scraper.tag_write_mode">
              <option value="fill_missing">补全缺失字段（推荐）</option>
              <option value="skip_existing">已有标题和艺人则跳过</option>
              <option value="overwrite">覆盖全部字段</option>
            </select>
          </div>
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.break_hardlink_before_tag" /><span>写标签前断开硬链接（保护 PT 做种文件）</span></label>
        </div>
      </div>

      <!-- 定时任务 -->
      <div v-show="activeSettingsTab === 'automation'" class="settings-section">
        <h3 class="animal-section-title"><img v-if="isIsland" :src="islandIconFor('automation')" alt="" /><span v-else>⏰</span><span>定时任务</span></h3>
        <div class="fields-row" style="margin-bottom:16px">
          <div class="field">
            <label>搜索间隔(分钟)</label>
            <input type="number" v-model.number="settings.scheduler.search_interval_minutes" style="width:100px" />
          </div>
          <div class="field">
            <label>完成检查间隔(分钟)</label>
            <input type="number" v-model.number="settings.scheduler.check_complete_interval_minutes" style="width:100px" />
          </div>
          <div class="field">
            <label>清理扫描间隔(小时)</label>
            <input type="number" v-model.number="settings.scheduler.cleanup_scan_interval_hours" style="width:100px" min="1" />
          </div>
          <label class="toggle-item" style="padding-bottom:8px"><input type="checkbox" v-model="settings.scheduler.cleanup_scan_enabled" /><span>启用自动清理扫描</span></label>
        </div>
        <div class="scheduler-list">
          <div v-for="s in scheduler" :key="s.id" class="scheduler-row">
            <div class="scheduler-info">
              <span class="scheduler-name">{{ s.name }}</span>
              <span class="scheduler-meta text-dim">下次: {{ s.next_run ? new Date(s.next_run).toLocaleString() : '-' }}</span>
            </div>
            <AppBadge :color="schedulerStatus(s).color">{{ schedulerStatus(s).label }}</AppBadge>
            <AppButton variant="ghost" size="sm" @click="handleRunScheduler(s.id)">立即执行</AppButton>
          </div>
        </div>
      </div>

      <!-- 通知 -->
      <div v-show="activeSettingsTab === 'notify'" class="settings-section">
        <h3 class="animal-section-title"><img v-if="isIsland" :src="islandIconFor('notify')" alt="" /><span v-else>📢</span><span>通知与消息入口</span></h3>
        <div class="notify-webhook-panel">
          <div class="notify-webhook-head">
            <div>
              <strong>入站 Webhook 密钥</strong>
              <div class="text-dim">用于保护 Music Sub 的外部消息入口。外部系统调用 /api/notify/webhook/... 或 /api/notify/incoming 时必须带 <code>?token=密钥</code>。</div>
            </div>
            <AppButton variant="ghost" size="sm" @click="generateWebhookToken">生成密钥</AppButton>
          </div>
          <div class="fields-row">
            <div class="field flex-1">
              <label>密钥</label>
              <input v-model="settings.notify.webhook_token" type="password" placeholder="建议点击生成；不是 Telegram Bot Token / 企业微信 Token" />
              <small class="text-dim">这个密钥只属于 Music Sub，用来校验入站消息。保存设置后才会生效。</small>
            </div>
            <AppButton variant="ghost" size="sm" :disabled="!notifyWebhookToken" @click="copyText(notifyWebhookToken, '入站密钥')">复制密钥</AppButton>
          </div>
          <div class="webhook-url-list">
            <div v-for="item in notifyWebhookUrls" :key="item.key" class="webhook-url-row">
              <div class="webhook-url-main">
                <strong>{{ item.label }}</strong>
                <small>{{ item.desc }}</small>
                <code>{{ item.url }}</code>
              </div>
              <AppButton variant="ghost" size="sm" :disabled="!notifyWebhookToken" @click="copyText(item.url, item.label + '地址')">复制地址</AppButton>
            </div>
          </div>
          <div class="webhook-help-grid">
            <div class="webhook-help-card">
              <strong>标准 JSON 示例</strong>
              <code>{"channel":"telegram","text":"帮我看看下载状态","user_id":"rey"}</code>
              <small>适合自建脚本、n8n、青龙、Webhook 转发器等。</small>
            </div>
            <div class="webhook-help-card">
              <strong>企业微信原生回调</strong>
              <code>{{ wecomNativeCallbackUrl }}</code>
              <small>企业微信后台配置的是这个地址；它使用下方“回调 Token / EncodingAESKey / Corp ID”验签解密，不使用上面的入站密钥。</small>
            </div>
          </div>
          <div v-if="!notifyWebhookTokenReady" class="webhook-warning">提示：当前密钥为空或为已脱敏显示。复制真实入站地址前，建议点击“生成密钥”并保存设置。</div>
        </div>

        <div class="notify-runtime-panel">
          <div class="notify-runtime-head">
            <div>
              <strong>运行状态</strong>
              <div class="text-dim">最近入站 / 出站 / 错误，方便调试 Gateway、企业微信回调和微信 Claw。</div>
            </div>
            <AppButton variant="ghost" size="sm" :loading="refreshingNotifyRuntime" @click="loadNotifyRuntime">刷新</AppButton>
          </div>
          <div class="notify-status-grid">
            <div v-for="(ch, name) in notifyStatus?.channels || {}" :key="name" class="notify-status-card">
              <div class="notify-status-title">
                <span>{{ notifyChannelLabels[name] || name }}</span>
                <AppBadge :color="notifyChannelColor(name, ch)">{{ notifyChannelLabel(name, ch) }}</AppBadge>
              </div>
              <small>入站：{{ ch.last_inbound?.text_preview || '-' }}</small>
              <small>出站：{{ ch.last_outbound?.status || '-' }} · {{ ch.last_outbound?.message || ch.last_outbound?.text_preview || '-' }}</small>
              <small v-if="ch.last_error" class="notify-error">错误：{{ ch.last_error.message || ch.last_error.text_preview }}</small>
            </div>
          </div>
          <div class="notify-event-list">
            <div v-for="ev in notifyRuntimeEvents" :key="ev.id" class="notify-event-row" :class="ev.status">
              <span class="notify-event-meta">{{ formatTime(ev.created_at) }} · {{ ev.channel }} · {{ ev.direction }}</span>
              <span class="notify-event-text">{{ ev.text_preview || ev.message || '-' }}</span>
              <AppBadge :color="ev.status === 'error' ? 'red' : (ev.status === 'ignored' ? 'orange' : 'green')">{{ ev.status }}</AppBadge>
            </div>
            <div v-if="!notifyRuntimeEvents.length" class="text-dim">暂无通知事件。</div>
          </div>
        </div>

        <div class="notify-channel-card">
          <div class="notify-channel-head">
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.telegram.enabled" /><span>Telegram</span></label>
            <AppButton variant="ghost" size="sm" :loading="testingTg" @click="handleTestTg">测试发送</AppButton>
          </div>
          <div class="fields-row" v-if="settings.notify.telegram.enabled">
            <div class="field flex-1"><label>Bot Token</label><input v-model="settings.notify.telegram.bot_token" placeholder="123456:ABC-DEF..." /></div>
            <div class="field flex-1"><label>Chat ID</label><input v-model="settings.notify.telegram.chat_id" placeholder="-100... 或 user id" /></div>
          </div>
          <div class="toggle-list compact"><label v-for="ev in notifyEvents" :key="'tg-' + ev[0]" class="toggle-item"><input type="checkbox" v-model="settings.notify.telegram[ev[0]]" /><span>{{ ev[1] }}</span></label></div>
        </div>

        <div class="notify-channel-card">
          <div class="notify-channel-head">
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.wecom.enabled" /><span>企业微信应用</span></label>
            <AppButton variant="ghost" size="sm" :loading="testingNotify === 'wecom'" @click="handleTestNotify('wecom')">测试发送</AppButton>
          </div>
          <div class="fields-row" v-if="settings.notify.wecom.enabled">
            <div class="field flex-1"><label>Corp ID</label><input v-model="settings.notify.wecom.corp_id" /></div>
            <div class="field flex-1"><label>Agent ID</label><input v-model="settings.notify.wecom.agent_id" /></div>
            <div class="field flex-1"><label>App Secret</label><input v-model="settings.notify.wecom.app_secret" type="password" /></div>
            <div class="field flex-1"><label>ToUser</label><input v-model="settings.notify.wecom.to_user" placeholder="@all / UserID" /></div>
            <div class="field flex-1"><label>回调 Token</label><input v-model="settings.notify.wecom.token" type="password" placeholder="企业微信后台设置的 Token" /></div>
            <div class="field flex-1"><label>EncodingAESKey</label><input v-model="settings.notify.wecom.encoding_aes_key" type="password" placeholder="43 位 EncodingAESKey" /></div>
          </div>
          <div class="toggle-list compact"><label v-for="ev in notifyEvents" :key="'wc-' + ev[0]" class="toggle-item"><input type="checkbox" v-model="settings.notify.wecom[ev[0]]" /><span>{{ ev[1] }}</span></label></div>
        </div>

        <div class="notify-channel-card">
          <div class="notify-channel-head">
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.qqbot.enabled" /><span>QQBot</span></label>
            <AppButton variant="ghost" size="sm" :loading="testingNotify === 'qqbot'" @click="handleTestNotify('qqbot')">测试发送</AppButton>
          </div>
          <div class="fields-row" v-if="settings.notify.qqbot.enabled">
            <div class="field flex-1"><label>App ID</label><input v-model="settings.notify.qqbot.app_id" /></div>
            <div class="field flex-1"><label>App Secret</label><input v-model="settings.notify.qqbot.app_secret" type="password" /></div>
            <div class="field flex-1"><label>User OpenID</label><input v-model="settings.notify.qqbot.user_openid" /></div>
            <div class="field flex-1"><label>Group OpenID</label><input v-model="settings.notify.qqbot.group_openid" /></div>
          </div>
          <div class="gateway-row">
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.qqbot.enable_gateway" /><span>启用 QQBot Gateway 长连接收消息</span></label>
            <AppBadge :color="qqGatewayStatus?.running ? 'green' : (qqGatewayStatus?.enabled ? 'orange' : 'dim')">{{ qqGatewayStatus?.running ? '运行中' : (qqGatewayStatus?.enabled ? '未运行' : '未启用') }}</AppBadge>
            <AppButton variant="ghost" size="sm" :loading="restartingQqGateway" @click="handleRestartQqGateway">重启 Gateway</AppButton>
          </div>
          <div class="toggle-list compact"><label v-for="ev in notifyEvents" :key="'qq-' + ev[0]" class="toggle-item"><input type="checkbox" v-model="settings.notify.qqbot[ev[0]]" /><span>{{ ev[1] }}</span></label></div>
        </div>

        <div class="notify-channel-card">
          <div class="notify-channel-head">
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.wechatbot.enabled" /><span>WeChatBot / WeichatBot Webhook</span></label>
            <AppButton variant="ghost" size="sm" :loading="testingNotify === 'wechatbot'" @click="handleTestNotify('wechatbot')">测试发送</AppButton>
          </div>
          <div class="fields-row" v-if="settings.notify.wechatbot.enabled">
            <div class="field flex-1"><label>Webhook URL（兼容旧模式）</label><input v-model="settings.notify.wechatbot.webhook_url" placeholder="http://.../send" /></div>
            <div class="field flex-1"><label>Token</label><input v-model="settings.notify.wechatbot.token" type="password" /></div>
            <div class="field flex-1"><label>Claw Base URL</label><input v-model="settings.notify.wechatbot.claw_base_url" placeholder="https://ilinkai.weixin.qq.com" /></div>
            <div class="field flex-1"><label>默认目标</label><input v-model="settings.notify.wechatbot.claw_default_target" placeholder="wxid / user_id，可空" /></div>
            <div class="field flex-1"><label>轮询超时</label><input v-model.number="settings.notify.wechatbot.claw_poll_timeout" type="number" min="10" max="120" /></div>
          </div>
          <div class="gateway-row">
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.wechatbot.enable_claw" /><span>启用微信 Claw/iLink 登录与轮询</span></label>
            <AppBadge :color="wechatClawStatus?.connected ? 'green' : (wechatClawStatus?.enabled ? 'orange' : 'dim')">{{ wechatClawStatus?.connected ? '已登录' : (wechatClawStatus?.enabled ? '待登录' : '未启用') }}</AppBadge>
            <AppButton variant="ghost" size="sm" :loading="wechatClawBusy === 'qrcode'" @click="handleWechatClawQrcode">获取二维码</AppButton>
            <AppButton variant="ghost" size="sm" :loading="wechatClawBusy === 'refresh'" @click="handleWechatClawRefresh">刷新状态</AppButton>
            <AppButton variant="ghost" size="sm" :loading="wechatClawBusy === 'restart'" @click="handleWechatClawRestart">重启轮询</AppButton>
            <AppButton variant="ghost" size="sm" :loading="wechatClawBusy === 'logout'" @click="handleWechatClawLogout">退出登录</AppButton>
          </div>
          <div v-if="wechatClawStatus?.qrcode_url" class="wechat-qrcode-box">
            <img v-if="wechatClawStatus.qrcode_url.startsWith('data:image') || wechatClawStatus.qrcode_url.startsWith('http')" :src="wechatClawStatus.qrcode_url" />
            <code>{{ wechatClawStatus.qrcode_url }}</code>
            <small>状态：{{ wechatClawStatus.qrcode_status || '-' }} · Account：{{ wechatClawStatus.account_id || '-' }}</small>
          </div>
          <div class="toggle-list compact"><label v-for="ev in notifyEvents" :key="'wb-' + ev[0]" class="toggle-item"><input type="checkbox" v-model="settings.notify.wechatbot[ev[0]]" /><span>{{ ev[1] }}</span></label></div>
        </div>
      </div>

      <!-- 智能助手 -->
      <div v-show="activeSettingsTab === 'assistant'" class="settings-section">
        <h3 class="animal-section-title"><img v-if="isIsland" :src="islandIconFor('assistant')" alt="" /><span v-else>🤖</span><span>智能助手</span></h3>
        <label class="toggle-item" style="margin-bottom:12px"><input type="checkbox" v-model="settings.assistant.enabled" /><span>启用智能助手</span></label>
        <div class="fields-grid">
          <div class="field">
            <label>Provider</label>
            <select v-model="settings.assistant.provider.provider" @change="applyAssistantProviderDefaults">
              <option v-for="p in assistantProviders" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <small class="text-dim">{{ selectedAssistantProvider()?.hint }}</small>
          </div>
          <div class="field" v-if="selectedAssistantProvider()?.presets?.length">
            <label>Base URL 预设</label>
            <select @change="applyAssistantPreset($event.target.value)">
              <option value="">选择预设...</option>
              <option v-for="p in selectedAssistantProvider()?.presets || []" :key="p.id" :value="p.id">{{ p.label }}</option>
            </select>
          </div>
          <div class="field">
            <label>Runtime</label>
            <select v-model="settings.assistant.provider.runtime">
              <option value="openai_compatible">OpenAI Compatible</option>
              <option value="anthropic_compatible">Anthropic Compatible</option>
            </select>
          </div>
          <div class="field">
            <label>Base URL</label>
            <input v-model="settings.assistant.provider.base_url" placeholder="http://localhost:8180/v1" />
          </div>
          <div class="field">
            <label>API Key</label>
            <input v-model="settings.assistant.provider.api_key" type="password" placeholder="sk-..." />
          </div>
          <div class="field">
            <label>Model</label>
            <input v-model="settings.assistant.provider.model" placeholder="gpt-4o-mini / claude..." />
          </div>
          <div class="field">
            <label>Temperature</label>
            <input v-model.number="settings.assistant.provider.temperature" type="number" min="0" max="2" step="0.1" />
          </div>
          <div class="field">
            <label>超时秒数</label>
            <input v-model.number="settings.assistant.provider.timeout_seconds" type="number" min="10" max="300" />
          </div>
        </div>
        <div style="margin-top:12px">
          <AppButton variant="ghost" size="sm" :loading="testingAssistant" @click="handleTestAssistant">测试模型调用</AppButton>
        </div>
        <div class="toggle-list" style="margin-top:12px">
          <label class="toggle-item"><input type="checkbox" v-model="settings.assistant.require_confirm_for_download" /><span>下载前需要确认</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.assistant.require_confirm_for_delete" /><span>删除前需要确认</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.assistant.require_confirm_for_apply_tools" /><span>中高风险工具需要确认</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.assistant.allow_online_download" /><span>允许在线音乐下载工具</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.assistant.allow_library_write" /><span>允许音乐库写入工具</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.assistant.allow_task_delete" /><span>允许任务删除工具</span></label>
        </div>
        <div class="assistant-tools-box">
          <div class="assistant-tools-head">
            <div>
              <strong>助手工具开关</strong>
              <div class="text-dim">控制哪些工具会暴露给模型。默认模式为全部启用。</div>
            </div>
            <div class="header-actions">
              <AppButton variant="ghost" size="sm" @click="selectAllAssistantTools">全选</AppButton>
              <AppButton variant="ghost" size="sm" @click="resetAssistantToolsDefault">恢复默认</AppButton>
            </div>
          </div>
          <div class="assistant-tool-grid">
            <label v-for="tool in assistantTools" :key="tool.name" class="assistant-tool-item" :class="{ disabled: !isAssistantToolEnabled(tool.name) }">
              <input type="checkbox" :checked="isAssistantToolEnabled(tool.name)" @change="toggleAssistantTool(tool.name)" />
              <span class="assistant-tool-main">
                <span class="assistant-tool-name">{{ tool.name }}</span>
                <small>{{ tool.group }} · {{ tool.description }}</small>
              </span>
              <AppBadge :color="riskColor(tool.risk)">{{ tool.risk }}</AppBadge>
            </label>
          </div>
        </div>
      </div>

      <!-- 账号安全 -->
      <div v-show="activeSettingsTab === 'security'" class="settings-section">
        <h3 class="animal-section-title"><img v-if="isIsland" :src="islandIconFor('security')" alt="" /><span v-else>🔐</span><span>账号安全</span></h3>
        <div class="pwd-form">
          <input v-model="pwdForm.old_password" type="password" placeholder="旧密码" />
          <input v-model="pwdForm.new_username" placeholder="新用户名（可选）" />
          <input v-model="pwdForm.new_password" type="password" placeholder="新密码" />
          <AppButton variant="primary" size="sm" :loading="pwdSaving" @click="handleChangePassword">修改密码</AppButton>
        </div>
      </div>
      </div>

      <!-- 保存按钮 -->
      <div class="save-bar">
        <AppButton variant="primary" :loading="saving" @click="handleSave">保存设置</AppButton>
      </div>

    </template>
  </div>
</template>

<style scoped>
.animal-section-title { display: inline-flex; align-items: center; gap: 8px; }
.animal-section-title img { width: 26px; height: 26px; object-fit: contain; filter: drop-shadow(0 2px 1px rgba(61, 52, 40, .14)); }
.settings-view { height: 100%; min-height: 0; padding: 24px; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; gap: 16px; overflow: hidden; }
.loading-text { color: var(--text-dim); padding: 20px 0; }
.settings-tabs { display: flex; gap: 8px; overflow-x: auto; overflow-y: visible; padding: 4px 4px 10px; margin: -4px -4px 0; scrollbar-width: none; -webkit-overflow-scrolling: touch; align-items: center; min-height: 52px; flex-shrink: 0; }
.settings-tabs::-webkit-scrollbar { display: none; }
.settings-tab { flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 38px; border: 1px solid var(--border); border-radius: 999px; padding: 9px 14px; color: var(--text-dim); background: var(--surface); font-size: 14px; font-weight: 600; cursor: pointer; transition: all .15s ease; white-space: nowrap; overflow: visible; }
.settings-tab:hover { color: var(--text); border-color: var(--accent); }
.settings-tab.active { color: var(--accent); border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, var(--surface)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent); }
.settings-tab-icon { font-size: 15px; }
.settings-content { min-height: 0; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 16px; padding-right: 4px; }
.settings-section { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px; display: flex; flex-direction: column; gap: 14px; flex-shrink: 0; }
.settings-section h3 { font-size: 16px; font-weight: 600; }
.site-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.site-card { background: var(--surface-hover); border-radius: var(--radius-md); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.site-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.site-name { font-size: 14px; font-weight: 700; letter-spacing: 0.5px; }
.toggle-label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; }
.toggle-label input { accent-color: var(--accent); }
.site-fields { display: flex; flex-direction: column; gap: 8px; }
.site-fields input { font-size: 13px; min-width: 0; }
.fields-row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.field.flex-1 { flex: 1; min-width: 160px; }
.field label { font-size: 12px; color: var(--text-dim); }
.field input, .field select { min-width: 0; }
.field small { line-height: 1.45; }
.toggle-list { display: flex; flex-direction: column; gap: 8px; }
.toggle-list.compact { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
.toggle-item { display: flex; align-items: flex-start; gap: 8px; cursor: pointer; font-size: 14px; line-height: 1.35; }
.notify-webhook-panel { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface-hover); padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.notify-webhook-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.notify-webhook-head code { font-size: 12px; color: var(--accent); }
.webhook-url-list { display: flex; flex-direction: column; gap: 8px; }
.webhook-url-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: center; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); padding: 10px; }
.webhook-url-main { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.webhook-url-main small, .webhook-help-card small { color: var(--text-dim); line-height: 1.4; }
.webhook-url-main code, .webhook-help-card code { display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); background: var(--surface-soft); border-radius: var(--radius-sm); padding: 6px 8px; font-size: 12px; }
.webhook-help-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.webhook-help-card { border: 1px dashed var(--border); border-radius: var(--radius-md); padding: 10px; background: var(--surface); display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.webhook-warning { color: #b45309; background: color-mix(in srgb, #f59e0b 14%, transparent); border: 1px solid color-mix(in srgb, #f59e0b 35%, var(--border)); border-radius: var(--radius-md); padding: 9px 10px; font-size: 13px; }
.notify-runtime-panel { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface-hover); padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.notify-runtime-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.notify-status-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.notify-status-card { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); padding: 10px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.notify-status-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-weight: 700; }
.notify-status-card small { color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notify-error { color: var(--danger, #ef4444) !important; }
.notify-event-list { display: flex; flex-direction: column; gap: 6px; max-height: 240px; overflow: auto; }
.notify-event-row { display: grid; grid-template-columns: 220px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 8px 10px; border-radius: var(--radius-md); background: var(--surface); border: 1px solid var(--border); }
.notify-event-row.error { border-color: color-mix(in srgb, #ef4444 35%, var(--border)); }
.notify-event-meta { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.notify-event-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.notify-channel-card { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); padding: 14px; margin-top: 12px; }
.notify-channel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.gateway-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; padding: 10px; border: 1px dashed var(--border); border-radius: var(--radius-md); background: var(--surface-soft); }
.wechat-qrcode-box { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; padding: 10px; border-radius: var(--radius-md); background: var(--surface-soft); }
.wechat-qrcode-box img { width: 132px; height: 132px; object-fit: contain; border-radius: var(--radius-sm); background: #fff; }
.wechat-qrcode-box code { max-width: 520px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-dim); }
.wechat-qrcode-box small { color: var(--text-muted); }
.toggle-item input { flex: 0 0 auto; margin-top: 2px; accent-color: var(--accent); }
.toggle-item span { min-width: 0; }
.scheduler-list { display: flex; flex-direction: column; gap: 8px; }
.scheduler-row { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: var(--radius-md); background: var(--surface-hover); }
.scheduler-info { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.scheduler-name { font-size: 14px; font-weight: 500; }
.scheduler-meta { font-size: 12px; }
.pwd-form { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.pwd-form input { flex: 1; min-width: 160px; }
.save-bar { z-index: 6; background: color-mix(in srgb, var(--bg) 94%, transparent); padding: 12px 0 0; border-top: 1px solid var(--border); display: flex; justify-content: flex-end; backdrop-filter: blur(max(14px, var(--blur-strength))); -webkit-backdrop-filter: blur(max(14px, var(--blur-strength))); flex-shrink: 0; }
.fields-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.assistant-tools-box { margin-top: 14px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; background: var(--surface-hover); display: flex; flex-direction: column; gap: 12px; }
.assistant-tools-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.assistant-tools-head > div:first-child { min-width: 0; }
.assistant-tool-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.assistant-tool-item { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; gap: 8px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 9px 10px; background: var(--surface); cursor: pointer; min-width: 0; height: auto; }
.assistant-tool-item input { flex: 0 0 auto; margin-top: 2px; accent-color: var(--accent); }
.assistant-tool-item :deep(.badge), .assistant-tool-item .badge { flex: 0 0 auto; justify-self: end; max-width: 76px; margin-top: 0; }
.assistant-tool-item.disabled { opacity: .55; }
.assistant-tool-main { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.assistant-tool-name { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.assistant-tool-main small { color: var(--text-dim); white-space: normal; overflow-wrap: anywhere; word-break: break-word; line-height: 1.35; }

@media (max-width: 768px) {
  .settings-view {
    padding: 14px !important;
    padding-bottom: var(--mobile-page-bottom, 70px) !important;
    gap: 14px;
  }
  .settings-tabs {
    position: sticky;
    top: 0;
    z-index: 7;
    min-height: 50px;
    background: linear-gradient(to bottom, color-mix(in srgb, var(--bg) 98%, transparent), color-mix(in srgb, var(--bg) 90%, transparent));
    padding: 7px 14px 9px;
    margin: -14px -14px 2px;
    scroll-padding-inline: 14px;
    mask-image: linear-gradient(90deg, transparent 0, #000 14px, #000 calc(100% - 28px), transparent 100%);
    backdrop-filter: blur(max(14px, var(--blur-strength)));
    -webkit-backdrop-filter: blur(max(14px, var(--blur-strength)));
  }
  .settings-tab { min-height: 34px; padding: 7px 11px; font-size: 13px; }
  .settings-section { padding: 14px; border-radius: 16px; gap: 12px; }
  .settings-section h3 { font-size: 15px; }
  .site-grid, .fields-grid, .assistant-tool-grid, .notify-status-grid { grid-template-columns: 1fr; gap: 10px; }
  .site-card { padding: 12px; gap: 10px; }
  .site-header { align-items: center; flex-direction: row; }
  .site-name { min-width: 0; font-size: 13px; line-height: 1.25; }
  .toggle-label { flex-shrink: 0; min-height: 28px; padding: 2px 0; }
  .site-fields { gap: 9px; }
  .site-fields input { width: 100%; min-height: 40px; font-size: 16px; overflow: hidden; text-overflow: ellipsis; }
  .site-fields :deep(.btn), .fields-row :deep(.btn), .pwd-form :deep(.btn) { width: 100%; justify-content: center; }
  .fields-row { flex-direction: column; align-items: stretch; gap: 10px; }
  .field, .field.flex-1 { min-width: 0; width: 100%; }
  .field input, .field select { width: 100%; min-height: 42px; font-size: 16px; }
  .field small { display: block; margin-top: 2px; }
  .assistant-tools-box { margin-top: 8px; padding: 12px; border-radius: 16px; overflow: hidden; }
  .assistant-tools-head { align-items: stretch; flex-direction: column; }
  .header-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .header-actions :deep(.btn) { width: 100%; justify-content: center; min-width: 0; }
  .assistant-tool-item { grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; padding: 10px; }
  .assistant-tool-item input { margin-top: 2px; }
  .assistant-tool-item :deep(.badge), .assistant-tool-item .badge { margin-top: 0; }
  .assistant-tool-name { white-space: normal; overflow-wrap: anywhere; line-height: 1.25; }
  .assistant-tool-main small { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .pwd-form { flex-direction: column; align-items: stretch; }
  .pwd-form input { min-width: unset; width: 100%; }
  .scheduler-row { flex-direction: column; align-items: stretch; gap: 8px; }
  .notify-webhook-head, .notify-runtime-head { flex-direction: column; align-items: stretch; }
  .webhook-url-row { grid-template-columns: 1fr; }
  .webhook-help-grid { grid-template-columns: 1fr; }
  .notify-event-row { grid-template-columns: 1fr auto; gap: 6px; }
  .notify-event-meta { grid-column: 1 / -1; white-space: normal; }
  .notify-event-text { white-space: normal; }
  .save-bar {
    position: static;
    margin: 0;
    padding: 12px;
    justify-content: stretch;
    border: 1px solid var(--border);
    border-radius: 16px;
    background: var(--surface);
  }
  .save-bar button { width: 100%; min-height: 42px; }
}

@media (max-width: 430px) {
  .settings-view {
    padding: 12px !important;
    padding-bottom: var(--mobile-page-bottom, 62px) !important;
  }
  .settings-tabs {
    margin: -12px -12px 2px;
    padding-left: 12px;
    padding-right: 12px;
    scroll-padding-inline: 12px;
  }
  .settings-section { padding: 12px; }
  .save-bar {
    margin-left: 0;
    margin-right: 0;
    margin-bottom: 0;
    padding-left: 12px;
    padding-right: 12px;
  }
}
</style>