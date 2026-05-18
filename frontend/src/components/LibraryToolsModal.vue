<script setup>
import { computed, ref, watch } from 'vue'
import {
  listLibraryTools,
  previewLibraryTool,
  applyLibraryTool,
  getLibraryJob,
  getLibraryFiles,
  getFile,
} from '@/api/index.js'
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
const fileSearch = ref('')
const files = ref([])
const totalFiles = ref(0)
const currentPage = ref(0)
const pageSize = 50
const loadingFiles = ref(false)
const loadingAll = ref(false)
const selectedFileIds = ref(new Set())
const allLoadedIds = ref(new Set())
const loadedPages = ref(new Set())

const isCueTool = computed(() => activeTool.value && ['split_audio', 'cue_candidates'].includes(activeTool.value.id))
const pageCount = computed(() => Math.max(1, Math.ceil((totalFiles.value || 0) / pageSize)))
const pageFiles = computed(() => {
  const start = currentPage.value * pageSize
  return files.value.slice(start, start + pageSize).filter(Boolean)
})
const pageSelected = computed(() => pageFiles.value.length > 0 && pageFiles.value.every(f => selectedFileIds.value.has(f.id)))
const allMatchingSelected = computed(() => totalFiles.value > 0 && selectedFileIds.value.size >= totalFiles.value && allLoadedIds.value.size >= totalFiles.value)
const pageNumbers = computed(() => {
  const total = pageCount.value
  const current = currentPage.value + 1
  const nums = new Set([1, total])
  for (let i = current - 2; i <= current + 2; i += 1) {
    if (i >= 1 && i <= total) nums.add(i)
  }
  const sorted = Array.from(nums).sort((a, b) => a - b)
  const out = []
  sorted.forEach((n, idx) => {
    if (idx && n - sorted[idx - 1] > 1) out.push('...')
    out.push(n)
  })
  return out
})

const optionPlaceholder = computed(() => {
  if (!activeTool.value) return '{}'
  const id = activeTool.value.id
  if (id === 'retag') return JSON.stringify({ fields: { title: '${title}', artist: '${artist}' }, write_tags: true }, null, 2)
  if (id === 'organize') return JSON.stringify({ template: '{artist}/{album}/{disc:02d}-{track:02d} {title}{ext}' }, null, 2)
  if (id === 'split_meta') return JSON.stringify({ prefer_artist_left: true, write_tags: false }, null, 2)
  if (id === 'identify') return JSON.stringify({ write_tags: false }, null, 2)
  if (id === 'album_artist') return JSON.stringify({ album_artist: '', write_tags: false }, null, 2)
  if (id === 'dedupe') return JSON.stringify({ mode: 'trash' }, null, 2)
  if (id === 'split_audio' || id === 'cue_candidates') return JSON.stringify({ keep_original: true, overwrite_existing: false, output_subdir: '', stream_copy: false }, null, 2)
  if (id === 'zh_t2s' || id === 'zh_s2t') return JSON.stringify({ fields: ['title', 'artist', 'album', 'genre'], write_tags: false }, null, 2)
  if (id === 'fix_garble') return JSON.stringify({ fields: ['title', 'artist', 'album', 'genre'], write_tags: false }, null, 2)
  return '{}'
})

const scopeLabel = computed(() => {
  const ctx = props.context || {}
  if (selectedFileIds.value.size) return `已选择 ${selectedFileIds.value.size} / ${totalFiles.value || selectedFileIds.value.size} 个文件`
  if (Array.isArray(ctx.file_ids) && ctx.file_ids.length) return `传入的 ${ctx.file_ids.length} 个文件`
  if (ctx.album_artist || ctx.album_name) return `当前专辑：${[ctx.album_artist, ctx.album_name].filter(Boolean).join(' / ')}`
  return '按搜索条件选择文件（每页 50 个）'
})

watch(() => props.open, async (val) => {
  if (val && tools.value.length === 0) {
    const data = await listLibraryTools()
    tools.value = data.tools || []
  }
  if (val) {
    reset()
    await loadScopeFiles()
    selectPreferredTool()
  }
})

function reset() {
  activeTool.value = null
  previewData.value = null
  job.value = null
  optionText.value = '{}'
  optionError.value = ''
  deleteIds.value = new Set()
  selectedFileIds.value = new Set()
  files.value = []
  totalFiles.value = 0
  currentPage.value = 0
  allLoadedIds.value = new Set()
  loadedPages.value = new Set()
}

function normalizeFile(row) {
  return {
    id: Number(row.id),
    title: row.title || row.file_path || `#${row.id}`,
    artist: row.artist || row.album_artist || '未知艺人',
    album: row.album || '未知专辑',
    file_path: row.file_path || '',
    format: row.format || '',
    duration: row.duration || 0,
    track_number: row.track_number,
    disc_number: row.disc_number,
  }
}

function pageParams(page = currentPage.value) {
  const ctx = props.context || {}
  const params = {
    q: fileSearch.value.trim(),
    limit: pageSize,
    offset: page * pageSize,
    sort: 'track',
  }
  if (ctx.album_artist || ctx.album_name) {
    params.album_artist = ctx.album_artist || ''
    params.album_name = ctx.album_name || ''
  }
  return params
}

function mergePageItems(page, rows) {
  const normalized = (rows || []).map(normalizeFile)
  const next = files.value.slice()
  const start = page * pageSize
  if (totalFiles.value) next.length = Math.max(next.length, totalFiles.value)
  normalized.forEach((file, idx) => { next[start + idx] = file })
  files.value = next
  const ids = new Set(allLoadedIds.value)
  normalized.forEach(f => ids.add(f.id))
  allLoadedIds.value = ids
  loadedPages.value = new Set([...loadedPages.value, page])
}

async function loadScopeFiles() {
  loadingFiles.value = true
  try {
    const ctx = props.context || {}
    files.value = []
    totalFiles.value = 0
    currentPage.value = 0
    allLoadedIds.value = new Set()
    loadedPages.value = new Set()
    if (Array.isArray(ctx.file_ids) && ctx.file_ids.length) {
      const collected = []
      for (let i = 0; i < ctx.file_ids.length; i += pageSize) {
        const chunk = ctx.file_ids.slice(i, i + pageSize)
        const rows = await Promise.all(chunk.map(id => getFile(id).catch(() => null)))
        collected.push(...rows.filter(Boolean).map(normalizeFile))
      }
      files.value = collected
      totalFiles.value = collected.length
      allLoadedIds.value = new Set(collected.map(f => f.id))
      loadedPages.value = new Set(Array.from({ length: pageCount.value }, (_, i) => i))
      selectedFileIds.value = new Set(collected.map(f => f.id))
      return
    }
    await changePage(0, true)
  } finally {
    loadingFiles.value = false
  }
}

async function searchFiles() {
  selectedFileIds.value = new Set()
  files.value = []
  totalFiles.value = 0
  allLoadedIds.value = new Set()
  loadedPages.value = new Set()
  await changePage(0, true)
}

async function changePage(page, force = false) {
  const target = Math.min(Math.max(0, page), pageCount.value - 1)
  currentPage.value = target
  if (!force && loadedPages.value.has(target)) return
  loadingFiles.value = true
  try {
    const data = await getLibraryFiles(pageParams(target))
    totalFiles.value = data.total || 0
    mergePageItems(target, data.items || [])
  } finally {
    loadingFiles.value = false
  }
}

async function loadMoreFiles() {
  if (currentPage.value >= pageCount.value - 1) return
  await changePage(currentPage.value + 1)
}

function toggleFile(id) {
  const next = new Set(selectedFileIds.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selectedFileIds.value = next
}

function selectCurrentPage() {
  const next = new Set(selectedFileIds.value)
  pageFiles.value.forEach(f => next.add(f.id))
  selectedFileIds.value = next
}

function clearCurrentPage() {
  const next = new Set(selectedFileIds.value)
  pageFiles.value.forEach(f => next.delete(f.id))
  selectedFileIds.value = next
}

function clearSelectedFiles() {
  selectedFileIds.value = new Set()
}

function selectAllLoaded() {
  selectedFileIds.value = new Set([...selectedFileIds.value, ...allLoadedIds.value])
}

async function toggleSelectAllMatching(event) {
  if (!event.target.checked) {
    clearSelectedFiles()
    return
  }
  loadingAll.value = true
  try {
    for (let page = 0; page < pageCount.value; page += 1) {
      if (!loadedPages.value.has(page)) {
        const data = await getLibraryFiles(pageParams(page))
        totalFiles.value = data.total || totalFiles.value
        mergePageItems(page, data.items || [])
      }
    }
    selectedFileIds.value = new Set(allLoadedIds.value)
  } finally {
    loadingAll.value = false
  }
}

function buildToolPayload(options) {
  const payload = { ...props.context, options }
  if (selectedFileIds.value.size) {
    payload.file_ids = Array.from(selectedFileIds.value)
    delete payload.album_artist
    delete payload.album_name
  }
  return payload
}

function parseOptions() {
  optionError.value = ''
  if (!optionText.value.trim()) return {}
  try {
    return JSON.parse(optionText.value)
  } catch (err) {
    optionError.value = '高级选项 JSON 解析失败：' + err.message
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
    previewData.value = await previewLibraryTool(activeTool.value.id, buildToolPayload(options))
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
    const res = await applyLibraryTool(activeTool.value.id, { ...buildToolPayload(options), async: true })
    if (res.job_id) await pollJob(res.job_id)
  } catch (err) {
    alert(err.message || '执行失败')
  } finally {
    applying.value = false
  }
}

async function pollJob(id) {
  job.value = { id, status: 'queued', progress: 0, total: previewData.value?.items?.length || selectedFileIds.value.size || 0 }
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

function clearToolSelection() {
  activeTool.value = null
  previewData.value = null
  job.value = null
  deleteIds.value = new Set()
}

function selectTool(tool) {
  activeTool.value = tool
  let options = {}
  try { options = JSON.parse(optionPlaceholder.value || '{}') } catch (_) { options = {} }
  optionText.value = JSON.stringify({ ...options, ...(props.context?.options || {}) }, null, 2)
  previewData.value = null
  job.value = null
  deleteIds.value = new Set()
}

function selectPreferredTool() {
  const preferred = props.context?.preferred_tool
  if (!props.open || !tools.value.length || !preferred || activeTool.value) return
  const tool = tools.value.find(t => t.id === preferred)
  if (tool) selectTool(tool)
}

watch(() => [tools.value.length, props.context?.preferred_tool], selectPreferredTool)

function handleClose() {
  emit('close')
}
</script>

<template>
  <AppModal v-if="open" title="库工具箱" @close="handleClose">
    <div class="tools-modal">
      <div class="scope-panel">
        <div class="scope-head">
          <div>
            <strong>操作范围</strong>
            <span>{{ scopeLabel }}</span>
          </div>
          <div class="page-status">第 {{ currentPage + 1 }} 页 / 共 {{ pageCount }} 页</div>
        </div>

        <div class="file-search-row" v-if="!(context.file_ids?.length)">
          <input v-model="fileSearch" class="file-search" placeholder="搜索标题 / 艺人 / 专辑 / 路径" @keyup.enter="searchFiles" />
          <AppButton variant="ghost" size="sm" :loading="loadingFiles" @click="searchFiles">搜索</AppButton>
        </div>

        <div class="file-count-line">共 {{ totalFiles }} 个文件，当前页 {{ pageFiles.length }} 个</div>

        <div class="scope-actions">
          <label class="check-action">
            <input type="checkbox" :checked="pageSelected" @change="$event.target.checked ? selectCurrentPage() : clearCurrentPage()" />
            全选当页
          </label>
          <label class="check-action">
            <input type="checkbox" :checked="allMatchingSelected" :disabled="loadingAll || !totalFiles" @change="toggleSelectAllMatching" />
            全选所有(共{{ totalFiles }}个)
          </label>
          <AppButton variant="ghost" size="sm" :disabled="!allLoadedIds.size" @click="selectAllLoaded">全选已加载</AppButton>
          <AppButton variant="ghost" size="sm" @click="clearSelectedFiles">清空</AppButton>
          <span v-if="loadingAll" class="mini-loading">正在加载全部...</span>
          <span v-else class="selected-status">已选 {{ selectedFileIds.size }} / {{ totalFiles }} 个</span>
        </div>

        <div v-if="loadingFiles && !pageFiles.length" class="info-line">加载文件中...</div>
        <div v-else class="file-picker">
          <label v-for="file in pageFiles" :key="file.id" class="file-option">
            <input type="checkbox" :checked="selectedFileIds.has(file.id)" @change="toggleFile(file.id)" />
            <span class="track-no">{{ file.track_number ? String(file.track_number).padStart(2, '0') : '--' }}</span>
            <span class="file-option-main">
              <strong>{{ file.title }}</strong>
              <em>{{ file.artist }} · {{ file.album }}</em>
              <small>{{ file.file_path }}</small>
            </span>
            <span class="file-format">{{ file.format }}</span>
          </label>
          <div v-if="!pageFiles.length" class="info-line">没有可选择的文件。</div>
        </div>

        <div class="pager" v-if="pageCount > 1">
          <button :disabled="currentPage === 0 || loadingFiles" @click="changePage(0)">&lt;&lt;</button>
          <button :disabled="currentPage === 0 || loadingFiles" @click="changePage(currentPage - 1)">&lt;</button>
          <template v-for="p in pageNumbers" :key="p + '-page'">
            <span v-if="p === '...'" class="pager-ellipsis">...</span>
            <button v-else :class="{ active: p === currentPage + 1 }" :disabled="loadingFiles" @click="changePage(p - 1)">{{ p }}</button>
          </template>
          <button :disabled="currentPage >= pageCount - 1 || loadingFiles" @click="loadMoreFiles">&gt;</button>
          <button :disabled="currentPage >= pageCount - 1 || loadingFiles" @click="changePage(pageCount - 1)">&gt;&gt;</button>
        </div>
        <div class="scope-hint">不勾选文件时，会按当前专辑/传入范围处理；勾选后只处理选中的文件。</div>
      </div>

      <div class="tool-grid" v-if="!activeTool">
        <button v-for="t in tools" :key="t.id" class="tool-card" @click="selectTool(t)">
          <strong>{{ t.label }}</strong>
          <span>{{ t.description }}</span>
        </button>
      </div>

      <div v-else class="tool-detail">
        <div class="tool-detail-head">
          <button class="link-back" @click="clearToolSelection">← 全部工具</button>
          <h3>{{ activeTool.label }}</h3>
          <span class="detail-desc">{{ activeTool.description }}</span>
        </div>

        <details class="tool-options">
          <summary>高级选项（可选）</summary>
          <label class="opt-label">
            JSON 参数
            <textarea v-model="optionText" rows="5" class="opt-area" :placeholder="optionPlaceholder"></textarea>
            <span v-if="optionError" class="opt-error">{{ optionError }}</span>
          </label>
        </details>
        <div class="opt-actions">
          <AppButton variant="ghost" :loading="previewing" @click="runPreview">预览</AppButton>
          <AppButton variant="primary" :loading="applying" :disabled="!previewData || previewData.error" @click="runApply">应用</AppButton>
        </div>

        <div v-if="previewing" class="info-line">预览中...</div>
        <div v-else-if="previewData?.error" class="info-line err">{{ previewData.error }}</div>
        <div v-else-if="previewData?.items?.length" class="preview-table-wrap">
          <div class="preview-summary">
            {{ previewData.summary?.changed ?? '?' }} / {{ previewData.summary?.total ?? previewData.items.length }} 项需要变更
            <template v-if="previewData.summary?.tracks"> · 预计拆出 {{ previewData.summary.tracks }} 首</template>
          </div>
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
                <td class="reason-cell">
                  <div>{{ item.reason || (item.would_change ? '需变更' : '无变化') }}</div>
                  <div v-if="isCueTool && item.after?.tracks?.length" class="cue-track-list">
                    <div v-for="track in item.after.tracks.slice(0, 12)" :key="track.index" class="cue-track-row">
                      <span>{{ String(track.index).padStart(2, '0') }}</span>
                      <strong>{{ track.title }}</strong>
                      <em>{{ track.performer }}</em>
                      <small>{{ track.out }}</small>
                    </div>
                    <div v-if="item.after.tracks.length > 12" class="cue-more">还有 {{ item.after.tracks.length - 12 }} 首未显示</div>
                  </div>
                </td>
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
.tools-modal { display: flex; flex-direction: column; gap: 14px; min-width: 640px; max-width: 980px; }
.scope-panel { display: flex; flex-direction: column; gap: 10px; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); }
.scope-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.scope-head strong { display: block; font-size: 14px; }
.scope-head span { display: block; margin-top: 4px; font-size: 12px; color: var(--text-dim); }
.page-status { font-size: 12px; color: var(--text-dim); white-space: nowrap; }
.scope-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.check-action { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--text-dim); cursor: pointer; }
.check-action input { margin: 0; }
.file-search-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
.file-search { width: 100%; padding: 9px 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-elevated); color: var(--text); }
.file-count-line, .selected-status, .mini-loading { font-size: 12px; color: var(--text-muted); }
.file-picker { max-height: 300px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding: 2px; }
.file-option { display: grid; grid-template-columns: auto 34px minmax(0, 1fr) 52px; gap: 9px; align-items: center; padding: 9px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-elevated); cursor: pointer; }
.file-option:hover { border-color: var(--accent); }
.track-no { color: var(--accent); font-weight: 700; font-size: 12px; text-align: right; }
.file-option-main { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.file-option-main strong { font-size: 13px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-option-main em { font-style: normal; font-size: 12px; color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-option-main small { font-size: 11px; color: var(--text-muted); word-break: break-all; }
.file-format { color: var(--text-muted); font-size: 11px; text-align: right; text-transform: uppercase; }
.pager { display: flex; gap: 6px; align-items: center; justify-content: center; flex-wrap: wrap; }
.pager button { min-width: 30px; height: 28px; padding: 0 8px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-elevated); color: var(--text-dim); cursor: pointer; }
.pager button:hover:not(:disabled), .pager button.active { border-color: var(--accent); color: var(--text); background: var(--surface-hover); }
.pager button:disabled { opacity: .45; cursor: not-allowed; }
.pager-ellipsis { color: var(--text-muted); padding: 0 2px; }
.scope-hint { font-size: 11px; color: var(--text-muted); }
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

.tool-options { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px; background: var(--surface); }
.tool-options summary { cursor: pointer; font-size: 12px; color: var(--text-dim); }
.opt-label { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; font-size: 12px; color: var(--text-dim); }
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
.cue-track-list { margin-top: 8px; display: flex; flex-direction: column; gap: 5px; max-height: 220px; overflow-y: auto; }
.cue-track-row { display: grid; grid-template-columns: 32px minmax(90px, 1.2fr) minmax(70px, .8fr); gap: 8px; align-items: baseline; padding: 6px 8px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-elevated); }
.cue-track-row span { color: var(--accent); font-weight: 700; }
.cue-track-row strong { color: var(--text); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cue-track-row em { font-style: normal; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cue-track-row small { grid-column: 2 / 4; color: var(--text-muted); word-break: break-all; font-size: 10px; }
.cue-more { padding: 4px 8px; color: var(--text-muted); font-size: 11px; }
.dedupe-keep { color: var(--accent); font-weight: 700; font-size: 11px; }

.job-progress { display: flex; flex-direction: column; gap: 6px; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); }
.job-head { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-dim); }
.job-bar { height: 6px; background: var(--bg-elevated); border-radius: 999px; overflow: hidden; }
.job-bar > div { height: 100%; background: var(--accent); transition: width .25s; }
.job-summary { white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto; font-size: 11px; color: var(--text-dim); margin: 0; }
.job-summary.err { color: var(--danger); }

@media (max-width: 720px) {
  .tools-modal { min-width: 0; max-width: 100%; }
  .scope-head { flex-direction: column; }
  .scope-actions { justify-content: flex-start; }
  .file-option { grid-template-columns: auto 30px minmax(0, 1fr); }
  .file-format { display: none; }
}
</style>
