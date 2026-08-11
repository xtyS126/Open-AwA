/**
 * 聊天会话生命周期与 CRUD 动作 Hook。
 *
 * 将 ChatPage 中与"会话增删改查/路由跳转/历史拉取/初始化"相关的副作用与回调
 * 集中管理，使 ChatPage 主组件聚焦于消息流式与渲染编排。
 *
 * 包含：
 * 1. 会话创建/恢复/重命名/删除/批量删除/restore
 * 2. 路由参数变化时的 session 同步
 * 3. 历史缺失时回退到 fallback 会话
 * 4. 会话路由变化时拉取历史消息
 * 5. handleRegenerate：基于现有用户消息重新生成（创建新会话后转发到 handleSend）
 *
 * 防重复与并发控制：
 * - pendingConversationCreationRef 防止并发创建会话
 * - 删除/批量删除前先计算 nextCandidate，避免 UI 空白
 */
import { useCallback, useEffect, useRef } from 'react'
import { useNavigate } from '@/shared/routing'
import { chatAPI, conversationAPI } from '@/shared/api/api'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useToast } from '@/shared/components/Toast'
import { appLogger } from '@/shared/utils/logger'
import type { ChatMessage, ConversationSessionSummary } from '@/features/chat/types'
import { useConversationListActions } from './useConversationListActions'

/** useChatConversationActions 入参 */
export interface UseChatConversationActionsParams {
  /** 当前路由参数中的 conversationId */
  conversationId: string | undefined
  /** 当前活跃 sessionId（'default' 表示无活跃会话） */
  sessionId: string
  /** 全部会话列表（已过滤已删除项的可视列表） */
  conversations: ConversationSessionSummary[]
  /** 是否包含已删除会话（影响删除后的列表更新策略） */
  includeDeleted: boolean
  /** 历史记录侧栏是否已初始化 */
  historyInitialized: boolean
  /** 历史记录是否正在加载 */
  historyLoading: boolean
  /** 历史记录当前页码 */
  historyPage: number
  /** 是否还有更多历史记录可加载 */
  conversationsHasMore: boolean
  /** 是否为紧凑视口（移动端） */
  isCompactViewport: boolean
  /** 加载会话列表分页 */
  loadConversationList: (page: number, append: boolean, force?: boolean) => Promise<void>
  /** 关闭历史记录侧栏（移动端选择会话后调用） */
  closeHistorySidebar: () => void
  /** 清空历史记录加载错误状态（创建新会话时调用） */
  clearHistoryError: () => void
  /** store 动作：设置 sessionId */
  setSessionId: (sessionId: string) => void
  /** store 动作：设置消息列表 */
  setMessages: (messages: ChatMessage[]) => void
  /** store 动作：upsert 会话 */
  upsertConversation: (conversation: ConversationSessionSummary) => void
  /** store 动作：移除会话 */
  removeConversation: (sessionId: string) => void
  /** 流式执行状态重置 */
  resetStreamExecutionState: () => void
  /** 任务面板状态重置 */
  resetTaskPanelState: () => void
  /** 设置 messageMeta（本地状态） */
  setMessageMeta: React.Dispatch<React.SetStateAction<Record<string, import('@/features/chat/types').AssistantExecutionMeta>>>
  /** 设置 streamingAssistantId（本地状态） */
  setStreamingAssistantId: React.Dispatch<React.SetStateAction<string | null>>
  /** 设置 feedbackState（本地状态） */
  setFeedbackState: React.Dispatch<React.SetStateAction<Record<string, 1 | -1 | undefined>>>
  /** 跨标签页广播：会话变更 */
  broadcastConversationChange: () => void
  /** 缓存：从本地恢复消息列表 */
  getLocalMessagesForRestore: (sessionId: string) => ChatMessage[]
  /** 缓存：合并服务端历史与本地缓存 */
  mergeServerHistoryWithCached: (server: ChatMessage[], cached: ChatMessage[]) => ChatMessage[]
  /** 缓存：清空当前会话缓存 */
  flushConversationCache: () => void
  /** 缓存：从本地存储读取持久化的活跃会话 ID */
  getActiveConversationId: () => string | undefined
  /** 缓存：基于消息列表构建执行元数据 */
  buildMessageMetaFromMessages: (messages: ChatMessage[]) => Record<string, import('@/features/chat/types').AssistantExecutionMeta>
  /**
   * handleSend 的 ref 镜像，供 handleRegenerate 调用。
   * 通过 ref 读取避免 useCallback 依赖 handleSend 导致引用频繁变化。
   */
  handleSendRef: React.MutableRefObject<((message?: string, attachments?: unknown[]) => Promise<void>) | undefined>
}

/** useChatConversationActions 返回值 */
export interface UseChatConversationActionsReturn {
  /** 重新生成：基于 messageId 找到上一条用户消息，在新会话中重新发送 */
  handleRegenerate: (messageId: string) => Promise<void>
  /** 主动创建新对话（点击「新对话」按钮） */
  handleCreateConversation: () => Promise<void>
  /** 侧栏点击新建会话按钮 */
  handleSidebarCreateConversation: () => void
  /** 选择会话（侧栏点击） */
  handleSelectConversation: (nextSessionId: string) => void
  /** 重命名会话 */
  handleRenameConversation: (targetSessionId: string, title: string) => Promise<void>
  /** 请求删除会话（弹出确认对话框） */
  handleDeleteConversation: (targetSessionId: string) => void
  /** 取消删除会话 */
  cancelDeleteConversation: () => void
  /** 确认删除会话 */
  confirmDeleteConversation: () => void
  /** 恢复已删除会话 */
  handleRestoreConversation: (targetSessionId: string) => Promise<void>
  /** 加载更多会话（分页） */
  handleLoadMoreConversations: () => void
  /** 请求批量删除会话（弹出确认对话框，不直接执行） */
  handleBatchDeleteConversations: (sessionIds: string[]) => void
  /** 取消批量删除 */
  cancelBatchDeleteConversations: () => void
  /** 确认批量删除 */
  confirmBatchDeleteConversations: () => void
  /** 当前待确认删除的会话 ID（用于渲染确认对话框） */
  pendingDeleteSessionId: string | null
  /** 当前待确认批量删除的会话 ID 列表（用于渲染确认对话框） */
  pendingBatchDeleteIds: string[] | null
  /** 确保当前有活跃会话，无则创建（供 handleSend 调用） */
  ensureConversationSession: () => Promise<string>
}

/**
 * 聊天会话生命周期与 CRUD 动作 Hook。
 *
 * 调用方传入 store 动作与缓存方法，本 hook 内部管理并发创建守卫与
 * 待删除会话状态，并返回所有会话相关回调。
 */
export function useChatConversationActions({
  conversationId,
  sessionId,
  conversations,
  includeDeleted,
  historyInitialized,
  historyLoading,
  historyPage,
  conversationsHasMore,
  isCompactViewport,
  loadConversationList,
  closeHistorySidebar,
  clearHistoryError,
  setSessionId,
  setMessages,
  upsertConversation,
  removeConversation,
  resetStreamExecutionState,
  resetTaskPanelState,
  setMessageMeta,
  setStreamingAssistantId,
  setFeedbackState,
  broadcastConversationChange,
  getLocalMessagesForRestore,
  mergeServerHistoryWithCached,
  flushConversationCache,
  getActiveConversationId,
  buildMessageMetaFromMessages,
  handleSendRef,
}: UseChatConversationActionsParams): UseChatConversationActionsReturn {
  const navigate = useNavigate()
  // 会话被删除/不可达时，重定向需给用户可见提示（toast），不能静默跳转
  const { addToast } = useToast()
  // 并发创建守卫：同一时间只允许一个 createSession 请求
  const pendingConversationCreationRef = useRef<Promise<string> | null>(null)

  const createConversationAndNavigate = useCallback(async (replace: boolean = false) => {
    if (pendingConversationCreationRef.current) {
      return pendingConversationCreationRef.current
    }

    const pendingRequest = (async () => {
      clearHistoryError()
      const response = await conversationAPI.createSession()
      const nextConversation = response.data as ConversationSessionSummary
      upsertConversation(nextConversation)
      setSessionId(nextConversation.session_id)
      setMessages([])
      setMessageMeta({})
      setStreamingAssistantId(null)
      resetStreamExecutionState()
      navigate(`/assistant/sessions/${nextConversation.session_id}`, { replace })
      // 广播会话列表变更到其他标签页
      broadcastConversationChange()
      return nextConversation.session_id
    })()

    pendingConversationCreationRef.current = pendingRequest

    try {
      return await pendingRequest
    } finally {
      pendingConversationCreationRef.current = null
    }
  }, [broadcastConversationChange, clearHistoryError, navigate, resetStreamExecutionState, setMessages, setSessionId, setMessageMeta, setStreamingAssistantId, upsertConversation])

  const ensureConversationSession = useCallback(async () => {
    if (sessionId && sessionId !== 'default') {
      return sessionId
    }
    return createConversationAndNavigate(!conversationId)
  }, [conversationId, createConversationAndNavigate, sessionId])

  const recoverUnavailableConversation = useCallback(async (missingSessionId: string) => {
    removeConversation(missingSessionId)
    setMessages([])
    setMessageMeta({})
    setStreamingAssistantId(null)
    resetStreamExecutionState()
    // 会话被移除后广播变更到其他标签页
    broadcastConversationChange()

    const fallbackConversation = useSessionStore.getState().conversations.find(
      (item) => item.session_id !== missingSessionId && !item.deleted_at
    )

    // 重定向必须用户可见提示：原会话已不存在，避免用户不知情地丢失上下文
    addToast('原会话已不存在，已切换到其他会话', 'warning')

    if (fallbackConversation) {
      navigate(`/assistant/sessions/${fallbackConversation.session_id}`, { replace: true })
      return
    }

    await createConversationAndNavigate(true)
  }, [addToast, broadcastConversationChange, createConversationAndNavigate, navigate, removeConversation, resetStreamExecutionState, setMessageMeta, setMessages, setStreamingAssistantId])

  // 路由 conversationId 变化时同步 sessionId
  useEffect(() => {
    if (conversationId && conversationId !== sessionId) {
      // 仅调用 setSessionId，其内部已包含 loadMessages 逻辑
      // 移除 loadCachedMessages 调用，避免与 setSessionId 内部的 loadMessages 产生竞态
      setSessionId(conversationId)
      setMessageMeta({})
      setStreamingAssistantId(null)
      setFeedbackState({})
      resetStreamExecutionState()
    }
  }, [conversationId, resetStreamExecutionState, sessionId, setSessionId, setMessageMeta, setStreamingAssistantId, setFeedbackState])

  // 历史侧栏初始化完成后，若无活跃会话则尝试恢复持久化的会话或创建新会话
  useEffect(() => {
    if (!historyInitialized || conversationId || (sessionId && sessionId !== 'default')) {
      return
    }

    const persistedSessionId = getActiveConversationId()
    const availableConversations = conversations.filter((item) => includeDeleted || !item.deleted_at)
    const nextConversation = availableConversations.find((item) => item.session_id === persistedSessionId) || availableConversations[0]
    if (nextConversation) {
      navigate(`/assistant/sessions/${nextConversation.session_id}`, { replace: true })
      return
    }

    void createConversationAndNavigate(true)
  }, [conversationId, conversations, createConversationAndNavigate, historyInitialized, includeDeleted, navigate, sessionId, getActiveConversationId])

  // 加载历史消息：sessionId 变化时拉取对应历史并合并本地缓存
  useEffect(() => {
    if (!historyInitialized) {
      return
    }

    if (!sessionId || sessionId === 'default') {
      setMessages([])
      setMessageMeta({})
      resetStreamExecutionState()
      return
    }
    let cancelled = false
    const loadHistory = async () => {
      try {
        const response = await chatAPI.getHistory(sessionId)
        if (cancelled) return
        const history = response.data
        if (Array.isArray(history)) {
          const restored = history.filter(Boolean).map((msg: {
            id?: string | number
            role: string
            content: string
            timestamp?: string
            reasoning_content?: string | null
            toolEvents?: unknown
            segments?: import('@/features/chat/types').AssistantMessageSegment[]
          }) => ({
            id: msg.id?.toString() || crypto.randomUUID(),
            role: msg.role as 'user' | 'assistant',
            content: msg.content,
            reasoning_content: typeof msg.reasoning_content === 'string' ? msg.reasoning_content : undefined,
            timestamp: msg.timestamp ? new Date(msg.timestamp) : new Date(),
            toolEvents: Array.isArray(msg.toolEvents) ? msg.toolEvents : undefined,
            segments: Array.isArray(msg.segments) ? msg.segments : undefined,
          }))
          const cachedMessages = getLocalMessagesForRestore(sessionId)
          const mergedMessages = mergeServerHistoryWithCached(restored, cachedMessages)
          setMessages(mergedMessages)
          setMessageMeta(buildMessageMetaFromMessages(mergedMessages))
          flushConversationCache()
          appLogger.info({
            event: 'chat_history_loaded',
            module: 'chat_page',
            action: 'load_history',
            status: 'success',
            message: `loaded ${mergedMessages.length} history messages`,
          })
        }
      } catch (error) {
        if (cancelled) return

        const statusCode = (error as { response?: { status?: number } })?.response?.status
        if (statusCode === 404 && useSessionStore.getState().sessionId === sessionId) {
          appLogger.warning({
            event: 'chat_history_missing',
            module: 'chat_page',
            action: 'load_history',
            status: 'warning',
            message: 'conversation history not found, recovering route',
            extra: { session_id: sessionId },
          })
          void recoverUnavailableConversation(sessionId)
          return
        }

        appLogger.warning({
          event: 'chat_history_load_failed',
          module: 'chat_page',
          action: 'load_history',
          status: 'failure',
          message: 'failed to load chat history',
        })
      }
    }
    loadHistory()
    return () => { cancelled = true }
  }, [flushConversationCache, historyInitialized, recoverUnavailableConversation, resetStreamExecutionState, sessionId, setMessages, setMessageMeta, getLocalMessagesForRestore, mergeServerHistoryWithCached, buildMessageMetaFromMessages])

  const handleRegenerate = useCallback(async (messageId: string) => {
    const currentMessages = useSessionStore.getState().messages
    const msgIndex = currentMessages.findIndex((m) => m.id === messageId)
    if (msgIndex === -1) return

    const messagesBefore = currentMessages.slice(0, msgIndex)
    const lastUserMsg = [...messagesBefore].reverse().find((m) => m.role === 'user')
    if (!lastUserMsg) return

    const lastUserMsgIndex = messagesBefore.findIndex((m) => m.id === lastUserMsg.id)
    const preservedMessages = messagesBefore.slice(0, lastUserMsgIndex)

    // 先创建新会话（无论是否有旧会话都需要新会话）
    const response = await conversationAPI.createSession()
    const newConv = response.data as ConversationSessionSummary
    upsertConversation(newConv)
    setSessionId(newConv.session_id)

    // 新会话创建成功后再删除旧会话，避免创建失败导致数据丢失
    if (sessionId && sessionId !== 'default') {
      try {
        await conversationAPI.deleteSession(sessionId, 1)
        removeConversation(sessionId)
      } catch {
        /* 旧会话删除失败不影响后续流程 */
      }
    }

    setMessages(preservedMessages)
    setMessageMeta({})
    setStreamingAssistantId(null)
    resetStreamExecutionState()
    resetTaskPanelState()
    navigate(`/assistant/sessions/${newConv.session_id}`, { replace: true })
    // 重新生成会话涉及会话增删，广播变更到其他标签页
    broadcastConversationChange()

    void handleSendRef.current?.(lastUserMsg.content, [])
  }, [broadcastConversationChange, sessionId, removeConversation, upsertConversation, setSessionId, setMessages, setMessageMeta, setStreamingAssistantId, resetStreamExecutionState, resetTaskPanelState, navigate, handleSendRef])

  const handleCreateConversation = useCallback(async () => {
    setMessageMeta({})
    setStreamingAssistantId(null)
    resetStreamExecutionState()
    resetTaskPanelState()
    await createConversationAndNavigate(false)
  }, [createConversationAndNavigate, resetStreamExecutionState, resetTaskPanelState, setMessageMeta, setStreamingAssistantId])

  const handleSidebarCreateConversation = useCallback(() => {
    void handleCreateConversation()
  }, [handleCreateConversation])

  const handleSelectConversation = useCallback((nextSessionId: string) => {
    if (!nextSessionId || nextSessionId === sessionId) {
      if (isCompactViewport) {
        closeHistorySidebar()
      }
      return
    }
    setMessageMeta({})
    setStreamingAssistantId(null)
    resetStreamExecutionState()
    resetTaskPanelState()
    navigate(`/assistant/sessions/${nextSessionId}`)
    if (isCompactViewport) {
      closeHistorySidebar()
    }
  }, [closeHistorySidebar, isCompactViewport, navigate, resetStreamExecutionState, resetTaskPanelState, sessionId, setMessageMeta, setStreamingAssistantId])

  const {
    handleRenameConversation,
    handleDeleteConversation,
    cancelDeleteConversation,
    confirmDeleteConversation,
    handleRestoreConversation,
    handleLoadMoreConversations,
    handleBatchDeleteConversations,
    cancelBatchDeleteConversations,
    confirmBatchDeleteConversations,
    pendingDeleteSessionId,
    pendingBatchDeleteIds,
  } = useConversationListActions({
    conversations,
    activeSessionId: sessionId,
    includeDeleted,
    loading: historyLoading,
    page: historyPage,
    hasMore: conversationsHasMore,
    loadConversationList,
    upsertConversation,
    removeConversation,
    broadcastConversationChange,
    onActiveConversationDeleted: async (nextConversation) => {
      if (nextConversation) {
        navigate(`/assistant/sessions/${nextConversation.session_id}`, { replace: true })
      } else {
        await createConversationAndNavigate(true)
      }
    },
    onConversationRestored: (restoredSessionId) => {
      if (!sessionId || sessionId === 'default') {
        navigate(`/assistant/sessions/${restoredSessionId}`, { replace: true })
      }
    },
  })

  return {
    ensureConversationSession,
    handleRegenerate,
    handleCreateConversation,
    handleSidebarCreateConversation,
    handleSelectConversation,
    handleRenameConversation,
    handleDeleteConversation,
    cancelDeleteConversation,
    confirmDeleteConversation,
    handleRestoreConversation,
    handleLoadMoreConversations,
    handleBatchDeleteConversations,
    cancelBatchDeleteConversations,
    confirmBatchDeleteConversations,
    pendingDeleteSessionId,
    pendingBatchDeleteIds,
  }
}
