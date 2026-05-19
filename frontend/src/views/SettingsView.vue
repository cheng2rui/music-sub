<script setup>
import { ref, onMounted } from 'vue'
import { getSettings, updateSettings, testQb, testTelegram, testNotifyChannel, testSite, getScheduler, runScheduler, changePasswordApi, getAssistantProviders, getAssistantTools, testAssistantProvider } from '@/api/index.js'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'

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
    qqbot: { enabled: false, app_id: '', app_secret: '', user_openid: '', group_openid: '', on_download_added: false, on_download_complete: true, on_scrape_complete: true, on_error: true, on_cleanup_candidates: true, assistant_chat: true },
    wechatbot: { enabled: false, webhook_url: '', token: '', on_download_added: false, on_download_complete: true, on_scrape_complete: true, on_error: true, on_cleanup_candidates: true, assistant_chat: true }
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
const testingSite = ref('')
const scheduler = ref([])
const assistantProviders = ref([])
const assistantTools = ref([])
const testingAssistant = ref(false)
const settingsTabs = [
  { key: 'sites', label: 'PT站', icon: '📡' },
  { key: 'downloader', label: '下载器', icon: '⬇️' },
  { key: 'paths', label: '媒体库/路径', icon: '📁' },
  { key: 'scraper', label: '刮削', icon: '🎵' },
  { key: 'automation', label: '自动化', icon: '⏰' },
  { key: 'notify', label: '通知', icon: '📢' },
  { key: 'assistant', label: '助手', icon: '🤖' },
  { key: 'security', label: '安全', icon: '🔐' }
]
const activeSettingsTab = ref('sites')

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
    alert(res.ok ? `${channel} 消息发送成功` : `发送失败: ${res.message || res.error || ''}`)
  } catch (e) { alert('发送失败: ' + e.message) }
  finally { testingNotify.value = '' }
}

const notifyEvents = [
  ['on_download_added', '开始下载'],
  ['on_download_complete', '下载完成'],
  ['on_scrape_complete', '刮削完成'],
  ['on_error', '错误告警'],
  ['on_cleanup_candidates', '清理候选提醒'],
  ['assistant_chat', '允许和智能助手对话']
]

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
          <span class="settings-tab-icon">{{ tab.icon }}</span>
          <span>{{ tab.label }}</span>
        </button>
      </div>

      <!-- PT站配置 -->
      <div v-show="activeSettingsTab === 'sites'" class="settings-section">
        <h3>📡 PT站配置</h3>
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
        <h3>⬇️ qBittorrent</h3>
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
        <h3>📁 路径配置</h3>
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
        <h3>🎵 刮削配置</h3>
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
        <h3>⏰ 定时任务</h3>
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
        <h3>📢 通知与消息入口</h3>
        <div class="field" style="margin-bottom:14px">
          <label>Webhook Token（入站消息校验）</label>
          <input v-model="settings.notify.webhook_token" placeholder="必填；/api/notify/webhook/... 必须带 ?token=" />
          <small class="text-dim">入站地址：/api/notify/webhook/wecom、/api/notify/webhook/qqbot、/api/notify/webhook/wechatbot。未配置 token 时拒绝入站。</small>
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
          <div class="toggle-list compact"><label v-for="ev in notifyEvents" :key="'qq-' + ev[0]" class="toggle-item"><input type="checkbox" v-model="settings.notify.qqbot[ev[0]]" /><span>{{ ev[1] }}</span></label></div>
        </div>

        <div class="notify-channel-card">
          <div class="notify-channel-head">
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.wechatbot.enabled" /><span>WeChatBot / WeichatBot Webhook</span></label>
            <AppButton variant="ghost" size="sm" :loading="testingNotify === 'wechatbot'" @click="handleTestNotify('wechatbot')">测试发送</AppButton>
          </div>
          <div class="fields-row" v-if="settings.notify.wechatbot.enabled">
            <div class="field flex-1"><label>Webhook URL</label><input v-model="settings.notify.wechatbot.webhook_url" placeholder="http://.../send" /></div>
            <div class="field flex-1"><label>Token</label><input v-model="settings.notify.wechatbot.token" type="password" /></div>
          </div>
          <div class="toggle-list compact"><label v-for="ev in notifyEvents" :key="'wb-' + ev[0]" class="toggle-item"><input type="checkbox" v-model="settings.notify.wechatbot[ev[0]]" /><span>{{ ev[1] }}</span></label></div>
        </div>
      </div>

      <!-- 智能助手 -->
      <div v-show="activeSettingsTab === 'assistant'" class="settings-section">
        <h3>🤖 智能助手</h3>
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
        <h3>账号安全</h3>
        <div class="pwd-form">
          <input v-model="pwdForm.old_password" type="password" placeholder="旧密码" />
          <input v-model="pwdForm.new_username" placeholder="新用户名（可选）" />
          <input v-model="pwdForm.new_password" type="password" placeholder="新密码" />
          <AppButton variant="primary" size="sm" :loading="pwdSaving" @click="handleChangePassword">修改密码</AppButton>
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
.settings-view { padding: 24px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; height: 100%; }
.loading-text { color: var(--text-dim); padding: 20px 0; }
.settings-tabs { display: flex; gap: 8px; overflow-x: auto; padding: 2px 2px 8px; margin: -2px -2px 0; scrollbar-width: none; -webkit-overflow-scrolling: touch; align-items: center; }
.settings-tabs::-webkit-scrollbar { display: none; }
.settings-tab { flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 38px; border: 1px solid var(--border); border-radius: 999px; padding: 9px 14px; color: var(--text-dim); background: var(--surface); font-size: 14px; font-weight: 600; cursor: pointer; transition: all .15s ease; white-space: nowrap; }
.settings-tab:hover { color: var(--text); border-color: var(--accent); }
.settings-tab.active { color: var(--accent); border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, var(--surface)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent); }
.settings-tab-icon { font-size: 15px; }
.settings-section { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px; display: flex; flex-direction: column; gap: 14px; }
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
.notify-channel-card { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); padding: 14px; margin-top: 12px; }
.notify-channel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.toggle-item input { flex: 0 0 auto; margin-top: 2px; accent-color: var(--accent); }
.toggle-item span { min-width: 0; }
.scheduler-list { display: flex; flex-direction: column; gap: 8px; }
.scheduler-row { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: var(--radius-md); background: var(--surface-hover); }
.scheduler-info { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.scheduler-name { font-size: 14px; font-weight: 500; }
.scheduler-meta { font-size: 12px; }
.pwd-form { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.pwd-form input { flex: 1; min-width: 160px; }
.save-bar { position: sticky; bottom: 0; z-index: 6; background: color-mix(in srgb, var(--bg) 94%, transparent); padding: 16px 0; border-top: 1px solid var(--border); display: flex; justify-content: flex-end; backdrop-filter: blur(max(14px, var(--blur-strength))); -webkit-backdrop-filter: blur(max(14px, var(--blur-strength))); }
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
  .site-grid, .fields-grid, .assistant-tool-grid { grid-template-columns: 1fr; gap: 10px; }
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