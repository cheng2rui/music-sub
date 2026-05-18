<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { getTasks, checkTasks, pauseTask, resumeTask, retryTask, deleteTask, previewTaskCleanup, applyTaskCleanup, pauseQbTask, resumeQbTask, deleteQbTask, importQbTask, organizeQbTask } from '@/api/index.js'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppModal from '@/components/AppModal.vue'

const tasks = ref([])
const loading = ref(false)
const actingId = ref(null)
const errorText = ref('')
const lastUpdatedAt = ref(null)
const cleanupLoading = ref(false)
const cleanupApplying = ref(false)
const cleanupPreview = ref(null)
const cleanupResult = ref(null)
const cleanupDeleteFiles = ref(false)
let timer = null

const hasActiveTasks = computed(() => tasks.value.some(t => ['downloading', 'organized', 'downloaded'].includes(t.status)))

function scheduleNextLoad() {
  if (timer) clearTimeout(timer)
  const delay = document.hidden ? 120000 : (hasActiveTasks.value ? 5000 : 60000)
  timer = setTimeout(async () => {
    await loadTasks()
    scheduleNextLoad()
  }, delay)
}

async function loadTasks() {
  try {
    errorText.value = ''
    tasks.value = await getTasks()
    lastUpdatedAt.value = new Date()
  } catch (e) {
    console.error(e)
    errorText.value = e.message || '任务加载失败'
  }
}

async function handleCheck() {
  loading.value = true
  try {
    await checkTasks()
    await loadTasks()
    scheduleNextLoad()
  } catch (e) {
    errorText.value = e.message || '检查失败'
  } finally {
    loading.value = false
  }
}

async function runTaskAction(task, action) {
  const key = task.external_qb ? task.torrent_hash : task.id
  actingId.value = `${action}:${key}`
  try {
    const deleteFiles = action === 'delete-files'
    if (task.external_qb) {
      if (action === 'pause') await pauseQbTask(task.torrent_hash)
      if (action === 'resume') await resumeQbTask(task.torrent_hash)
      if (action === 'import') await importQbTask(task.torrent_hash)
      if (action === 'organize') await organizeQbTask(task.torrent_hash)
      if (action === 'delete' || action === 'delete-files') {
        const message = deleteFiles
          ? `⚠️ 删除 qB 任务并删除本地文件？\n${task.torrent_name}\n\n此操作会让 qB 删除已下载数据文件，不可恢复。`
          : `删除 qB 任务？\n${task.torrent_name}\n\n只移除 qB 任务，保留已下载文件。`
        if (!confirm(message)) return
        await deleteQbTask(task.torrent_hash, deleteFiles)
      }
    } else {
      if (action === 'pause') await pauseTask(task.id)
      if (action === 'resume') await resumeTask(task.id)
      if (action === 'retry') await retryTask(task.id)
      if (action === 'delete' || action === 'delete-files') {
        const message = deleteFiles
          ? `⚠️ 删除任务并删除本地文件？\n${task.torrent_name}\n\n会删除任务记录/qB 种子，并让 qB 删除已下载数据文件，不可恢复。`
          : `删除任务？\n${task.torrent_name}\n\n会删除任务记录/qB 种子，但保留已下载文件。`
        if (!confirm(message)) return
        await deleteTask(task.id, deleteFiles)
      }
    }
    await loadTasks()
    scheduleNextLoad()
  } catch (e) {
    alert(e.message || '操作失败')
  } finally {
    actingId.value = null
  }
}

async function handleCleanupPreview() {
  cleanupLoading.value = true
  cleanupResult.value = null
  cleanupDeleteFiles.value = false
  try {
    cleanupPreview.value = await previewTaskCleanup()
  } catch (e) {
    alert(e.message || '清理扫描失败')
  } finally {
    cleanupLoading.value = false
  }
}

async function handleCleanupApply() {
  if (!cleanupPreview.value?.candidate_count) return
  const lines = [
    `确认清理 ${cleanupPreview.value.candidate_count} 条脏任务？`,
    `qB 种子：${cleanupPreview.value.unique_qb_hash_count} 个`,
    `影响大小：${formatSize(cleanupPreview.value.total_size || 0)}`,
    `未下载剩余：${formatSize(cleanupPreview.value.total_amount_left || 0)}`,
    '',
    cleanupDeleteFiles.value
      ? '⚠️ 已开启“同时删除下载文件”，qB 会尝试删除本地数据文件。'
      : '默认安全模式：不会删除下载文件，只移除任务记录/qB 种子。',
  ]
  const ok = confirm(lines.join('\n'))
  if (!ok) return
  cleanupApplying.value = true
  try {
    cleanupResult.value = await applyTaskCleanup(cleanupDeleteFiles.value)
    await loadTasks()
    cleanupPreview.value = await previewTaskCleanup()
    cleanupDeleteFiles.value = false
    scheduleNextLoad()
  } catch (e) {
    alert(e.message || '执行清理失败')
  } finally {
    cleanupApplying.value = false
  }
}

function closeCleanupModal() {
  cleanupPreview.value = null
  cleanupResult.value = null
  cleanupDeleteFiles.value = false
}

function reasonText(reasons = []) {
  const map = {
    simulated_hash: '模拟测试任务',
    qb_missing: 'qB 任务缺失',
    video_like: '疑似视频资源',
    paused_video_like: '已暂停且疑似视频',
    paused_zero_progress_video_like: '0% 暂停的视频类任务',
    external_qb_paused_video_like: 'qB 未关联且疑似视频',
    external_qb_paused_zero_progress_video_like: 'qB 未关联 0% 暂停的视频类任务',
  }
  return reasons.map(r => map[r] || r).join('、')
}

function statusLabel(s) {
  const map = {
    pending: { label: '等待中', color: 'dim' },
    downloading: { label: '下载中', color: 'blue' },
    downloaded: { label: '已下载', color: 'blue' },
    running: { label: '进行中', color: 'blue' },
    organized: { label: '已整理', color: 'blue' },
    scraped: { label: '已刮削', color: 'green' },
    completed: { label: '已完成', color: 'green' },
    paused: { label: '已暂停', color: 'dim' },
    missing: { label: 'qB缺失', color: 'orange' },
    failed: { label: '失败', color: 'red' },
  }
  return map[s] || { label: s || '-', color: 'dim' }
}

function formatSize(bytes) {
  if (!bytes) return '-'
  if (typeof bytes === 'string') return bytes
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB'
}

function progressPercent(task) {
  if (task.progress === null || task.progress === undefined) return null
  return Math.max(0, Math.min(100, Math.round(task.progress * 1000) / 10))
}

function formatSpeed(bytesPerSecond) {
  if (!bytesPerSecond) return ''
  return `${formatSize(bytesPerSecond)}/s`
}

function formatEta(seconds) {
  if (!seconds || seconds >= 8640000) return ''
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.ceil(seconds / 60)}m`
  return `${Math.ceil(seconds / 3600)}h`
}

function isQbManaged(task) {
  return task.torrent_hash && !task.torrent_hash.startsWith('online:') && !task.torrent_hash.startsWith('SIMULATED_')
}

function actionKey(task, action) {
  return `${action}:${task.external_qb ? task.torrent_hash : task.id}`
}

function canPause(task) {
  return isQbManaged(task) && !['paused', 'scraped', 'missing'].includes(task.status)
}

function canResume(task) {
  return isQbManaged(task) && task.status === 'paused'
}

function canOrganize(task) {
  return task.external_qb && task.progress === 1
}

function canRetry(task) {
  return !task.external_qb && isQbManaged(task) && ['failed', 'downloaded', 'organized'].includes(task.status)
}

function handleVisibilityChange() {
  scheduleNextLoad()
}

onMounted(async () => {
  await loadTasks()
  scheduleNextLoad()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  if (timer) clearTimeout(timer)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<template>
  <div class="tasks-view">
    <div class="tasks-header">
      <div>
        <h2>任务列表</h2>
        <div class="refresh-meta">
          {{ lastUpdatedAt ? `上次更新 ${lastUpdatedAt.toLocaleTimeString()}` : '尚未刷新' }}
          <span v-if="hasActiveTasks"> · 活跃任务 5s 刷新</span>
        </div>
      </div>
      <div class="header-actions">
        <AppButton variant="ghost" :loading="cleanupLoading" @click="handleCleanupPreview">清理扫描</AppButton>
        <AppButton variant="primary" :loading="loading" @click="handleCheck">检查完成</AppButton>
      </div>
    </div>

    <AppModal v-if="cleanupPreview" title="脏任务清理 dry-run" @close="closeCleanupModal">
      <div class="cleanup-summary">
        <div>扫描任务：{{ cleanupPreview.task_count }}</div>
        <div>候选清理：<strong>{{ cleanupPreview.candidate_count }}</strong></div>
        <div>仅删 DB：{{ cleanupPreview.db_only_count }} · qB+DB：{{ cleanupPreview.qb_and_db_count }} · qB Hash：{{ cleanupPreview.unique_qb_hash_count }}</div>
        <div>影响大小：{{ formatSize(cleanupPreview.total_size) }} · 未下载剩余：{{ formatSize(cleanupPreview.total_amount_left) }}</div>
      </div>
      <div v-if="cleanupResult" class="success-text">
        已清理 {{ cleanupResult.tasks_deleted }} 条任务，删除 music_files {{ cleanupResult.music_files_deleted }} 条；DB 备份：{{ cleanupResult.backup_path || '-' }}
      </div>
      <div v-if="cleanupPreview.warnings?.length" class="warning-text">
        <div v-for="w in cleanupPreview.warnings" :key="w">{{ w }}</div>
      </div>
      <template v-if="cleanupPreview.candidates.length">
        <div class="cleanup-list">
          <div v-for="item in cleanupPreview.candidates" :key="item.id" class="cleanup-item">
            <div class="cleanup-title">#{{ item.id }} {{ item.torrent_name }}</div>
            <div class="cleanup-meta">
              {{ item.cleanup_type === 'qb_and_db' ? 'qB + DB' : '仅 DB' }} · {{ item.effective_status }} · {{ item.qb_state || '-' }} · {{ reasonText(item.reasons) }}
            </div>
            <div class="cleanup-meta">
              大小 {{ formatSize(item.size) }} · 剩余 {{ formatSize(item.amount_left) }}
            </div>
          </div>
        </div>
        <label class="delete-files-toggle" :class="{ danger: cleanupDeleteFiles }">
          <input type="checkbox" v-model="cleanupDeleteFiles" />
          <span>
            同时删除下载文件
            <strong v-if="cleanupDeleteFiles">（危险：会让 qB 删除本地数据文件）</strong>
            <em v-else>（默认关闭，仅移除任务/qB 种子）</em>
          </span>
        </label>
      </template>
      <div v-else class="empty-text">没有发现需要清理的脏任务。</div>
      <div class="modal-actions">
        <AppButton variant="ghost" @click="closeCleanupModal">关闭</AppButton>
        <AppButton
          variant="danger"
          :disabled="!cleanupPreview.candidate_count"
          :loading="cleanupApplying"
          @click="handleCleanupApply"
        >执行清理</AppButton>
      </div>
    </AppModal>

    <div v-if="errorText" class="error-text">{{ errorText }}</div>
    <div v-if="tasks.length === 0" class="empty-text">暂无任务</div>
    <div v-else class="tasks-section">
      <div class="tasks-table-wrap">
        <table class="tasks-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>站点</th>
            <th>大小</th>
            <th>状态</th>
            <th>qB状态</th>
            <th>进度</th>
            <th>创建时间</th>
            <th>完成时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id">
            <td class="name-cell" :title="task.torrent_name">
              <div>{{ task.torrent_name }}</div>
              <div v-if="task.external_qb" class="external-qb-tag">qB 未关联 · {{ task.content_path || task.save_path || '' }}</div>
            </td>
            <td class="text-dim">{{ task.external_qb ? 'qB' : task.site }}</td>
            <td class="text-dim">{{ formatSize(task.size) }}</td>
            <td>
              <AppBadge :color="statusLabel(task.status).color">
                {{ statusLabel(task.status).label }}
              </AppBadge>
            </td>
            <td class="text-dim">
              <div>{{ task.qb_state || '-' }}</div>
              <div v-if="task.tracker_msg" class="tracker-msg" :title="task.tracker_msg">{{ task.tracker_msg }}</div>
            </td>
            <td class="progress-cell">
              <template v-if="progressPercent(task) !== null">
                <div class="progress-bar"><span :style="{ width: progressPercent(task) + '%' }"></span></div>
                <div class="progress-meta">
                  {{ progressPercent(task) }}%
                  <span v-if="task.download_speed"> · {{ formatSpeed(task.download_speed) }}</span>
                  <span v-if="task.eta"> · ETA {{ formatEta(task.eta) }}</span>
                </div>
              </template>
              <span v-else class="text-dim">-</span>
            </td>
            <td class="text-dim">{{ new Date(task.created_at).toLocaleString() }}</td>
            <td class="text-dim">{{ task.completed_at ? new Date(task.completed_at).toLocaleString() : '-' }}</td>
            <td>
              <div class="actions">
                <AppButton
                  v-if="canPause(task)"
                  size="sm"
                  variant="ghost"
                  :loading="actingId === actionKey(task, 'pause')"
                  @click="runTaskAction(task, 'pause')"
                >暂停</AppButton>
                <AppButton
                  v-if="canResume(task)"
                  size="sm"
                  variant="success"
                  :loading="actingId === actionKey(task, 'resume')"
                  @click="runTaskAction(task, 'resume')"
                >继续</AppButton>
                <AppButton
                  v-if="task.external_qb"
                  size="sm"
                  variant="ghost"
                  :loading="actingId === actionKey(task, 'import')"
                  @click="runTaskAction(task, 'import')"
                >导入</AppButton>
                <AppButton
                  v-if="canOrganize(task)"
                  size="sm"
                  variant="success"
                  :loading="actingId === actionKey(task, 'organize')"
                  @click="runTaskAction(task, 'organize')"
                >整理</AppButton>
                <AppButton
                  v-if="canRetry(task)"
                  size="sm"
                  variant="success"
                  :loading="actingId === actionKey(task, 'retry')"
                  @click="runTaskAction(task, 'retry')"
                >重试</AppButton>
                <AppButton
                  size="sm"
                  variant="ghost"
                  :loading="actingId === actionKey(task, 'delete')"
                  @click="runTaskAction(task, 'delete')"
                >删任务</AppButton>
                <AppButton
                  size="sm"
                  variant="danger"
                  :loading="actingId === actionKey(task, 'delete-files')"
                  @click="runTaskAction(task, 'delete-files')"
                >删文件</AppButton>
              </div>
            </td>
          </tr>
        </tbody>
        </table>
      </div>

      <div class="task-cards">
        <article v-for="task in tasks" :key="`card-${task.id}`" class="task-card">
          <div class="task-card-head">
            <h3 :title="task.torrent_name">{{ task.torrent_name }}</h3>
            <AppBadge :color="statusLabel(task.status).color">
              {{ statusLabel(task.status).label }}
            </AppBadge>
          </div>
          <div v-if="task.external_qb" class="external-qb-tag">qB 未关联 · {{ task.content_path || task.save_path || '' }}</div>
          <div class="task-meta-grid">
            <div><span>来源</span>{{ task.external_qb ? 'qB' : (task.site || '-') }}</div>
            <div><span>大小</span>{{ formatSize(task.size) }}</div>
            <div><span>qB</span>{{ task.qb_state || '-' }}</div>
            <div v-if="task.download_speed"><span>速度</span>{{ formatSpeed(task.download_speed) }}</div>
          </div>
          <div class="mobile-progress">
            <template v-if="progressPercent(task) !== null">
              <div class="progress-bar"><span :style="{ width: progressPercent(task) + '%' }"></span></div>
              <div class="progress-meta">
                {{ progressPercent(task) }}%
                <span v-if="task.eta"> · ETA {{ formatEta(task.eta) }}</span>
              </div>
            </template>
            <span v-else class="text-dim">进度 -</span>
          </div>
          <div v-if="task.tracker_msg" class="tracker-msg mobile" :title="task.tracker_msg">{{ task.tracker_msg }}</div>
          <div class="mobile-actions">
            <AppButton
              v-if="canPause(task)"
              size="sm"
              variant="ghost"
              :loading="actingId === actionKey(task, 'pause')"
              @click="runTaskAction(task, 'pause')"
            >暂停</AppButton>
            <AppButton
              v-if="canResume(task)"
              size="sm"
              variant="success"
              :loading="actingId === actionKey(task, 'resume')"
              @click="runTaskAction(task, 'resume')"
            >继续</AppButton>
            <AppButton
              v-if="task.external_qb"
              size="sm"
              variant="ghost"
              :loading="actingId === actionKey(task, 'import')"
              @click="runTaskAction(task, 'import')"
            >导入</AppButton>
            <AppButton
              v-if="canOrganize(task)"
              size="sm"
              variant="success"
              :loading="actingId === actionKey(task, 'organize')"
              @click="runTaskAction(task, 'organize')"
            >整理</AppButton>
            <AppButton
              v-if="canRetry(task)"
              size="sm"
              variant="success"
              :loading="actingId === actionKey(task, 'retry')"
              @click="runTaskAction(task, 'retry')"
            >重试</AppButton>
            <AppButton
              size="sm"
              variant="ghost"
              :loading="actingId === actionKey(task, 'delete')"
              @click="runTaskAction(task, 'delete')"
            >删任务</AppButton>
            <AppButton
              size="sm"
              variant="danger"
              :loading="actingId === actionKey(task, 'delete-files')"
              @click="runTaskAction(task, 'delete-files')"
            >删文件</AppButton>
          </div>
        </article>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tasks-view { padding: 24px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; height: 100%; }
.tasks-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.tasks-header h2 { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.refresh-meta { font-size: 12px; color: var(--text-dim); }
.empty-text { color: var(--text-dim); padding: 20px 0; }
.error-text { color: var(--danger); background: color-mix(in srgb, var(--danger) 12%, transparent); border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent); border-radius: var(--radius-md); padding: 10px 12px; }
.success-text { color: var(--success); background: color-mix(in srgb, var(--success) 12%, transparent); border: 1px solid color-mix(in srgb, var(--success) 30%, transparent); border-radius: var(--radius-md); padding: 10px 12px; margin: 12px 0; }
.warning-text { color: var(--warning); background: color-mix(in srgb, var(--warning) 12%, transparent); border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent); border-radius: var(--radius-md); padding: 10px 12px; margin: 12px 0; font-size: 13px; }
.cleanup-summary { display: flex; flex-direction: column; gap: 6px; color: var(--text-dim); font-size: 14px; margin-bottom: 12px; }
.cleanup-list { display: flex; flex-direction: column; gap: 8px; max-height: 360px; overflow-y: auto; }
.cleanup-item { padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-elevated); }
.cleanup-title { font-weight: 600; margin-bottom: 4px; }
.cleanup-meta { color: var(--text-dim); font-size: 12px; margin-top: 2px; }
.delete-files-toggle { display: flex; align-items: flex-start; gap: 8px; margin-top: 14px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text-dim); font-size: 13px; }
.delete-files-toggle input { margin-top: 2px; }
.delete-files-toggle strong { color: var(--danger); font-style: normal; }
.delete-files-toggle em { color: var(--text-muted); font-style: normal; }
.delete-files-toggle.danger { border-color: color-mix(in srgb, var(--danger) 45%, transparent); background: color-mix(in srgb, var(--danger) 10%, transparent); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.tasks-section { display: block; }
.tasks-table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-elevated); -webkit-overflow-scrolling: touch; }
.tasks-table { width: 100%; border-collapse: collapse; min-width: 1120px; }
.tasks-table th { text-align: left; padding: 8px 12px; font-size: 12px; font-weight: 600; color: var(--text-dim); border-bottom: 1px solid var(--border); }
.tasks-table td { padding: 10px 12px; font-size: 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.tasks-table tr:hover td { background: var(--surface-hover); }
.name-cell { font-weight: 500; max-width: 340px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.external-qb-tag { margin-top: 3px; font-size: 11px; color: var(--warning); overflow: hidden; text-overflow: ellipsis; }
.tracker-msg { margin-top: 2px; font-size: 11px; color: var(--danger, #f87171); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.progress-cell { min-width: 150px; }
.progress-bar { width: 120px; height: 6px; background: var(--surface); border-radius: 999px; overflow: hidden; margin-bottom: 4px; }
.progress-bar span { display: block; height: 100%; background: var(--accent); border-radius: inherit; }
.progress-meta { font-size: 12px; color: var(--text-dim); white-space: nowrap; }
.actions { display: flex; align-items: center; gap: 8px; }
.task-cards { display: none; }
.task-card { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-elevated); padding: 14px; }
.task-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.task-card-head h3 { min-width: 0; margin: 0; font-size: 15px; line-height: 1.35; font-weight: 700; overflow-wrap: anywhere; }
.task-meta-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 12px; color: var(--text-dim); font-size: 12px; }
.task-meta-grid div { min-width: 0; overflow-wrap: anywhere; }
.task-meta-grid span { display: block; color: var(--text-muted); font-size: 11px; margin-bottom: 2px; }
.mobile-progress { margin-top: 12px; }
.mobile-progress .progress-bar { width: 100%; }
.mobile-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.tracker-msg.mobile { max-width: none; white-space: normal; margin-top: 10px; }

@media (max-width: 768px) {
  .tasks-header { flex-direction: column; align-items: stretch; }
  .tasks-header h2 { font-size: 18px; }
  .header-actions { justify-content: space-between; flex-wrap: wrap; }
  .tasks-table-wrap { display: none; }
  .task-cards { display: flex; flex-direction: column; gap: 12px; }
  .cleanup-list { max-height: 46vh; }
  .modal-actions { display: grid; grid-template-columns: 1fr 1fr; }
}
@media (max-width: 420px) {
  .tasks-view { padding: 16px; }
  .header-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .task-meta-grid { grid-template-columns: 1fr; }
}

</style>
