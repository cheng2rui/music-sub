import { defineStore } from 'pinia'
import { reactive, watch } from 'vue'

const ONLINE_KEY = 'music_sub_online_cache'
const PT_KEY = 'music_sub_pt_cache'

function loadState(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback()
    const data = JSON.parse(raw)
    return { ...fallback(), ...data }
  } catch {
    return fallback()
  }
}

function saveState(key, state) {
  try {
    localStorage.setItem(key, JSON.stringify(state))
  } catch {
    // ignore quota / serialization errors
  }
}

function makeHistoryItem(payload) {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    at: Date.now(),
    ...payload,
  }
}

function trimHistory(list, max = 12) {
  return list.slice(0, max)
}

const defaultOnlineState = () => ({
  keyword: '',
  results: [],
  loading: false,
  downloading: '',
  resolving: '',
  downloadMessage: null,
  resolveMessage: null,
  page: 1,
  pageSize: 20,
  filterSource: 'all',
  filterFormat: 'all',
  onlyDownloadable: false,
  searchLimit: 100,
  selectedSources: ['qq', 'migu', 'kugou', 'netease', 'kuwo'],
  history: [],
  downloadHistory: [],
  lastSearchAt: 0,
})

const defaultPtState = () => ({
  keyword: '',
  searchType: 'keyword',
  quality: 'any',
  formatFilter: 'all',
  sortBy: 'score',
  sourceFilter: 'all',
  siteFilter: '',
  onlineSourceFilter: '',
  loading: false,
  downloading: null,
  downloadMessage: null,
  lastResp: null,
  history: [],
  lastSearchAt: 0,
})

export const useSearchCacheStore = defineStore('searchCache', () => {
  const online = reactive({
    ...loadState(ONLINE_KEY, defaultOnlineState),
    // Never restore transient in-flight flags after refresh/navigation.
    loading: false,
    downloading: '',
    resolving: '',
  })
  const pt = reactive({
    ...loadState(PT_KEY, defaultPtState),
    loading: false,
    downloading: null,
    downloadMessage: null,
  })

  watch(online, (val) => saveState(ONLINE_KEY, val), { deep: true })
  watch(pt, (val) => saveState(PT_KEY, val), { deep: true })

  function pushOnlineHistory(entry) {
    online.history = trimHistory([makeHistoryItem(entry), ...(online.history || [])])
  }

  function pushPtHistory(entry) {
    pt.history = trimHistory([makeHistoryItem(entry), ...(pt.history || [])])
  }

  function pushOnlineDownload(entry) {
    online.downloadHistory = trimHistory([makeHistoryItem(entry), ...(online.downloadHistory || [])])
  }

  function rememberOnlineSearch(keyword, summary = {}) {
    online.keyword = keyword || online.keyword
    online.lastSearchAt = Date.now()
    pushOnlineHistory({ keyword, ...summary })
  }

  function rememberPtSearch(keyword, summary = {}) {
    pt.keyword = keyword || pt.keyword
    pt.lastSearchAt = Date.now()
    pushPtHistory({ keyword, ...summary })
  }

  function clearOnlineMessages() {
    online.downloadMessage = null
    online.resolveMessage = null
  }

  function setOnlineState(patch = {}) {
    Object.assign(online, patch)
  }

  function setPtState(patch = {}) {
    Object.assign(pt, patch)
  }

  function resetOnlineResults(keepKeyword = true) {
    const keyword = keepKeyword ? online.keyword : ''
    Object.assign(online, defaultOnlineState(), { keyword })
  }

  function resetPtResults(keepKeyword = true) {
    const keyword = keepKeyword ? pt.keyword : ''
    Object.assign(pt, defaultPtState(), { keyword })
  }

  return {
    online,
    pt,
    pushOnlineHistory,
    pushPtHistory,
    pushOnlineDownload,
    rememberOnlineSearch,
    rememberPtSearch,
    clearOnlineMessages,
    setOnlineState,
    setPtState,
    resetOnlineResults,
    resetPtResults,
  }
})
