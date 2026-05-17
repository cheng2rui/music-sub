<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { listLibraryTools, previewLibraryTool, applyLibraryTool, getLibraryJob } from '@/api/index.js'
import AppModal from '@/components/AppModal.vue'
import AppButton from '@/components/AppButton.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  context: { type: Object, default: () => ({}) }, // {file_ids?, album_artist?, album_name?}
})
const emit = defineEmits(['close'])

const tools = ref([])
const activeTool = ref(null)
const previewData = ref(null)
const previewing = ref(false)
const applying = ref(false)
const job = ref(null)
const optionText = ref('{}')
const optionError = ref('')
const deleteIds = ref(new Set())

const optionPlaceholder = computed(() => {
  if (!activeTool.value) return '{}'
  const id = activeTool.value.id
  if (id === 'retag') return JSON.stringify({ fields: { title: '${title}', artist: '${artist}' }, write_tags: true }, null, 2)
  if (id === 'organize') return JSON.stringify({ template: '{artist}/{album}/{disc:02d}-{track:02d} {title}{ext}' }, null, 2)
  if (id === 'split_meta') return JSON.stringify({ prefer_artist_left: true, write_tags: false }, null, 2)
  if (id === 'identify') return JSON.stringify({ write_tags: false }, null, 2)
  if (id === 'dedupe') return JSON.stringify({ mode: 'trash' }, null, 2)
  return '{}'
})

watch(() => props.open, async (val) => {
  if (val && tools.value.length === 0) {
    const data = await listLibraryTools()
    tools.value = data.tools || []
  }
  if (val) reset()
})

function reset() {
  activeTool.value = null
  previewData.value = null
  job.value = null
  optionText.value = '{}'
  optionError.value = ''
  deleteIds.value = new Set()
}

function parseOptions() {
  optionError.value = ''
  if (!optionText.value.trim()) return {}
  try {
    return JSON.parse(optionText.value)
  } catch (err) {
    optionError.value = '选项 JSON 解析失败：' + err.message
    return null
  }
}

async function runPreview() {
  if (!activeTool.value) return
  const options = parseOptions()
  if (options === null) return
  previewing.value = true
  previewData.value = null
  job.value = null
  deleteIds.value = new Set()
  try {
    previewData.value = await previewLibraryTool(activeTool.value.id, { ...props.context, options })
  } catch (err) {
    previewData.value = { error: err.message }
  } finally {
    previewing.value = false
  }
}

async function runApply() {
  if (!activeTool.value) return
  const options = parseOptions()
  if (options === null) return
  if (activeTool.value.id === 'dedupe') {
    options.delete_ids = Array.from(deleteIds.value)
    if (!options.delete_ids.length) {
      alert('请在预览里选中要处理的重复项')
      return
    }
  }
  applying.value = true
  try {
    const res = await applyLibraryTool(activeTool.value.id, { ...props.context, options, async: true })
    if (res.job_id) await pollJob(res.job_id)
  } catch (err) {
    alert(err.message || '执行失败')
  } finally {
    applying.value = false
  }
}

async function pollJob(id) {
  job.value = { id, status: 'queued', progress: 0, total: previewData.value?.items?.length || 0 }
  while (true) {
    const data = await getLibraryJob(id)
    job.value = data
    if (['done', 'failed', 'cancelled'].includes(data.status)) break
    await new Promise(r => setTimeout(r, 800))
  }
}

function toggleDelete(id) {
  if (deleteIds.value.has(id)) deleteIds.value.delete(id)
  else deleteIds.value.add(id)
  deleteIds.value = new Set(deleteIds.value)
}

function selectTool(tool) {
  activeTool.value = tool
  optionText.value = optionPlaceholder.value
  previewData.value = null
  job.value = null
  deleteIds.value = new Set()
}

function handleClose() {
  emit('close')
}
</script>

<template>
  <AppModal v-if="open" title="库工具箱" @close="handleClose">
    <div class="tools-modal">
      <div class="tool-grid" v-if="!activeTool">
        <button v-for="t in tools" :key="t.id" class="tool-card" @click="selectTool(t)">
          <strong>{{ t.label }}</strong>
          <span>{{ t.description }}</span>
        </button>
      </div>

      <div v-else class="tool-detail">
        <div class="tool-detail-head">
          <button class="link-back" @click="reset">← 全部工具</button>
          <h3>{{ activeTool.label }}</h3>
          <span class="detail-desc">{{ activeTool.description }}</span>
        </div>

        <div class="tool-options">
          <label class="opt-label">
            选项 (JSON)
            <textarea v-model="optionText" rows="5" class="opt-area" :placeholder="optionPlaceholder"></textarea>
            <span v-if="optionError" class="opt-error">{{ optionError }}</span>
          </label>
          <div class="opt-actions">
            <AppButton variant="ghost" :loading="previewing" @click="runPreview">预览</AppButton>
            <AppButton variant="primary" :loading="applying" :disabled="!previewData || previewData.error" @click="runApply">应用</AppButton>
          </div>
        </div>

        <div v-if="previewing" class="info-line">预览中...</div>
        <div v-else-if="previewData?.error" class="info-line err">{{ previewData.error }}</div>
        <div v-else-if="previewData?.items?.length" class="preview-table-wrap">
          <div class="preview-summary">{{ previewData.summary?.changed ?? '?' }} / {{ previewData.summary?.total ?? previewData.items.length }} 项需要变更</div>
          <table class="preview-table">
            <thead>
              <tr>
                <th v-if="activeTool.id === 'dedupe'">删</th>
                <th>#</th>
                <th>文件</th>
                <th>变更</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in previewData.items" :key="item.file_id" :class="{ change: item.would_change }">
                <td v-if="activeTool.id === 'dedupe'">
                  <input v-if="item.after?.action === 'duplicate'" type="checkbox" :checked="deleteIds.has(item.file_id)" @change="toggleDelete(item.file_id)" />
                  <span v-else class="dedupe-keep">keep</span>
                </td>
                <td>{{ item.file_id }}</td>
                <td class="file-cell">
                  <div class="file-name">{{ item.label }}</div>
                  <div class="file-path">{{ item.file_path }}</div>
                </td>
                <td class="reason-cell">{{ item.reason || (item.would_change ? '需变更' : '无变化') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else-if="previewData?.summary?.empty" class="info-line">当前范围下没有可处理的文件。</div>
        <div v-else-if="previewData" class="info-line">预览完成，未发现需要变更的项。</div>

        <div v-if="job" class="job-progress">
          <div class="job-head">
            <span>后台任务: {{ job.status }}</span>
            <span>{{ job.progress }} / {{ job.total }}</span>
          </div>
          <div class="job-bar"><div :style="`width:${job.total ? Math.round(job.progress*100/job.total) : 0}%`"></div></div>
          <pre v-if="job.summary" class="job-summary">{{ JSON.stringify(job.summary, null, 2) }}</pre>
          <pre v-if="job.error" class="job-summary err">{{ job.error }}</pre>
        </div>
      </div>
    </div>
  </AppModal>
</template>

<style scoped>
.tools-modal { display: flex; flex-direction: column; gap: 14px; min-width: 520px; max-width: 900px; }
.tool-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.tool-card { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); color: var(--text); cursor: pointer; text-align: left; }
.tool-card:hover { background: var(--surface-hover); border-color: var(--accent); }
.tool-card strong { font-size: 14px; }
.tool-card span { font-size: 12px; color: var(--text-dim); line-height: 1.5; }

.tool-detail { display: flex; flex-direction: column; gap: 10px; }
.tool-detail-head { display: flex; flex-direction: column; gap: 4px; }
.tool-detail-head h3 { margin: 0; font-size: 16px; }
.detail-desc { color: var(--text-dim); font-size: 12px; }
.link-back { background: none; border: 0; color: var(--text-muted); cursor: pointer; padding: 0; align-self: flex-start; font-size: 12px; }
.link-back:hover { color: var(--text); }

.tool-options { display: flex; flex-direction: column; gap: 8px; }
.opt-label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); }
.opt-area { width: 100%; min-height: 90px; resize: vertical; font-family: 'Source Code Pro', monospace; font-size: 12px; padding: 8px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text); }
.opt-error { color: var(--danger); font-size: 12px; }
.opt-actions { display: flex; gap: 8px; justify-content: flex-end; }

.info-line { color: var(--text-dim); padding: 6px 0; font-size: 13px; }
.info-line.err { color: var(--danger); }
.preview-summary { color: var(--text-dim); font-size: 12px; margin-bottom: 6px; }
.preview-table-wrap { max-height: 320px; overflow-y: auto; border: 1px solid var(--border); border-radius: var(--radius-md); }
.preview-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.preview-table th, .preview-table td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
.preview-table tr.change td { background: rgba(29,185,84,0.06); }
.file-cell { max-width: 240px; }
.file-name { font-weight: 600; }
.file-path { color: var(--text-muted); font-size: 11px; word-break: break-all; }
.reason-cell { color: var(--text-dim); }
.dedupe-keep { color: var(--accent); font-weight: 700; font-size: 11px; }

.job-progress { display: flex; flex-direction: column; gap: 6px; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); }
.job-head { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-dim); }
.job-bar { height: 6px; background: var(--bg-elevated); border-radius: 999px; overflow: hidden; }
.job-bar > div { height: 100%; background: var(--accent); transition: width .25s; }
.job-summary { white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto; font-size: 11px; color: var(--text-dim); margin: 0; }
.job-summary.err { color: var(--danger); }
</style>
