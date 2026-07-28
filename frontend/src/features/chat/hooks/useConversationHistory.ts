import { useCallback, useEffect, useRef, useState } from 'react'
import { conversationAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import type { ConversationSessionSummary } from '@/features/chat/types'
import { isAxiosError } from 'axios'

export type ConversationSortKey = 'last_message_at' | 'title'

const HISTORY_PAGE_SIZE = 20
const COMPACT_VIEWPORT_WIDTH = 960

/**
 * 模块级 stale-while-revalidate 缓存：避免 StrictMode 双 mount、conversationsVersion
 * 广播、操作后刷新等场景重复拉取 /api/conversations。
 *
 * 缓存键：search + sort + includeDeleted + page
 * 缓存有效期：5 秒，期间相同参数的请求直接跳过（force=true 时强制刷新）
 */
const CONVERSATION_LIST_CACHE_TTL_MS = 5000
interface ConversationListCacheKey {
  search: string
  sort: ConversationSortKey
  includeDeleted: boolean
  page: number
}
let _conversationListCache: { key: ConversationListCacheKey; ts: number } | null = null

function makeCacheKey(
  search: string,
  sort: ConversationSortKey,
  includeDeleted: boolean,
  page: number
): ConversationListCacheKey {
  return { search, sort, includeDeleted, page }
}

function isCacheFresh(key: ConversationListCacheKey, now: number): boolean {
  if (!_conversationListCache) return false
  if (
    _conversationListCache.key.search !== key.search ||
    _conversationListCache.key.sort !== key.sort ||
    _conversationListCache.key.includeDeleted !== key.includeDeleted ||
    _conversationListCache.key.page !== key.page
  ) {
    return false
  }
  return now - _conversationListCache.ts < CONVERSATION_LIST_CACHE_TTL_MS
}

function updateCache(key: ConversationListCacheKey, ts: number): void {
  _conversationListCache = { key, ts }
}

/**
 * 重置模块级 stale-while-revalidate 缓存，仅供测试使用。
 *
 * 测试用例间需要清空缓存，避免前一个用例填充的缓存导致后续用例跳过
 * API 调用（进而导致 mock 断言失败）。
 */
export function __resetConversationListCacheForTests(): void {
  _conversationListCache = null
}

function getIsCompactViewport(): boolean {
  return window.innerWidth <= COMPACT_VIEWPORT_WIDTH
}

function mergeConversationSummaries(
  currentItems: ConversationSessionSummary[],
  nextItems: ConversationSessionSummary[]
): ConversationSessionSummary[] {
  const nextMap = new Map<string, ConversationSessionSummary>()
  for (const item of currentItems) {
    nextMap.set(item.session_id, item)
  }
  for (const item of nextItems) {
    nextMap.set(item.session_id, item)
  }
  return Array.from(nextMap.values())
}

/**
 * 统一管理聊天页历史侧栏的视口状态、筛选条件与列表加载逻辑。
 */
export function useConversationHistory() {
  const setConversations = useSessionStore((state) => state.setConversations)
  // 跨标签页会话变更版本号：变化时重新加载会话列表
  const conversationsVersion = useSessionStore((state) => state.conversationsVersion)
  const [isCompactViewport, setIsCompactViewport] = useState(getIsCompactViewport)
  const [historySidebarOpen, setHistorySidebarOpen] = useState(() => !getIsCompactViewport())
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historySearchInput, setHistorySearchInput] = useState('')
  const [historySearch, setHistorySearch] = useState('')
  const [historySort, setHistorySort] = useState<ConversationSortKey>('last_message_at')
  const [historyPage, setHistoryPage] = useState(1)
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [historyInitialized, setHistoryInitialized] = useState(false)

  const toggleHistorySidebar = useCallback(() => {
    setHistorySidebarOpen((current) => !current)
  }, [])

  const closeHistorySidebar = useCallback(() => {
    setHistorySidebarOpen(false)
  }, [])

  const clearHistoryError = useCallback(() => {
    setHistoryError(null)
  }, [])

  useEffect(() => {
    setHistorySidebarOpen(!isCompactViewport)
  }, [isCompactViewport])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setHistorySearch(historySearchInput)
    }, 250)

    return () => {
      window.clearTimeout(timer)
    }
  }, [historySearchInput])

  useEffect(() => {
    const handleResize = () => {
      setIsCompactViewport(getIsCompactViewport())
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // 当前在飞的 listSessions 请求的 AbortController；组件卸载或参数变化时主动 abort，
  // 避免请求继续占用浏览器连接池直到 axios 30s 超时（P0 修复：页面切换快导致
  // /conversations 请求 timeout of 30000ms exceeded）
  const inflightListRef = useRef<AbortController | null>(null)

  const loadConversationList = useCallback(async (page: number = 1, append: boolean = false, force: boolean = false) => {
    // stale-while-revalidate：5 秒内相同参数的请求跳过，避免重复拉取
    // force=true 时跳过缓存（用于用户主动操作如创建/删除/重命名会话后的强制刷新）
    const cacheKey = makeCacheKey(historySearch.trim(), historySort, includeDeleted, page)
    if (!append && !force && isCacheFresh(cacheKey, Date.now())) {
      return
    }

    // 取消前一个在飞请求，避免并发请求堆积占用浏览器连接池
    if (inflightListRef.current) {
      inflightListRef.current.abort()
    }
    const abortController = new AbortController()
    inflightListRef.current = abortController

    setHistoryLoading(true)
    setHistoryError(null)

    try {
      const response = await conversationAPI.listSessions(
        {
          search: historySearch.trim(),
          sort_by: historySort,
          sort_order: historySort === 'title' ? 'asc' : 'desc',
          page,
          page_size: HISTORY_PAGE_SIZE,
          include_deleted: includeDeleted,
        },
        abortController.signal
      )

      const incomingItems = response.data.items || []
      const existingItems = append ? useSessionStore.getState().conversations : []
      const nextItems = append ? mergeConversationSummaries(existingItems, incomingItems) : incomingItems
      setConversations(nextItems, response.data.total, response.data.has_more)
      setHistoryPage(response.data.page)
      // 仅成功路径更新缓存时间戳
      if (!append) {
        updateCache(cacheKey, Date.now())
      }
    } catch (error) {
      // 组件卸载或参数变化触发的 abort 是预期行为，不当作错误处理
      if (isAxiosError(error) && error.code === 'ERR_CANCELED') {
        return
      }
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      setHistoryError(error instanceof Error ? error.message : '加载历史对话失败')
      appLogger.warning({
        event: 'conversation_list_load_failed',
        module: 'chat_page',
        action: 'load_conversations',
        status: 'failure',
        message: 'failed to load conversations',
      })
    } finally {
      // 仅当当前请求仍是本 controller 时清理引用，避免被后续请求覆盖后误清
      if (inflightListRef.current === abortController) {
        inflightListRef.current = null
      }
      setHistoryLoading(false)
      setHistoryInitialized(true)
    }
  }, [historySearch, historySort, includeDeleted, setConversations])

  useEffect(() => {
    void loadConversationList(1, false)
    // 组件卸载时 abort 在飞请求，避免请求继续占用浏览器连接池直到 axios 30s 超时
    return () => {
      if (inflightListRef.current) {
        inflightListRef.current.abort()
        inflightListRef.current = null
      }
    }
  }, [historySearch, historySort, includeDeleted, loadConversationList])

  // 跨标签页会话变更监听：当其他标签页广播会话变更导致 conversationsVersion 自增时，
  // 重新加载会话列表。使用 ref 记录上一次版本号，避免初始挂载时触发重复加载。
  const prevConversationsVersionRef = useRef(conversationsVersion)
  useEffect(() => {
    if (prevConversationsVersionRef.current === conversationsVersion) {
      return
    }
    prevConversationsVersionRef.current = conversationsVersion
    // 仅在初始化完成后才响应版本变化，避免与初始加载竞态
    if (!historyInitialized) {
      return
    }
    // 跨标签页变更强制刷新，跳过 stale-while-revalidate 缓存
    void loadConversationList(1, false, true)
  }, [conversationsVersion, loadConversationList, historyInitialized])

  return {
    isCompactViewport,
    historySidebarOpen,
    historyLoading,
    historyError,
    historySearchInput,
    historySort,
    historyPage,
    includeDeleted,
    historyInitialized,
    setHistorySearchInput,
    setHistorySort,
    setIncludeDeleted,
    toggleHistorySidebar,
    closeHistorySidebar,
    clearHistoryError,
    loadConversationList,
  }
}
