import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PanelLeft } from 'lucide-react'
import { chatAPI, conversationAPI, diaryAPI } from '@/shared/api/api'
import { useConversationHistory } from '@/features/chat/hooks/useConversationHistory'
import { useStreamExecutionState } from '@/features/chat/hooks/useStreamExecutionState'
import { useTaskPanelState } from '@/features/chat/hooks/useTaskPanelState'
import { useChatStore } from '@/features/chat/store/chatStore'
import { shallow } from 'zustand/shallow'
import {
  applyToolPatchToSegments,
} from '@/features/chat/utils/assistantSegments'
import { applySubagentStop, applyToolUpdate } from '@/features/chat/utils/executionMeta'
import { stopAgent } from '@/shared/api/taskRuntimeApi'
import { useI18nStore } from '@/i18n'
import { appLogger } from '@/shared/utils/logger'
import { useToast } from '@/shared/components/Toast'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { useChatStream } from './hooks/useChatStream'
import { useSubagentSync } from './hooks/useSubagentSync'
import { useMessageCache } from './hooks/useMessageCache'
import { usePermissionRequest } from './hooks/usePermissionRequest'
import ConversationSidebar from './components/ConversationSidebar'
import { MessageList } from './components/MessageList'
import { ChatInput } from './components/ChatInput'
import { PermissionRequestNotification } from './components/PermissionRequestNotification'
import type { FileAttachment } from './components/ChatInput'
// P1: TaskPanel/TodoPanel 按需懒加载，减少聊天页首屏 JS
const TaskPanel = React.lazy(() => import('./components/TaskPanel').then(m => ({ default: m.TaskPanel })))
const TodoPanel = React.lazy(() => import('./components/TodoPanel').then(m => ({ default: m.TodoPanel })))
import type { TodoItem } from './components/TodoPanel'
import styles from './ChatPage.module.css'

function ChatPage() {
  const navigate = useNavigate()
  const { t } = useI18nStore()
  const { conversationId } = useParams<{ conversationId?: string }>()
  // 原子化 store selector：避免流式输出期间 messages 等高频字段变化导致整个聊天页重渲染
  // 数组/对象字段使用 shallow 做浅比较，避免内容相同时的假阳性重渲染
  const messages = useChatStore(s => s.messages, shallow)
  const conversations = useChatStore(s => s.conversations, shallow)
  // 标量字段使用简单 selector（默认 === 比较）
  const isLoading = useChatStore(s => s.isLoading)
  const sessionId = useChatStore(s => s.sessionId)
  const outputMode = useChatStore(s => s.outputMode)
  const selectedModel = useChatStore(s => s.selectedModel)
  const conversationsHasMore = useChatStore(s => s.conversationsHasMore)
  const thinkingEnabled = useChatStore(s => s.thinkingEnabled)
  const thinkingDepth = useChatStore(s => s.thinkingDepth)
  // Actions — 在 create() 中定义后引用永不变，单独提取避免触发数据订阅
  const setLoading = useChatStore(s => s.setLoading)
  const setSessionId = useChatStore(s => s.setSessionId)
  const setOutputMode = useChatStore(s => s.setOutputMode)
  const setMessages = useChatStore(s => s.setMessages)
  const updateMessage = useChatStore(s => s.updateMessage)
  const upsertConversation = useChatStore(s => s.upsertConversation)
  const removeConversation = useChatStore(s => s.removeConversation)
  const setThinkingEnabled = useChatStore(s => s.setThinkingEnabled)
  const setThinkingDepth = useChatStore(s => s.setThinkingDepth)
  const resetActiveToolCalls = useChatStore(s => s.resetActiveToolCalls)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const isMountedRef = useRef(true)
  const pendingConversationCreationRef = useRef<Promise<string> | null>(null)
  const [messageMeta, setMessageMeta] = useState<Record<string, import('@/features/chat/types').AssistantExecutionMeta>>({})
  const [streamingAssistantId, setStreamingAssistantId] = useState<string | null>(null)
  const [editContent, setEditContent] = useState<string>('')
  const [shouldFocusInput, setShouldFocusInput] = useState<number>(0)
  const [feedbackState, setFeedbackState] = useState<Record<string, 1 | -1 | undefined>>({})
  const {
    streamConnectionState,
    streamStatusText,
    setStreamStageMessage,
    beginStreamExecution,
    markStreamRetrying,
    markStreamStreaming,
    markStreamFailed,
    clearStreamStageMessage,
    setIdleStreamState,
    resetStreamExecutionState,
  } = useStreamExecutionState()
  const [todoItems, setTodoItems] = useState<TodoItem[]>([])
  const [todoSummary, setTodoSummary] = useState<string>('')
  const [aborting, setAborting] = useState<boolean>(false)
  const [showAbortConfirm, setShowAbortConfirm] = useState<boolean>(false)
  /* 删除会话确认状态 */
  const [pendingDeleteSessionId, setPendingDeleteSessionId] = useState<string | null>(null)
  /* 批量删除会话确认状态（预留） */
  // const [pendingBatchDeleteIds, setPendingBatchDeleteIds] = useState<string[] | null>(null)
  const {
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
  } = useConversationHistory()
  const {
    activeExecution,
    taskPanelExpanded,
    toggleTaskPanel,
    resetTaskPanelState,
  } = useTaskPanelState(messages, messageMeta, streamingAssistantId)
  const { addToast, ToastContainer } = useToast()
  const messageMetaRef = useRef<Record<string, import('@/features/chat/types').AssistantExecutionMeta>>({})

  // 权限请求实时推送
  const {
    pendingRequests: permissionRequests,
    approve: approvePermission,
    approveAlways: approveAlwaysPermission,
    deny: denyPermission,
  } = usePermissionRequest(sessionId)

  const {
    getLocalMessagesForRestore,
    buildMessageMetaFromMessages,
    mergeServerHistoryWithCached,
    flushConversationCache,
    getActiveConversationId,
  } = useMessageCache()

  const appendAssistantMessageText = useCallback((assistantMessageId: string, content: string, reasoningContent?: string) => {
    if (!content && !reasoningContent) {
      return
    }

    updateMessage(assistantMessageId, (message) => {
      if (message.role !== 'assistant') {
        return message
      }

      return {
        ...message,
        content: message.content + content,
        reasoning_content: (thinkingEnabled && reasoningContent)
          ? (message.reasoning_content || '') + reasoningContent
          : message.reasoning_content,
      }
    })
  }, [thinkingEnabled, updateMessage])

  const bufferRef = useRef({
    content: '',
    reasoning: '',
    lastUpdateTime: Date.now()
  })

  const flushBuffer = useCallback((assistantMessageId?: string) => {
    const targetMessageId = assistantMessageId || streamingAssistantId
    if (!targetMessageId) {
      return
    }
    if (bufferRef.current.content || bufferRef.current.reasoning) {
      appendAssistantMessageText(targetMessageId, bufferRef.current.content, bufferRef.current.reasoning)
      bufferRef.current.content = ''
      bufferRef.current.reasoning = ''
      bufferRef.current.lastUpdateTime = Date.now()
    }
  }, [appendAssistantMessageText, streamingAssistantId])

  const scrollToBottom = useCallback(() => {
    if (document.hidden) return
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  // P0: 仅在新消息增加时触发自动滚动，不再因 messageMeta 变化频繁滚动
  useEffect(() => {
    scrollToBottom()
  }, [messages.length, scrollToBottom])

  useEffect(() => {
    messageMetaRef.current = messageMeta
  }, [messageMeta])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        flushBuffer()
        setTimeout(scrollToBottom, 50)
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [flushBuffer, scrollToBottom])

  useEffect(() => {
    appLogger.info({
      event: 'page_view',
      module: 'chat_page',
      action: 'mount',
      status: 'success',
      message: 'chat page mounted',
    })
  }, [])

  const createConversationAndNavigate = useCallback(async (replace: boolean = false) => {
    if (pendingConversationCreationRef.current) {
      return pendingConversationCreationRef.current
    }

    const pendingRequest = (async () => {
      clearHistoryError()
      const response = await conversationAPI.createSession()
      const nextConversation = response.data as import('@/features/chat/types').ConversationSessionSummary
      upsertConversation(nextConversation)
      setSessionId(nextConversation.session_id)
      setMessages([])
      setMessageMeta({})
      setStreamingAssistantId(null)
      resetStreamExecutionState()
      navigate(`/chat/${nextConversation.session_id}`, { replace })
      return nextConversation.session_id
    })()

    pendingConversationCreationRef.current = pendingRequest

    try {
      return await pendingRequest
    } finally {
      pendingConversationCreationRef.current = null
    }
  }, [clearHistoryError, navigate, resetStreamExecutionState, setMessages, setSessionId, upsertConversation])

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

    const fallbackConversation = useChatStore.getState().conversations.find(
      (item) => item.session_id !== missingSessionId && !item.deleted_at
    )

    if (fallbackConversation) {
      navigate(`/chat/${fallbackConversation.session_id}`, { replace: true })
      return
    }

    await createConversationAndNavigate(true)
  }, [createConversationAndNavigate, navigate, removeConversation, resetStreamExecutionState, setMessages])

  useEffect(() => {
    void loadConversationList(1, false)
  }, [loadConversationList])

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
  }, [conversationId, resetStreamExecutionState, sessionId, setSessionId])

  useEffect(() => {
    if (!historyInitialized || conversationId || (sessionId && sessionId !== 'default')) {
      return
    }

    const persistedSessionId = getActiveConversationId()
    const availableConversations = conversations.filter((item) => includeDeleted || !item.deleted_at)
    const nextConversation = availableConversations.find((item) => item.session_id === persistedSessionId) || availableConversations[0]
    if (nextConversation) {
      navigate(`/chat/${nextConversation.session_id}`, { replace: true })
      return
    }

    void createConversationAndNavigate(true)
  }, [conversationId, conversations, createConversationAndNavigate, historyInitialized, includeDeleted, navigate, sessionId])

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
            id: string
            role: string
            content: string
            timestamp: string
            reasoning_content?: string
            toolEvents?: import('@/features/chat/types').ChatMessage['toolEvents']
            segments?: import('@/features/chat/types').AssistantMessageSegment[]
          }) => ({
            id: msg.id?.toString() || crypto.randomUUID(),
            role: msg.role as 'user' | 'assistant',
            content: msg.content,
            reasoning_content: typeof msg.reasoning_content === 'string' ? msg.reasoning_content : undefined,
            timestamp: new Date(msg.timestamp),
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
        if (statusCode === 404 && useChatStore.getState().sessionId === sessionId) {
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
  }, [flushConversationCache, historyInitialized, recoverUnavailableConversation, resetStreamExecutionState, sessionId, setMessages])

  const updateAssistantMeta = useCallback((messageId: string, updater: (current: import('@/features/chat/types').AssistantExecutionMeta) => import('@/features/chat/types').AssistantExecutionMeta) => {
    setMessageMeta((prev) => ({
      ...prev,
      [messageId]: updater(prev[messageId] || { steps: [], toolEvents: [] }),
    }))
  }, [])

  const updateAssistantSegments = useCallback((
    messageId: string,
    updater: (current: import('@/features/chat/types').AssistantMessageSegment[] | undefined) => import('@/features/chat/types').AssistantMessageSegment[]
  ) => {
    updateMessage(messageId, (message) => {
      if (message.role !== 'assistant') {
        return message
      }
      return {
        ...message,
        segments: updater(message.segments),
      }
    })
  }, [updateMessage])

  const finalizeAssistantMessageSegments = useCallback((messageId: string) => {
    updateAssistantSegments(messageId, (segments) => {
      // 最终化助手消息分段：将最后一个 thought 分段标记为已完成
      if (!segments || segments.length === 0) {
        return segments || []
      }
      const lastIndex = segments.length - 1
      return segments.map((segment, index) =>
        index === lastIndex && segment.kind === 'thought'
          ? { ...segment, status: 'completed' as const }
          : segment
      )
    })
  }, [updateAssistantSegments])

  const handleSendRef = useRef<((message?: string, attachments?: FileAttachment[], options?: import('./hooks/useChatStream').SendMessageOptions) => Promise<void>) | undefined>(undefined)

  const subagentSync = useSubagentSync({
    updateAssistantMeta,
    updateAssistantSegments,
    addToast,
    isMountedRef,
    messageMetaRef,
    handleSendRef: handleSendRef as React.MutableRefObject<((message?: string | undefined, attachments?: unknown[] | undefined, options?: import('@/features/chat/hooks/useSubagentSync').SendOptions | undefined) => Promise<void>) | undefined>,
  })

  const chatStream = useChatStream({
    sessionId,
    outputMode,
    selectedModel,
    thinkingEnabled,
    thinkingDepth,
    isMountedRef,
    updateAssistantMeta,
    updateAssistantSegments,
    finalizeAssistantMessageSegments,
    appendAssistantMessageText,
    flushBuffer,
    addToast,
    streamExecution: {
      beginStreamExecution,
      markStreamRetrying,
      markStreamStreaming,
      markStreamFailed,
      clearStreamStageMessage,
      setIdleStreamState,
      setStreamStageMessage,
    },
    subagentSync,
    setTodoItems,
    setTodoSummary,
    setStreamingAssistantId,
    setLoading,
    messageMeta,
    setMessageMeta,
  })

  const handleSend = useCallback(async (userMessage?: string, uploadedAttachments?: FileAttachment[], options?: import('./hooks/useChatStream').SendMessageOptions) => {
    await chatStream.handleSendMessage(
      userMessage,
      uploadedAttachments,
      options,
      ensureConversationSession,
      () => {
        flushConversationCache()
        if (sessionId && sessionId !== 'default') {
          void loadConversationList(1, false)
        }
      }
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatStream, ensureConversationSession, flushConversationCache, sessionId, loadConversationList])

  handleSendRef.current = handleSend

  // 稳定化传递给子组件的回调：通过 ref 读取最新 handleSend，避免内联箭头函数导致子组件无效重渲染
  const handleChatInputSend = useCallback((content: string, atts?: FileAttachment[]) => {
    void handleSendRef.current?.(content, atts)
  }, [])

  const handleDiaryCommand = useCallback(async () => {
    addToast(t('chat.generatingDiary'), 'info')
    try {
      const result = await diaryAPI.generate()
      if (result.success && result.content) {
        addToast(t('chat.diaryGenerated', { date: result.logical_date || '' }), 'success')
      } else {
        addToast(result.error || t('chat.diaryFailed'), 'warning')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : t('chat.diaryFailed')
      addToast(message, 'error')
    }
  }, [addToast, t])

  const doAbort = useCallback(() => {
    setAborting(true)
    try {
      chatStream.abortStream()
      if (sessionId && sessionId !== 'default') {
        chatAPI.cancelSession(sessionId).catch(() => { /* 静默，abort 已处理 */ })
      }
      setStreamingAssistantId(null)
      resetActiveToolCalls()
    } finally {
      setAborting(false)
      setShowAbortConfirm(false)
    }
  }, [sessionId, resetActiveToolCalls, chatStream])

  const handleAbort = useCallback(() => {
    // 通过 getState() 读取最新 activeToolCalls，避免 useCallback 依赖 activeToolCalls 导致引用频繁变化
    if (useChatStore.getState().activeToolCalls.length > 0) {
      setShowAbortConfirm(true)
      return
    }
    doAbort()
  }, [doAbort])

  const handleEditMessage = useCallback((content: string) => {
    setEditContent(content)
    setShouldFocusInput((prev) => prev + 1)
  }, [])

  const handleFeedback = useCallback((messageId: string, rating: 1 | -1) => {
    setFeedbackState((prev) => ({ ...prev, [messageId]: rating }))
    chatAPI.sendFeedback({
      session_id: sessionId,
      message_id: messageId,
      rating,
    }).catch(() => {
      // 回滚乐观更新，移除该消息的反馈状态
      setFeedbackState((prev) => {
        const next = { ...prev }
        delete next[messageId]
        return next
      })
      addToast(t('chat.feedbackFailed'), 'error')
    })
  }, [sessionId, addToast, t])

  const handleUndoOperation = useCallback(async (operationId: string) => {
    try {
      await chatAPI.undoOperation({ operation_id: operationId })
    } catch (error) {
      appLogger.error({
        event: 'undo_operation_failed',
        module: 'chat_page',
        message: '撤销操作失败',
        extra: { operationId, error: error instanceof Error ? error.message : String(error) },
      })
      throw error
    }
  }, [])

  const handleRegenerate = useCallback(async (messageId: string) => {
    const currentMessages = useChatStore.getState().messages
    const msgIndex = currentMessages.findIndex((m) => m.id === messageId)
    if (msgIndex === -1) return

    const messagesBefore = currentMessages.slice(0, msgIndex)
    const lastUserMsg = [...messagesBefore].reverse().find((m) => m.role === 'user')
    if (!lastUserMsg) return

    const lastUserMsgIndex = messagesBefore.findIndex((m) => m.id === lastUserMsg.id)
    const preservedMessages = messagesBefore.slice(0, lastUserMsgIndex)

    // 先创建新会话（无论是否有旧会话都需要新会话）
    const response = await conversationAPI.createSession()
    const newConv = response.data as import('@/features/chat/types').ConversationSessionSummary
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
    navigate(`/chat/${newConv.session_id}`, { replace: true })

    void handleSendRef.current?.(lastUserMsg.content, [])
  }, [sessionId, removeConversation, upsertConversation, setSessionId, setMessages, setStreamingAssistantId, resetStreamExecutionState, resetTaskPanelState, navigate])

  const handleCreateConversation = useCallback(async () => {
    setMessageMeta({})
    setStreamingAssistantId(null)
    resetStreamExecutionState()
    resetTaskPanelState()
    await createConversationAndNavigate(false)
  }, [createConversationAndNavigate, resetStreamExecutionState, resetTaskPanelState])

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
    navigate(`/chat/${nextSessionId}`)
    if (isCompactViewport) {
      closeHistorySidebar()
    }
  }, [closeHistorySidebar, isCompactViewport, navigate, resetStreamExecutionState, resetTaskPanelState, sessionId])

  const handleRenameConversation = useCallback(async (targetSessionId: string, title: string) => {
    const response = await conversationAPI.renameSession(targetSessionId, title)
    upsertConversation(response.data as import('@/features/chat/types').ConversationSessionSummary)
  }, [upsertConversation])

  /* 请求删除会话 - 显示确认对话框 */
  const handleDeleteConversation = useCallback((targetSessionId: string) => {
    setPendingDeleteSessionId(targetSessionId)
  }, [])

  /* 执行删除会话 */
  const executeDeleteConversation = useCallback(async () => {
    if (!pendingDeleteSessionId) return
    const targetSessionId = pendingDeleteSessionId
    setPendingDeleteSessionId(null)

    const nextCandidate = conversations.find((item) => item.session_id !== targetSessionId && !item.deleted_at)
    const response = await conversationAPI.deleteSession(targetSessionId)
    if (includeDeleted) {
      upsertConversation(response.data as import('@/features/chat/types').ConversationSessionSummary)
    } else {
      removeConversation(targetSessionId)
    }
    if (sessionId === targetSessionId) {
      if (nextCandidate) {
        navigate(`/chat/${nextCandidate.session_id}`, { replace: true })
      } else {
        await createConversationAndNavigate(true)
      }
    }
    void loadConversationList(1, false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations, createConversationAndNavigate, includeDeleted, navigate, removeConversation, sessionId, upsertConversation, loadConversationList, pendingDeleteSessionId])

  /* 取消删除会话 */
  const cancelDeleteConversation = useCallback(() => {
    setPendingDeleteSessionId(null)
  }, [])

  /* 确认删除会话 */
  const confirmDeleteConversation = useCallback(() => {
    void executeDeleteConversation()
  }, [executeDeleteConversation])

  const handleRestoreConversation = useCallback(async (targetSessionId: string) => {
    const response = await conversationAPI.restoreSession(targetSessionId)
    upsertConversation(response.data as import('@/features/chat/types').ConversationSessionSummary)
    if (!sessionId || sessionId === 'default') {
      navigate(`/chat/${targetSessionId}`, { replace: true })
    }
    void loadConversationList(1, false)
  }, [navigate, sessionId, upsertConversation, loadConversationList])

  const handleLoadMoreConversations = useCallback(() => {
    if (historyLoading || !conversationsHasMore) {
      return
    }
    void loadConversationList(historyPage + 1, true)
  }, [conversationsHasMore, historyLoading, historyPage, loadConversationList])

  const handleBatchDeleteConversations = useCallback(async (sessionIds: string[]) => {
    if (sessionIds.length === 0) {
      return
    }
    if (!window.confirm(t('chat.confirmDeleteSelected', { count: String(sessionIds.length) }))) {
      return
    }

    const currentSessionDeleted = Boolean(sessionId && sessionIds.includes(sessionId))
    const nextCandidate = conversations.find((item) => !sessionIds.includes(item.session_id) && !item.deleted_at)
    const response = await conversationAPI.batchDeleteSessions(sessionIds)

    if (includeDeleted) {
      for (const item of response.data.items || []) {
        upsertConversation(item as import('@/features/chat/types').ConversationSessionSummary)
      }
    } else {
      for (const targetSessionId of sessionIds) {
        removeConversation(targetSessionId)
      }
    }

    if (currentSessionDeleted) {
      if (nextCandidate) {
        navigate(`/chat/${nextCandidate.session_id}`, { replace: true })
      } else {
        await createConversationAndNavigate(true)
      }
    }

    void loadConversationList(1, false)
  }, [conversations, createConversationAndNavigate, includeDeleted, loadConversationList, navigate, removeConversation, sessionId, upsertConversation, t])

  const handleStopAgent = useCallback(async (agentId: string) => {
    try {
      const result = await stopAgent(agentId)
      if (result.ok) {
        updateAssistantMeta(streamingAssistantId || '', (current) => {
          const targetTool = current.toolEvents.find((tool) => tool.id === agentId)
          if (targetTool?.kind === 'subagent') {
            return applySubagentStop(current, {
              agentId,
              agentType: targetTool.subagent?.agentType,
              state: 'stopped',
              summary: t('chat.manuallyStopped'),
            })
          }
          return applyToolUpdate(current, {
            id: agentId,
            kind: 'task',
            status: 'completed',
            detail: '已手动停止',
          })
        })
        if (streamingAssistantId) {
          updateAssistantSegments(streamingAssistantId, (segments) => applyToolPatchToSegments(segments, agentId, {
            status: 'completed',
            detail: '已手动停止',
            completedAt: Date.now(),
          }))
          subagentSync.scheduleSubagentAggregation(streamingAssistantId)
        }
        subagentSync.clearSubagentTimeout(agentId)
      }
    } catch (error) {
      appLogger.warning({
        event: 'stop_agent_failed',
        module: 'chat_page',
        message: 'failed to stop agent',
        extra: { agentId },
      })
    }
  }, [subagentSync, streamingAssistantId, updateAssistantMeta, updateAssistantSegments, t])

  return (
    <div className={styles['chat-page']}>
      <div className={styles['chat-header']}>
        <div className={styles['chat-header-title']}>
          <button
            type="button"
            className={styles['history-toggle']}
            onClick={toggleHistorySidebar}
            title={historySidebarOpen ? '收起历史记录' : '展开历史记录'}
            aria-label={historySidebarOpen ? '收起历史记录' : '展开历史记录'}
          >
            <PanelLeft size={18} />
          </button>
          <div>
            <h1>AI 助手</h1>
            <p className={styles['session-caption']}>
              {sessionId && sessionId !== 'default' ? `当前会话：${sessionId.slice(0, 12)}` : '准备开始新对话'}
            </p>
          </div>
        </div>
        <div className={styles['header-controls']}>
          {outputMode === 'stream' && (isLoading || streamConnectionState === 'error') && streamStatusText && (
            <span className={`${styles['stream-status']} ${styles[`stream-status-${streamConnectionState}`]}`}>
              <span className={styles['stream-status-dot']} />
              {streamStatusText}
            </span>
          )}
          {/* 思考模式开关 */}
          <label className={styles['thinking-toggle']} title={isLoading ? '发送中不可修改' : '启用 AI 思考模式'}>
            <input
              type="checkbox"
              checked={thinkingEnabled}
              onChange={(e) => setThinkingEnabled(e.target.checked)}
              disabled={isLoading}
            />
            <span>思考</span>
          </label>
          {thinkingEnabled && (
            <div className={styles['thinking-depth']}>
              <input
                type="range"
                min="0"
                max="5"
                value={thinkingDepth}
                onChange={(e) => setThinkingDepth(Number(e.target.value))}
                disabled={isLoading}
                title={`思考深度: ${thinkingDepth}`}
              />
              <span className={styles['thinking-depth-value']}>{thinkingDepth}</span>
            </div>
          )}
          <select
            value={outputMode}
            onChange={(e) => setOutputMode(e.target.value as 'stream' | 'direct')}
            className={styles['mode-select']}
          >
            <option value="stream">流式传输</option>
            <option value="direct">直接输出</option>
          </select>
          {selectedModel && (
            <span className={styles['current-model']}>{selectedModel.split(':').pop()}</span>
          )}
        </div>
        <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={() => void handleCreateConversation()}>
          新对话
        </button>
      </div>

      <div className={styles['chat-body']}>
        {historySidebarOpen && isCompactViewport && (
          <button className={styles['history-overlay']} onClick={closeHistorySidebar} aria-label="关闭历史记录遮罩" />
        )}
        <ConversationSidebar
          open={historySidebarOpen}
          loading={historyLoading}
          error={historyError}
          conversations={conversations}
          activeSessionId={sessionId}
          search={historySearchInput}
          sortBy={historySort}
          includeDeleted={includeDeleted}
          hasMore={conversationsHasMore}
          onToggle={toggleHistorySidebar}
          onSearchChange={setHistorySearchInput}
          onSortChange={setHistorySort}
          onIncludeDeletedChange={setIncludeDeleted}
          onCreateConversation={handleSidebarCreateConversation}
          onSelectConversation={handleSelectConversation}
          onRenameConversation={handleRenameConversation}
          onDeleteConversation={handleDeleteConversation}
          onBatchDeleteConversations={handleBatchDeleteConversations}
          onRestoreConversation={handleRestoreConversation}
          onLoadMore={handleLoadMoreConversations}
        />

        <div className={styles['chat-main']}>
          <PermissionRequestNotification
            pendingRequests={permissionRequests}
            onApprove={approvePermission}
            onApproveAlways={approveAlwaysPermission}
            onDeny={denyPermission}
          />
          <MessageList
            messages={messages}
            messageMeta={messageMeta}
            streamingAssistantId={streamingAssistantId}
            isLoading={isLoading}
            outputMode={outputMode}
            streamStatusText={streamStatusText}
            messagesEndRef={messagesEndRef}
            onEditMessage={handleEditMessage}
            onRegenerate={handleRegenerate}
            onFeedback={handleFeedback}
            feedbackState={feedbackState}
            onUndo={handleUndoOperation}
          />

          <React.Suspense fallback={null}>
            <TodoPanel
              items={todoItems}
              summary={todoSummary}
            />
          </React.Suspense>

          <React.Suspense fallback={null}>
            <TaskPanel
              steps={activeExecution?.meta.steps || []}
              toolEvents={activeExecution?.meta.toolEvents || []}
              isStreaming={activeExecution?.isStreaming || false}
              onStopAgent={(agentId) => void handleStopAgent(agentId)}
              expanded={taskPanelExpanded}
            onToggle={toggleTaskPanel}
          />
          </React.Suspense>

          <ChatInput
            onSend={handleChatInputSend}
            isLoading={isLoading}
            streamingAssistantId={streamingAssistantId}
            onAbort={handleAbort}
            aborting={aborting}
            onDiaryCommand={handleDiaryCommand}
            editContent={editContent}
            focusTrigger={shouldFocusInput}
          />
        </div>
      </div>
      <ToastContainer />
      {showAbortConfirm && (
        <ConfirmDialog
          isOpen={showAbortConfirm}
          title="中断执行"
          message="正在执行工具调用，确定要中断吗？已完成的工具调用结果将保留。"
          type="warning"
          confirmText="中断"
          cancelText="继续"
          onConfirm={doAbort}
          onCancel={() => setShowAbortConfirm(false)}
        />
      )}
      {pendingDeleteSessionId && (
        <ConfirmDialog
          isOpen={!!pendingDeleteSessionId}
          title="删除会话"
          message="确定要删除此会话吗？删除后无法恢复。"
          type="danger"
          confirmText="删除"
          cancelText="取消"
          onConfirm={confirmDeleteConversation}
          onCancel={cancelDeleteConversation}
        />
      )}
    </div>
  )
}

export default ChatPage
