<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getTasks, checkTasks, pauseTask, resumeTask, deleteTask } from '@/api/index.js'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'

const tasks = ref([])
const loading = ref(false)
const actingId = ref(null)
let timer = null

async function loadTasks() {
  try {
    tasks.value = await getTasks()
  } catch (e) {
    console.error(e)
  }
}

async function handleCheck() {
  loading.value = true
  try {
    await checkTasks()
    await loadTasks()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function runTaskAction(task, action) {
  actingId.value = `${action}:${task.id}`
  try {
    if (action === 'pause') await pauseTask(task.id)
    if (action === 'resume') await resumeTask(task.id)
    if (action === 'delete') {
      if (!confirm(`删除任务记录？\n${task.torrent_name}\n\n不会删除已下载文件。`)) return
      await deleteTask(task.id)
    }
    await loadTasks()
  } catch (e) {
    alert(e.message || '操作失败')
  } finally {
    actingId.value = null
  }
}

function statusLabel(s) {
  const map = {
    pending: { label: '等待中', color: 'dim' },
    downloading: { label: '下载中', color: 'blue' },
    running: { label: '进行中', color: 'blue' },
    organized: { label: '已整理', color: 'blue' },
    scraped: { label: '已刮削', color: 'green' },
    completed: { label: '已完成', color: 'green' },
    paused: { label: '已暂停', color: 'dim' },
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

function formatProgress(task) {
  if (task.progress === null || task.progress === undefined) return '-'
  return `${Math.round(task.progress * 1000) / 10}%`
}

function canPause(task) {
  return task.torrent_hash && !task.torrent_hash.startsWith('online:') && !task.torrent_hash.startsWith('SIMULATED_') && task.status !== 'paused' && task.status !== 'scraped'
}

function canResume(task) {
  return task.torrent_hash && !task.torrent_hash.startsWith('online:') && !task.torrent_hash.startsWith('SIMULATED_') && task.status === 'paused'
}

onMounted(async () => {
  await loadTasks()
  timer = setInterval(loadTasks, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="tasks-view">
    <div class="tasks-header">
      <h2>任务列表</h2>
      <AppButton variant="primary" :loading="loading" @click="handleCheck">检查完成</AppButton>
    </div>

    <div v-if="tasks.length === 0" class="empty-text">暂无任务</div>
    <div v-else class="tasks-table-wrap">
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
            <td class="name-cell" :title="task.torrent_name">{{ task.torrent_name }}</td>
            <td class="text-dim">{{ task.site }}</td>
            <td class="text-dim">{{ formatSize(task.size) }}</td>
            <td>
              <AppBadge :color="statusLabel(task.status).color">
                {{ statusLabel(task.status).label }}
              </AppBadge>
            </td>
            <td class="text-dim">{{ task.qb_state || '-' }}</td>
            <td class="text-dim">{{ formatProgress(task) }}</td>
            <td class="text-dim">{{ new Date(task.created_at).toLocaleString() }}</td>
            <td class="text-dim">{{ task.completed_at ? new Date(task.completed_at).toLocaleString() : '-' }}</td>
            <td>
              <div class="actions">
                <AppButton
                  v-if="canPause(task)"
                  size="sm"
                  variant="ghost"
                  :loading="actingId === `pause:${task.id}`"
                  @click="runTaskAction(task, 'pause')"
                >暂停</AppButton>
                <AppButton
                  v-if="canResume(task)"
                  size="sm"
                  variant="success"
                  :loading="actingId === `resume:${task.id}`"
                  @click="runTaskAction(task, 'resume')"
                >继续</AppButton>
                <AppButton
                  size="sm"
                  variant="danger"
                  :loading="actingId === `delete:${task.id}`"
                  @click="runTaskAction(task, 'delete')"
                >删除</AppButton>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.tasks-view { padding: 24px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; height: 100%; }
.tasks-header { display: flex; align-items: center; justify-content: space-between; }
.tasks-header h2 { font-size: 20px; font-weight: 700; }
.empty-text { color: var(--text-dim); padding: 20px 0; }
.tasks-table-wrap { overflow-x: auto; }
.tasks-table { width: 100%; border-collapse: collapse; min-width: 1040px; }
.tasks-table th { text-align: left; padding: 8px 12px; font-size: 12px; font-weight: 600; color: var(--text-dim); border-bottom: 1px solid var(--border); }
.tasks-table td { padding: 10px 12px; font-size: 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.tasks-table tr:hover td { background: var(--surface-hover); }
.name-cell { font-weight: 500; max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.actions { display: flex; align-items: center; gap: 8px; }
</style>
