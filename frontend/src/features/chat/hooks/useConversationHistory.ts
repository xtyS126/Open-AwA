import { useCallback, useEffect, useState } from 'react'
import { conversationAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import type { ConversationSessionSummary } from '@/features/chat/types'

export type ConversationSortKey = 'last_message_at' | 'title'

const HISTORY_PAGE_SIZE = 20
const COMPACT_VIEWPORT_WIDTH = 960

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

  const loadConversationList = useCallback(async (page: number = 1, append: boolean = false) => {
    setHistoryLoading(true)
    setHistoryError(null)

    try {
      const response = await conversationAPI.listSessions({
        search: historySearch.trim(),
        sort_by: historySort,
        sort_order: historySort === 'title' ? 'asc' : 'desc',
        page,
        page_size: HISTORY_PAGE_SIZE,
        include_deleted: includeDeleted,
      })

      const incomingItems = response.data.items || []
      const existingItems = append ? useSessionStore.getState().conversations : []
      const nextItems = append ? mergeConversationSummaries(existingItems, incomingItems) : incomingItems
      setConversations(nextItems, response.data.total, response.data.has_more)
      setHistoryPage(response.data.page)
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : '加载历史对话失败')
      appLogger.warning({
        event: 'conversation_list_load_failed',
        module: 'chat_page',
        action: 'load_conversations',
        status: 'failure',
        message: 'failed to load conversations',
      })
    } finally {
      setHistoryLoading(false)
      setHistoryInitialized(true)
    }
  }, [historySearch, historySort, includeDeleted, setConversations])

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