import { useAuthStore } from '@/stores/auth.js'

async function authFetch(url, options = {}) {
  const auth = useAuthStore()
  const headers = { ...(options.headers || {}) }
  const { timeoutMs, ...fetchOptions } = options
  let timeoutId = null
  let signal = fetchOptions.signal
  if (timeoutMs) {
    const controller = new AbortController()
    timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)
    signal = controller.signal
  }
  if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`
  // Only set Content-Type for requests with body
  if (fetchOptions.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }

  let res
  try {
    res = await fetch(url, { ...fetchOptions, headers, signal })
  } catch (e) {
    if (e?.name === 'AbortError') throw new Error('请求超时，请稍后重试或检查模型/工具连接。')
    throw new Error(e?.message || '网络请求失败')
  } finally {
    if (timeoutId) window.clearTimeout(timeoutId)
  }

  if (res.status === 401) {
    auth.logout()
    window.location.href = '/login'
    throw new Error('未登录或登录已过期')
  }
  return res
}

async function parseApiResponse(res) {
  const text = await res.text()
  let data = null
  if (text) {
    try { data = JSON.parse(text) } catch { data = { message: text } }
  }
  const detail = data?.detail || data?.error || data?.message
  if (!res.ok) {
    const message = typeof detail === 'string' ? detail : detail?.message || `请求失败（HTTP ${res.status}）`
    throw new Error(message)
  }
  if (data && data.ok === false) {
    const message = typeof detail === 'string' ? detail : detail?.message || data.message || '操作失败'
    const err = new Error(message)
    err.payload = data
    throw err
  }
  return data
}

const json = (promise) => promise.then(parseApiResponse)
const ASSISTANT_TIMEOUT_MS = 120000

// ============ Auth ============
export const loginApi = (username, password) =>
  fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  }).then(r => r.json())

export const changePasswordApi = (oldPassword, newUsername, newPassword) =>
  authFetch('/api/auth/password', {
    method: 'PUT',
    body: JSON.stringify({ old_password: oldPassword, new_username: newUsername, new_password: newPassword })
  }).then(r => r.json())

// ============ Discover ============
export const getRecommend = () => authFetch('/api/discover/recommend').then(r => r.json())
export const getPersonalized = () => authFetch('/api/discover/personalized').then(r => r.json())
export const getPlaylists = () => authFetch('/api/discover/playlists').then(r => r.json())
export const getToplist = (topid) => authFetch(`/api/discover/toplist${topid ? `?topid=${topid}` : ''}`).then(r => r.json())
export const getPlaylist = (id) => authFetch(`/api/discover/playlist/${id}`).then(r => r.json())
export const parsePlaylistUrl = (url) => authFetch('/api/discover/parse-playlist-url?url=' + encodeURIComponent(url), { method: 'POST' }).then(r => r.json())

// ============ Subscriptions ============
export const getSubs = () => authFetch('/api/subscriptions/').then(r => r.json())
export const addSub = (data) => authFetch('/api/subscriptions/', {
  method: 'POST',
  body: JSON.stringify(data)
}).then(r => r.json())
export const updateSub = (id, data) => authFetch(`/api/subscriptions/${id}`, {
  method: 'PUT',
  body: JSON.stringify(data)
}).then(r => r.json())
export const deleteSub = (id) => authFetch(`/api/subscriptions/${id}`, { method: 'DELETE' }).then(r => r.json())
export const toggleSub = (id) => authFetch(`/api/subscriptions/${id}/toggle`, { method: 'PUT' }).then(r => r.json())

// ============ Search ============
export const searchMusic = (keyword, sites = []) => authFetch('/api/search/', {
  method: 'POST',
  body: JSON.stringify({ keyword, sites })
}).then(r => r.json())

export const searchMusicV2 = (params) => authFetch('/api/search/v2', {
  method: 'POST',
  body: JSON.stringify(params)
}).then(r => r.json())

export const downloadTorrent = (site, torrentId, title) =>
  authFetch(`/api/search/download?site=${encodeURIComponent(site)}&torrent_id=${encodeURIComponent(torrentId)}&title=${encodeURIComponent(title)}`, {
    method: 'POST'
  }).then(r => r.json())

// ============ Online Download ============
export const searchOnlineMusic = (keyword, sources = ['qq', 'migu', 'kugou', 'netease', 'kuwo'], limit = 20) => authFetch('/api/online/search', {
  method: 'POST',
  body: JSON.stringify({ keyword, sources, limit })
}).then(r => r.json())

export const downloadOnlineSong = (song, organize = true) => authFetch('/api/online/download', {
  method: 'POST',
  body: JSON.stringify({ song, organize })
}).then(r => r.json())

// ============ Tasks ============
export const getTasks = () => authFetch('/api/tasks/').then(r => r.json())
export const checkTasks = () => authFetch('/api/tasks/check', { method: 'POST' }).then(r => r.json())
export const previewTaskCleanup = () => authFetch('/api/tasks/cleanup/preview', { method: 'POST' }).then(r => r.json())
export const applyTaskCleanup = (deleteFiles = false) => authFetch(`/api/tasks/cleanup/apply?delete_files=${deleteFiles ? 'true' : 'false'}`, { method: 'POST' }).then(r => r.json())
export const pauseTask = (id) => authFetch(`/api/tasks/${id}/pause`, { method: 'POST' }).then(r => r.json())
export const resumeTask = (id) => authFetch(`/api/tasks/${id}/resume`, { method: 'POST' }).then(r => r.json())
export const retryTask = (id) => authFetch(`/api/tasks/${id}/retry`, { method: 'POST' }).then(r => r.json())
export const deleteTask = (id, deleteFiles = false) => authFetch(`/api/tasks/${id}?delete_files=${deleteFiles ? 'true' : 'false'}`, { method: 'DELETE' }).then(r => r.json())
export const pauseQbTask = (hash) => authFetch(`/api/tasks/qb/${hash}/pause`, { method: 'POST' }).then(r => r.json())
export const resumeQbTask = (hash) => authFetch(`/api/tasks/qb/${hash}/resume`, { method: 'POST' }).then(r => r.json())
export const deleteQbTask = (hash, deleteFiles = false) => authFetch(`/api/tasks/qb/${hash}?delete_files=${deleteFiles ? 'true' : 'false'}`, { method: 'DELETE' }).then(r => r.json())
export const importQbTask = (hash) => authFetch(`/api/tasks/qb/${hash}/import`, { method: 'POST' }).then(r => r.json())
export const organizeQbTask = (hash) => authFetch(`/api/tasks/qb/${hash}/organize`, { method: 'POST' }).then(r => r.json())

// ============ Assistant ============
export const getAssistantCapabilities = () => json(authFetch('/api/assistant/capabilities', { timeoutMs: ASSISTANT_TIMEOUT_MS }))
export const getAssistantProviders = () => json(authFetch('/api/assistant/providers', { timeoutMs: ASSISTANT_TIMEOUT_MS }))
export const getAssistantTools = () => json(authFetch('/api/assistant/tools', { timeoutMs: ASSISTANT_TIMEOUT_MS }))
export const getAssistantActivity = (limit = 50) => json(authFetch(`/api/assistant/activity?limit=${limit}`, { timeoutMs: ASSISTANT_TIMEOUT_MS }))
export const testAssistantProvider = (enabled, provider) => json(authFetch('/api/assistant/providers/test', {
  method: 'POST',
  body: JSON.stringify({ enabled, provider }),
  timeoutMs: ASSISTANT_TIMEOUT_MS
}))
export const getAssistantConversations = () => json(authFetch('/api/assistant/conversations', { timeoutMs: ASSISTANT_TIMEOUT_MS }))
export const createAssistantConversation = (title = '新对话') => json(authFetch('/api/assistant/conversations', {
  method: 'POST',
  body: JSON.stringify({ title }),
  timeoutMs: ASSISTANT_TIMEOUT_MS
}))
export const getAssistantMessages = (id) => json(authFetch(`/api/assistant/conversations/${id}/messages`, { timeoutMs: ASSISTANT_TIMEOUT_MS }))
export const deleteAssistantConversation = (id) => json(authFetch(`/api/assistant/conversations/${id}`, { method: 'DELETE', timeoutMs: ASSISTANT_TIMEOUT_MS }))
export const sendAssistantMessage = (message, conversationId = null) => json(authFetch('/api/assistant/chat', {
  method: 'POST',
  body: JSON.stringify({ message, conversation_id: conversationId }),
  timeoutMs: ASSISTANT_TIMEOUT_MS
}))
export const confirmAssistantAction = (actionId) => json(authFetch(`/api/assistant/actions/${actionId}/confirm`, { method: 'POST', timeoutMs: ASSISTANT_TIMEOUT_MS }))
export const cancelAssistantAction = (actionId) => json(authFetch(`/api/assistant/actions/${actionId}/cancel`, { method: 'POST', timeoutMs: ASSISTANT_TIMEOUT_MS }))

// ============ Library ============
export const getLibraryStats = () => authFetch('/api/library/stats').then(r => r.json())
export const getLibrary = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return authFetch(`/api/library/${qs ? '?' + qs : ''}`).then(r => r.json())
}
export const getLibraryFiles = (params = {}) => {
  const qs = new URLSearchParams({
    limit: 50,
    offset: 0,
    sort: 'track',
    ...params
  }).toString()
  return authFetch(`/api/library/files?${qs}`).then(r => r.json())
}
export const getLibraryAlbums = (params = {}) => {
  const qs = new URLSearchParams({
    limit: 50,
    offset: 0,
    sort: 'updated',
    ...params
  }).toString()
  return authFetch(`/api/library/albums?${qs}`)
    .then(r => r.json())
    .then(data => Array.isArray(data)
      ? { total: data.length, offset: Number(params.offset || 0), limit: Number(params.limit || data.length || 50), items: data }
      : data)
}
export const getLibraryHealth = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return authFetch(`/api/library/health${qs ? '?' + qs : ''}`).then(r => r.json())
}
export const rescanLibraryMetadata = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return authFetch(`/api/library/rescan_metadata${qs ? '?' + qs : ''}`, { method: 'POST' }).then(r => r.json())
}
export const scanLibrary = (payload = {}) => authFetch('/api/library/scan', {
  method: 'POST',
  body: JSON.stringify(payload)
}).then(r => r.json())
export const rescrapeAlbums = (albums, opts = {}) => authFetch('/api/library/rescrape_albums', {
  method: 'POST',
  body: JSON.stringify({ albums, async: opts.async !== false })
}).then(r => r.json())
export const getLibraryJob = (id) => authFetch(`/api/library/jobs/${id}`).then(r => r.json())
export const listLibraryJobs = (limit = 20) => authFetch(`/api/library/jobs?limit=${limit}`).then(r => r.json())
export const getAlbumTracks = (artist, album) =>
  authFetch(`/api/library/album-tracks?artist=${encodeURIComponent(artist)}&album=${encodeURIComponent(album)}`).then(r => r.json())
export const getAlbumCover = (artist, album) =>
  `/api/library/album-cover?artist=${encodeURIComponent(artist)}&album=${encodeURIComponent(album)}`
export const getFile = (id) => authFetch(`/api/library/file/${id}`).then(r => r.json())
export const getStreamUrl = (id) => {
  const token = localStorage.getItem('music_sub_token') || ''
  return `/api/library/stream/${id}?token=${encodeURIComponent(token)}`
}
export const rescrapeLibrary = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return authFetch(`/api/library/rescrape${qs ? '?' + qs : ''}`, { method: 'POST' }).then(r => r.json())
}
export const updateFile = (id, data) => authFetch(`/api/library/file/${id}?${new URLSearchParams(data).toString()}`, { method: 'PUT' }).then(r => r.json())

export const listLibraryTools = () => authFetch('/api/library/tools').then(r => r.json())
export const previewLibraryTool = (toolId, payload) => authFetch(`/api/library/tools/${toolId}/preview`, {
  method: 'POST',
  body: JSON.stringify(payload || {})
}).then(r => r.json())
export const applyLibraryTool = (toolId, payload) => authFetch(`/api/library/tools/${toolId}/apply`, {
  method: 'POST',
  body: JSON.stringify(payload || {})
}).then(r => r.json())

// ============ Settings ============
export const getSettings = () => authFetch('/api/settings/').then(r => r.json())
export const updateSettings = (data) => authFetch('/api/settings/', {
  method: 'PUT',
  body: JSON.stringify(data)
}).then(r => r.json())
export const testQb = () => authFetch('/api/settings/test_qb', { method: 'POST' }).then(r => r.json())
export const testTelegram = () => authFetch('/api/settings/test_telegram', { method: 'POST' }).then(r => r.json())
export const testSite = (name) => authFetch(`/api/settings/test_site/${name}`, { method: 'POST' }).then(r => r.json())
export const getScheduler = () => authFetch('/api/settings/scheduler').then(r => r.json())
export const runScheduler = (id) => authFetch(`/api/settings/scheduler/${id}/run`, { method: 'POST' }).then(r => r.json())

// ============ Logs ============
export const getLogs = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return authFetch(`/api/logs/${qs ? '?' + qs : ''}`).then(r => r.json())
}
export const clearLogs = () => authFetch('/api/logs/', { method: 'DELETE' }).then(r => r.json())