<script setup>
import { ref, onMounted } from 'vue'
import { getSettings, updateSettings, testQb, testTelegram, testSite, getScheduler, runScheduler, changePasswordApi } from '@/api/index.js'
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
  scraper: { sources: ['qqmusic', 'netease', 'kugou', 'migu', 'kuwo', 'musicbrainz'], embed_cover: true, save_cover_file: true, save_lyrics: true, save_nfo: false, rename_file: false, overwrite_tag: false },
  scheduler: { search_interval_minutes: 30, check_complete_interval_minutes: 5, cleanup_scan_enabled: true, cleanup_scan_interval_hours: 24 },
  notify: { telegram: { enabled: false, bot_token: '', chat_id: '', on_download_added: false, on_download_complete: true, on_scrape_complete: true, on_error: true, on_cleanup_candidates: true } }
})
const loading = ref(false)
const saving = ref(false)
const testingQb = ref(false)
const testingTg = ref(false)
const testingSite = ref('')
const scheduler = ref([])

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
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function handleSave() {
  saving.value = true
  try {
    await updateSettings(settings.value)
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
    alert(res.ok ? 'Telegram 消息发送成功' : '发送失败: ' + (res.error || ''))
  } catch (e) { alert('发送失败: ' + e.message) }
  finally { testingTg.value = false }
}

async function handleRunScheduler(id) {
  try { await runScheduler(id) } catch (e) { console.error(e) }
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

      <!-- PT站配置 -->
      <div class="settings-section">
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
              <span class="site-name">🐬 Dis.Music 海豚</span>
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
      <div class="settings-section">
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
      <div class="settings-section">
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
      <div class="settings-section">
        <h3>🎵 刮削配置</h3>
        <div class="toggle-list">
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.embed_cover" /><span>嵌入封面到音频标签</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.save_cover_file" /><span>保存 cover.jpg 到专辑目录</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.save_lyrics" /><span>保存歌词</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.save_nfo" /><span>生成 album.nfo (Kodi/Jellyfin)</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.rename_file" /><span>按模板重命名文件</span></label>
          <label class="toggle-item"><input type="checkbox" v-model="settings.scraper.overwrite_tag" /><span>覆盖已有标签</span></label>
        </div>
      </div>

      <!-- 定时任务 -->
      <div class="settings-section">
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

      <!-- Telegram 通知 -->
      <div class="settings-section">
        <h3>📢 Telegram 通知</h3>
        <label class="toggle-item" style="margin-bottom:12px"><input type="checkbox" v-model="settings.notify.telegram.enabled" /><span>启用 Telegram 通知</span></label>
        <div v-if="settings.notify.telegram.enabled">
          <div class="fields-row">
            <div class="field flex-1">
              <label>Bot Token</label>
              <input v-model="settings.notify.telegram.bot_token" placeholder="123456:ABC-DEF..." />
            </div>
            <div class="field flex-1">
              <label>Chat ID</label>
              <input v-model="settings.notify.telegram.chat_id" placeholder="-100... 或 user id" />
            </div>
            <AppButton variant="ghost" size="sm" :loading="testingTg" @click="handleTestTg">测试发送</AppButton>
          </div>
          <div class="toggle-list" style="margin-top:12px">
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.telegram.on_download_added" /><span>开始下载</span></label>
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.telegram.on_download_complete" /><span>下载完成</span></label>
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.telegram.on_scrape_complete" /><span>刮削完成</span></label>
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.telegram.on_error" /><span>错误告警</span></label>
            <label class="toggle-item"><input type="checkbox" v-model="settings.notify.telegram.on_cleanup_candidates" /><span>清理候选提醒</span></label>
          </div>
        </div>
      </div>

      <!-- 账号安全 -->
      <div class="settings-section">
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
.settings-view { padding: 24px; display: flex; flex-direction: column; gap: 24px; overflow-y: auto; height: 100%; }
.loading-text { color: var(--text-dim); padding: 20px 0; }
.settings-section { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.settings-section h3 { font-size: 16px; font-weight: 600; }
.site-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.site-card { background: var(--surface-hover); border-radius: var(--radius-md); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.site-header { display: flex; align-items: center; justify-content: space-between; }
.site-name { font-size: 14px; font-weight: 700; letter-spacing: 0.5px; }
.toggle-label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; }
.toggle-label input { accent-color: var(--accent); }
.site-fields { display: flex; flex-direction: column; gap: 8px; }
.site-fields input { font-size: 13px; }
.fields-row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field.flex-1 { flex: 1; min-width: 160px; }
.field label { font-size: 12px; color: var(--text-dim); }
.toggle-list { display: flex; flex-direction: column; gap: 8px; }
.toggle-item { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 14px; }
.toggle-item input { accent-color: var(--accent); }
.scheduler-list { display: flex; flex-direction: column; gap: 8px; }
.scheduler-row { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: var(--radius-md); background: var(--surface-hover); }
.scheduler-info { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.scheduler-name { font-size: 14px; font-weight: 500; }
.scheduler-meta { font-size: 12px; }
.pwd-form { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.pwd-form input { flex: 1; min-width: 160px; }
.save-bar { position: sticky; bottom: 0; background: var(--bg); padding: 16px 0; border-top: 1px solid var(--border); display: flex; justify-content: flex-end; }

@media (max-width: 768px) {
  .site-grid { grid-template-columns: 1fr; }
  .pwd-form { flex-direction: column; align-items: stretch; }
  .pwd-form input { min-width: unset; }
  .scheduler-row { flex-direction: column; align-items: flex-start; gap: 8px; }
}
</style>