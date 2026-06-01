import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PanelLeft } from 'lucide-react'
import { chatAPI, conversationAPI, diaryAPI, type ChatContinuationPayload } from '@/shared/api/api'
import { useConversationHistory } from '@/features/chat/hooks/useConversationHistory'
import { useStreamExecutionState } from '@/features/chat/hooks/useStreamExecutionState'
import { useTaskPanelState } from '@/features/chat/hooks/useTaskPanelState'
import { useChatStore } from '@/features/chat/store/chatStore'
import { applyDirectAssistantResponse } from '@/features/chat/utils/applyDirectAssistantResponse'
import { handleStreamChunkEvent } from '@/features/chat/utils/handleStreamChunkEvent'
import {
  getActiveConversationId,
  getCachedConversationMessages,
} from '@/features/chat/utils/chatCache'
import { safeGetJsonItem } from '@/shared/utils/safeStorage'
import type { AssistantExecutionMeta, AssistantMessageSegment, ChatMessage, ConversationSessionSummary, TaskStatus } from '@/features/chat/types'
import {
  applySubagentStop,
  syncSubagentSnapshot,
  applySubagentTimeout,
  buildSubagentTranscriptText,
  setSubagentAggregation,
  SUBAGENT_INACTIVITY_TIMEOUT_MS,
  applyTaskUpdate,
  applyToolUpdate,
  createEmptyExecutionMeta,
  formatUsageCost,
  formatUsageTokens,
  getTaskTitle,
  hasExecutionMeta,
} from '@/features/chat/utils/executionMeta'
import {
  appendAssistantChunk,
  applyToolEventToSegments,
  applyToolPatchToSegments,
  finalizeAssistantSegments,
} from '@/features/chat/utils/assistantSegments'
import { dispatchStructuredStreamEvent } from '@/features/chat/utils/dispatchStructuredStreamEvent'
import { getAgent, getTranscript, stopAgent } from '@/shared/api/taskRuntimeApi'
import { useI18nStore } from '@/i18n'
import { appLogger } from '@/shared/utils/logger'
import { dispatchBillingUsageUpdated } from '@/shared/events/billingEvents'
import { useToast } from '@/shared/components/Toast'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import ConversationSidebar from './components/ConversationSidebar'
import { MessageList } from './components/MessageList'
import { ChatInput } from './components/ChatInput'
import type { FileAttachment } from './components/ChatInput'
// P1: TaskPanel/TodoPanel 按需懒加载，减少聊天页首屏 JS
const TaskPanel = React.lazy(() => import('./components/TaskPanel').then(m => ({ default: m.TaskPanel })))
const TodoPanel = React.lazy(() => import('./components/TodoPanel').then(m => ({ default: m.TodoPanel })))
import type { TodoItem } from './components/TodoPanel'
import styles from './ChatPage.module.css'

function sanitizeDisplayedError(message: string): string {
  return String(message || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const MAX_STREAM_RETRY_COUNT = 1
const SUBAGENT_RUNTIME_SYNC_INTERVAL_MS = 1200

function shouldRetryStreamError(error: Error): boolean {
  const message = String(error.message || '').toLowerCase()
  return [
    'failed to fetch',
    'network',
    'stream',
    'timeout',
    'load failed',
    'econnreset',
  ].some((keyword) => message.includes(keyword))
}

interface ChatAppSettings {
  maxToolCallRounds?: number
}

function buildMessageMetaFromSegments(
  segments: AssistantMessageSegment[] | undefined
): AssistantExecutionMeta | undefined {
  if (!segments || segments.length === 0) {
    return undefined
  }

  let meta = createEmptyExecutionMeta()
  for (const segment of segments) {
    if (segment.kind !== 'thought') {
      continue
    }
    if (segment.intent) {
      meta.intent = segment.intent
    }
    for (const step of segment.steps) {
      meta = applyTaskUpdate(meta, step as unknown as Record<string, unknown>)
    }
    for (const tool of segment.toolEvents) {
      meta = applyToolUpdate(meta, tool as unknown as Record<string, unknown>)
    }
    if (segment.usage) {
      meta.usage = segment.usage
    }
  }

  return hasExecutionMeta(meta) ? meta : undefined
}

function buildMessageMetaFromMessages(messages: ChatMessage[]): Record<string, AssistantExecutionMeta> {
  const restoredMeta: Record<string, AssistantExecutionMeta> = {}

  for (const message of messages) {
    if (message.role !== 'assistant') {
      continue
    }

    const segmentMeta = buildMessageMetaFromSegments(message.segments)
    if (segmentMeta) {
      restoredMeta[message.id] = segmentMeta
      continue
    }

    if (message.toolEvents && message.toolEvents.length > 0) {
      restoredMeta[message.id] = {
        steps: [],
        toolEvents: message.toolEvents,
      }
    }
  }

  return restoredMeta
}

function mergeServerHistoryWithCached(
  remoteMessages: ChatMessage[],
  cachedMessages: ChatMessage[]
): ChatMessage[] {
  if (remoteMessages.length === 0) {
    return cachedMessages
  }

  const mergedMessages = remoteMessages.map((remoteMessage, index) => {
    const cachedMessage = cachedMessages[index]
    if (
      !cachedMessage ||
      cachedMessage.role !== remoteMessage.role ||
      cachedMessage.content !== remoteMessage.content
    ) {
      return remoteMessage
    }

    if (remoteMessage.role !== 'assistant') {
      return remoteMessage
    }

    return {
      ...remoteMessage,
      reasoning_content: remoteMessage.reasoning_content ?? cachedMessage.reasoning_content,
      toolEvents: remoteMessage.toolEvents?.length ? remoteMessage.toolEvents : cachedMessage.toolEvents,
      segments: remoteMessage.segments?.length ? remoteMessage.segments : cachedMessage.segments,
    }
  })

  const isPrefixMatch = remoteMessages.every((remoteMessage, index) => {
    const cachedMessage = cachedMessages[index]
    return Boolean(
      cachedMessage &&
      cachedMessage.role === remoteMessage.role &&
      cachedMessage.content === remoteMessage.content
    )
  })

  if (isPrefixMatch && cachedMessages.length > remoteMessages.length) {
    return [...mergedMessages, ...cachedMessages.slice(remoteMessages.length)]
  }

  return mergedMessages
}

function getLocalMessagesForRestore(targetSessionId: string): ChatMessage[] {
  const state = useChatStore.getState()
  if (state.sessionId === targetSessionId && state.messages.length > 0) {
    return state.messages
  }

  return getCachedConversationMessages(targetSessionId)
}

function getConfiguredMaxToolCallRounds(): number {
  const appSettings = safeGetJsonItem<ChatAppSettings | null>('app_settings', null)
  const rawValue = appSettings?.maxToolCallRounds
  if (typeof rawValue !== 'number' || Number.isNaN(rawValue)) {
    return 12
  }
  return Math.max(1, Math.min(50000, Math.trunc(rawValue)))
}

function buildSubagentAggregateLine(name: string, text: string, failed: boolean): string {
  const normalizedText = text.trim()
  if (!normalizedText) {
    return failed ? `[ERROR] Subagent ${name}: 未返回可用输出` : `Subagent ${name}: `
  }
  return failed ? `[ERROR] Subagent ${name}: ${normalizedText}` : `Subagent ${name}: ${normalizedText}`
}

function buildSubagentContinuationPrompt(): string {
  return '请基于刚刚完成的子代理输出继续完成上一轮任务，并直接给出后续分析或最终答复。'
}

interface SendMessageOptions {
  assistantMessageId?: string
  hiddenUserMessage?: boolean
  continuation?: ChatContinuationPayload
}

function ChatPage() {
  const navigate = useNavigate()
  const { t } = useI18nStore()
  const { conversationId } = useParams<{ conversationId?: string }>()
  const {
    messages,
    addMessage,
    setLoading,
    isLoading,
    sessionId,
    setSessionId,
    outputMode,
    setOutputMode,
    selectedModel,
    setMessages,
    updateMessage,
    loadCachedMessages,
    conversations,
    upsertConversation,
    removeConversation,
    conversationsHasMore,
    thinkingEnabled,
    setThinkingEnabled,
    thinkingDepth,
    setThinkingDepth,
    activeToolCalls,
    addActiveToolCall,
    removeActiveToolCall,
    resetActiveToolCalls,
  } = useChatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const activeRequestIdRef = useRef(0)
  const activeAbortControllerRef = useRef<AbortController | null>(null)
  const isMountedRef = useRef(true)
  const pendingConversationCreationRef = useRef<Promise<string> | null>(null)
  const [messageMeta, setMessageMeta] = useState<Record<string, AssistantExecutionMeta>>({})
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
  const messageMetaRef = useRef<Record<string, AssistantExecutionMeta>>({})
  const subagentTimeoutRef = useRef<Record<string, number>>({})
  const subagentSyncTimerRef = useRef<Record<string, number>>({})
  const subagentSyncInFlightRef = useRef<Record<string, boolean>>({})
  const subagentAggregationTimerRef = useRef<Record<string, number>>({})
  const aggregatedSubagentIdsRef = useRef<Record<string, Set<string>>>({})
  const syncSubagentRuntimeRef = useRef<(assistantMessageId: string, agentId: string, agentType?: string) => void>(() => {})
  const triggerSubagentContinuationRef = useRef<(assistantMessageId: string, aggregatedText: string) => void>(() => {})
  const handleSendRef = useRef<typeof handleSend>(undefined as unknown as typeof handleSend)

  const bufferRef = useRef({
    content: '',
    reasoning: '',
    lastUpdateTime: Date.now()
  })

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

  const flushConversationCache = useCallback(() => {
    // P1: 使用 store 内置的 flushMessages（内部调用 IndexedDB saveMessages）
    useChatStore.getState().flushMessages()
  }, [])

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
      activeAbortControllerRef.current?.abort()
      for (const timerId of Object.values(subagentTimeoutRef.current)) {
        window.clearTimeout(timerId)
      }
      subagentTimeoutRef.current = {}
      for (const timerId of Object.values(subagentSyncTimerRef.current)) {
        window.clearTimeout(timerId)
      }
      subagentSyncTimerRef.current = {}
      subagentSyncInFlightRef.current = {}
      for (const timerId of Object.values(subagentAggregationTimerRef.current)) {
        window.clearTimeout(timerId)
      }
      subagentAggregationTimerRef.current = {}
      aggregatedSubagentIdsRef.current = {}
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
      const nextConversation = response.data as ConversationSessionSummary
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
      setSessionId(conversationId)
      const cachedMsgs = getLocalMessagesForRestore(conversationId)
      loadCachedMessages(conversationId)
      setMessageMeta(buildMessageMetaFromMessages(cachedMsgs))
      setStreamingAssistantId(null)
      resetStreamExecutionState()
    }
  }, [conversationId, loadCachedMessages, resetStreamExecutionState, sessionId, setSessionId])

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
            toolEvents?: ChatMessage['toolEvents']
            segments?: AssistantMessageSegment[]
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

  const updateAssistantMeta = useCallback((messageId: string, updater: (current: AssistantExecutionMeta) => AssistantExecutionMeta) => {
    setMessageMeta((prev) => ({
      ...prev,
      [messageId]: updater(prev[messageId] || createEmptyExecutionMeta()),
    }))
  }, [])

  const updateAssistantSegments = useCallback((
    messageId: string,
    updater: (current: AssistantMessageSegment[] | undefined) => AssistantMessageSegment[]
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
    updateAssistantSegments(messageId, (segments) => finalizeAssistantSegments(segments))
  }, [updateAssistantSegments])

  const clearSubagentTimeout = useCallback((agentId: string) => {
    const timerId = subagentTimeoutRef.current[agentId]
    if (timerId !== undefined) {
      window.clearTimeout(timerId)
      delete subagentTimeoutRef.current[agentId]
    }
  }, [])

  const clearSubagentSyncTimer = useCallback((agentId: string) => {
    const timerId = subagentSyncTimerRef.current[agentId]
    if (timerId !== undefined) {
      window.clearTimeout(timerId)
      delete subagentSyncTimerRef.current[agentId]
    }
  }, [])

  const scheduleSubagentTimeout = useCallback((assistantMessageId: string, agentId: string, agentType?: string) => {
    clearSubagentTimeout(agentId)
    subagentTimeoutRef.current[agentId] = window.setTimeout(() => {
      const timeoutMessage = `Subagent ${agentType || agentId} 执行失败`
      const timeoutPayload = { agentId, agentType, message: timeoutMessage }

      updateAssistantMeta(assistantMessageId, (current) => applySubagentTimeout(current, timeoutPayload))
      updateAssistantSegments(assistantMessageId, (segments = []) => {
        // 从当前 segments 读取已积累的日志，避免被超时消息覆盖
        const currentTool = (segments || []).flatMap(s => (s && 'toolEvents' in s && Array.isArray(s.toolEvents)) ? s.toolEvents : []).find(t => t && t.id === agentId)
        const tempMeta = { toolEvents: currentTool ? [currentTool] : [], isThinking: false } as any
        const toolMeta = applySubagentTimeout(tempMeta, timeoutPayload).toolEvents[0]
        if (!toolMeta) return segments || []
        return applyToolEventToSegments(segments, toolMeta)
      })
      addToast(timeoutMessage, 'error')
      clearSubagentTimeout(agentId)
      scheduleSubagentAggregation(assistantMessageId)
    }, SUBAGENT_INACTIVITY_TIMEOUT_MS)
  }, [addToast, clearSubagentTimeout, updateAssistantMeta, updateAssistantSegments])

  const clearSubagentAggregationTimer = useCallback((assistantMessageId: string) => {
    const timerId = subagentAggregationTimerRef.current[assistantMessageId]
    if (timerId !== undefined) {
      window.clearTimeout(timerId)
      delete subagentAggregationTimerRef.current[assistantMessageId]
    }
  }, [])

  const scheduleSubagentAggregation = useCallback((assistantMessageId: string) => {
    clearSubagentAggregationTimer(assistantMessageId)
    subagentAggregationTimerRef.current[assistantMessageId] = window.setTimeout(() => {
      const meta = messageMetaRef.current[assistantMessageId]
      const subagents = meta?.toolEvents.filter((tool) => tool.kind === 'subagent') || []
      const aggregatedIds = aggregatedSubagentIdsRef.current[assistantMessageId] || new Set<string>()
      const pendingSubagents = subagents.filter((tool) => !aggregatedIds.has(tool.id))
      const allCompleted = pendingSubagents.length > 0 && pendingSubagents.every((tool) => tool.status === 'completed' || tool.status === 'error')
      if (!allCompleted) {
        return
      }
      void aggregateSubagentOutputs(assistantMessageId, pendingSubagents)
    }, 80)
  }, [clearSubagentAggregationTimer])

  const aggregateSubagentOutputs = useCallback(async (
    assistantMessageId: string,
    subagents: AssistantExecutionMeta['toolEvents']
  ) => {
    const settledResults = await Promise.allSettled(subagents.map(async (tool) => {
      const fallbackText = tool.subagent?.archivedLogs || tool.subagent?.logs || tool.subagent?.summary || tool.detail || ''
      if (tool.id.startsWith('sub_') || fallbackText.trim()) {
        return buildSubagentAggregateLine(tool.name, fallbackText, tool.status === 'error')
      }

      try {
        const transcriptResponse = await getTranscript(tool.id)
        const transcriptText = buildSubagentTranscriptText(
          Array.isArray(transcriptResponse.transcript) ? transcriptResponse.transcript : []
        )
        const mergedText = transcriptText || fallbackText
        return buildSubagentAggregateLine(tool.name, mergedText, tool.status === 'error')
      } catch {
        const fallbackError = tool.subagent?.errorText || tool.detail || '转录读取失败'
        const fallbackLogs = tool.subagent?.archivedLogs || tool.subagent?.logs || fallbackError
        return buildSubagentAggregateLine(tool.name, fallbackLogs, true)
      }
    }))

    let successCount = 0
    let errorCount = 0
    const lines = settledResults.map((result, index) => {
      const tool = subagents[index]
      const failed = tool.status === 'error' || result.status === 'rejected'
      if (failed) {
        errorCount += 1
      } else {
        successCount += 1
      }

      if (result.status === 'fulfilled') {
        return result.value
      }

      return buildSubagentAggregateLine(tool.name, tool.subagent?.errorText || tool.detail || '转录读取失败', true)
    })

    const mergedText = lines.join('\n\n')
    const aggregatedIds = aggregatedSubagentIdsRef.current[assistantMessageId] || new Set<string>()
    for (const tool of subagents) {
      aggregatedIds.add(tool.id)
    }
    aggregatedSubagentIdsRef.current[assistantMessageId] = aggregatedIds

    updateAssistantMeta(assistantMessageId, (current) => setSubagentAggregation(current, {
      text: current.subagentAggregation?.text
        ? `${current.subagentAggregation.text}\n\n${mergedText}`
        : mergedText,
      total: (current.subagentAggregation?.total || 0) + subagents.length,
      successCount: (current.subagentAggregation?.successCount || 0) + successCount,
      errorCount: (current.subagentAggregation?.errorCount || 0) + errorCount,
      completedAt: Date.now(),
    }))

    if (mergedText.trim()) {
      triggerSubagentContinuationRef.current(assistantMessageId, mergedText)
    }
  }, [updateAssistantMeta])

  syncSubagentRuntimeRef.current = (assistantMessageId: string, agentId: string, agentType?: string) => {
    clearSubagentSyncTimer(agentId)
    if (subagentSyncInFlightRef.current[agentId]) {
      return
    }

    subagentSyncInFlightRef.current[agentId] = true
    void (async () => {
      try {
        const [agentResult, transcriptResult] = await Promise.allSettled([
          getAgent(agentId),
          getTranscript(agentId),
        ])

        if (!isMountedRef.current) {
          return
        }

        const agentDetail = agentResult.status === 'fulfilled'
          ? agentResult.value.agent
          : undefined
        const currentTool = messageMetaRef.current[assistantMessageId]?.toolEvents.find((tool) => tool.id === agentId)
        const transcriptText = transcriptResult.status === 'fulfilled'
          ? buildSubagentTranscriptText(
              Array.isArray(transcriptResult.value.transcript) ? transcriptResult.value.transcript : []
            )
          : ''

        const nextAgentType = agentDetail?.agent_type || agentType || currentTool?.subagent?.agentType
        const snapshotPayload = {
          agentId,
          agentType: nextAgentType,
          state: agentDetail?.state,
          logs: transcriptText || currentTool?.subagent?.archivedLogs || currentTool?.subagent?.logs || '',
          summary: typeof agentDetail?.summary === 'string' ? agentDetail.summary : currentTool?.subagent?.summary,
          errorText: typeof agentDetail?.last_error === 'string' ? agentDetail.last_error : currentTool?.subagent?.errorText,
        }

        if (agentDetail || snapshotPayload.logs) {
          updateAssistantMeta(assistantMessageId, (current) => syncSubagentSnapshot(current, snapshotPayload))
          const toolMeta = syncSubagentSnapshot(createEmptyExecutionMeta(), snapshotPayload).toolEvents[0]
          if (toolMeta) {
            updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
          }
        }

        const normalizedState = String(agentDetail?.state || '').trim().toLowerCase()
        const isTerminal = ['completed', 'failed', 'stopped', 'error'].includes(normalizedState)
        if (isTerminal) {
          clearSubagentTimeout(agentId)
          clearSubagentSyncTimer(agentId)
          scheduleSubagentAggregation(assistantMessageId)
          return
        }

        scheduleSubagentTimeout(assistantMessageId, agentId, nextAgentType)
        subagentSyncTimerRef.current[agentId] = window.setTimeout(() => {
          syncSubagentRuntimeRef.current(assistantMessageId, agentId, nextAgentType)
        }, SUBAGENT_RUNTIME_SYNC_INTERVAL_MS)
      } catch {
        if (isMountedRef.current) {
          subagentSyncTimerRef.current[agentId] = window.setTimeout(() => {
            syncSubagentRuntimeRef.current(assistantMessageId, agentId, agentType)
          }, SUBAGENT_RUNTIME_SYNC_INTERVAL_MS)
        }
      } finally {
        delete subagentSyncInFlightRef.current[agentId]
      }
    })()
  }

  const parseSelectedModel = (value: string): { provider?: string; model?: string } => {
    if (!value) {
      return { provider: undefined, model: undefined }
    }

    const separatorIndex = value.indexOf(':')
    if (separatorIndex <= 0 || separatorIndex >= value.length - 1) {
      return { provider: undefined, model: value }
    }

    return {
      provider: value.slice(0, separatorIndex),
      model: value.slice(separatorIndex + 1),
    }
  }

  const handleSend = async (userMessage?: string, uploadedAttachments?: FileAttachment[], options?: SendMessageOptions) => {
    const messageText = (userMessage || '').trim()
    const safeAttachments = uploadedAttachments || []
    if (!messageText && safeAttachments.length === 0 && !options?.continuation) return
    if (isLoading && !options?.continuation) return

    const hiddenUserMessage = Boolean(options?.hiddenUserMessage)

    let targetSessionId = sessionId
    if (!targetSessionId || targetSessionId === 'default') {
      targetSessionId = await ensureConversationSession()
    }

    const requestId = activeRequestIdRef.current + 1
    activeRequestIdRef.current = requestId
    activeAbortControllerRef.current?.abort()
    const abortController = new AbortController()
    activeAbortControllerRef.current = abortController
    let streamErrorHandled = false
    let assistantMessageCreated = Boolean(options?.assistantMessageId)
    const userMessageId = hiddenUserMessage ? undefined : crypto.randomUUID()
    const assistantMessageId = options?.assistantMessageId || crypto.randomUUID()

    const ensureAssistantMessage = (content = '', reasoning = '') => {
      if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
        return false
      }
      if (!assistantMessageCreated) {
        addMessage('assistant', content, reasoning || undefined, assistantMessageId)
        assistantMessageCreated = true
        setStreamingAssistantId(assistantMessageId)
        if (content || reasoning) {
          updateAssistantSegments(assistantMessageId, (segments) => appendAssistantChunk(segments, {
            content,
            reasoningContent: reasoning,
          }))
        }
        return true
      }
      return false
    }

    let fullMessage = messageText
    // 构建多模态附件载荷
    const chatAttachments: { type: string; data: string; mime_type: string; file_name?: string }[] = []
    if (safeAttachments.length > 0) {
      for (const att of safeAttachments) {
        if (att.base64Data && att.mimeType) {
          chatAttachments.push({
            type: att.mimeType.startsWith('image/') ? 'image' :
                  att.mimeType.startsWith('audio/') ? 'audio' :
                  att.mimeType.startsWith('video/') ? 'video' : 'image',
            data: att.base64Data,
            mime_type: att.mimeType,
            file_name: att.file.name,
          })
        }
        if (att.uploaded) {
          fullMessage = fullMessage
            ? `${fullMessage}\n[附件: ${att.uploaded.name}](${att.uploaded.url})`
            : `[附件: ${att.uploaded.name}](${att.uploaded.url})`
        }
      }
    }

    if (!fullMessage && chatAttachments.length === 0) return

    const currentConversation = conversations.find((item) => item.session_id === targetSessionId)
    const nowIso = new Date().toISOString()
    if (currentConversation && !hiddenUserMessage) {
      upsertConversation({
        ...currentConversation,
        title: currentConversation.title || messageText.slice(0, 80) || '新对话',
        summary: messageText.slice(0, 160),
        last_message_preview: messageText.slice(0, 160),
        last_message_role: 'user',
        updated_at: nowIso,
        last_message_at: nowIso,
        message_count: Math.max(0, currentConversation.message_count) + 1,
      })
    }

    appLogger.info({
      event: 'chat_send',
      module: 'chat_page',
      action: 'send_message',
      status: 'start',
      message: 'chat send started',
      extra: { session_id: targetSessionId, input_length: fullMessage.length, mode: outputMode, attachments: safeAttachments.length },
    })
    if (!hiddenUserMessage) {
      addMessage('user', fullMessage, undefined, userMessageId)
    }
    setLoading(true)
    setStreamingAssistantId(assistantMessageId)
    beginStreamExecution(outputMode)

    try {
      const { provider, model } = parseSelectedModel(selectedModel)
      const executionOptions = {
        ...(thinkingEnabled ? { thinking_enabled: true, thinking_depth: thinkingDepth } : {}),
        max_tool_call_rounds: getConfiguredMaxToolCallRounds(),
        ...(options?.continuation ? { continuation: options.continuation } : {}),
      }

      if (outputMode === 'stream') {
        bufferRef.current = { content: '', reasoning: '', lastUpdateTime: Date.now() }

        for (let attempt = 0; attempt <= MAX_STREAM_RETRY_COUNT; attempt += 1) {
          let runtimeError: Error | null = null
          if (attempt > 0) {
            markStreamRetrying(attempt)
          }

          try {
            await chatAPI.sendMessageStream(
              fullMessage,
              targetSessionId,
              provider,
              model,
              (event) => {
                if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
                  return
                }

                markStreamStreaming()

                if (event?.type === 'status') {
                  const nextStageMessage = typeof event.message === 'string' ? event.message.trim() : ''
                  setStreamStageMessage(nextStageMessage || null)
                  return
                }

                if (event?.type === 'chunk') {
                  assistantMessageCreated = handleStreamChunkEvent({
                    assistantMessageId,
                    event: event as Record<string, unknown>,
                    assistantMessageCreated,
                    ensureAssistantMessage,
                    updateAssistantSegments,
                    appendAssistantMessageText,
                    flushBuffer,
                    buffer: bufferRef.current,
                    isDocumentHidden: document.hidden,
                  })
                  return
                }

                ensureAssistantMessage()
                // 追踪进行中的工具调用，用于停止按钮的智能判断
                if ((event as Record<string, unknown>)?.type === 'tool') {
                  const toolData = (event as Record<string, unknown>).tool as Record<string, unknown> | undefined
                  const toolId = String(toolData?.id || '')
                  const toolStatus = String(toolData?.status || '')
                  if (toolStatus === 'running') {
                    addActiveToolCall(toolId)
                  } else if (toolStatus === 'completed' || toolStatus === 'error') {
                    removeActiveToolCall(toolId)
                  }
                }
                dispatchStructuredStreamEvent(event as Record<string, unknown>, {
                  assistantMessageId,
                  messageMeta,
                  addToast,
                  updateAssistantMeta,
                  updateAssistantSegments,
                  clearSubagentAggregationTimer,
                  scheduleSubagentTimeout,
                  syncSubagentRuntime: (targetAssistantMessageId, agentId, agentType) => {
                    syncSubagentRuntimeRef.current(targetAssistantMessageId, agentId, agentType)
                  },
                  clearSubagentTimeout,
                  clearSubagentSyncTimer,
                  scheduleSubagentAggregation,
                  setTodoItems,
                  setTodoSummary,
                  dispatchUsageUpdated: ({ callId, provider, model }) => {
                    dispatchBillingUsageUpdated({ callId, provider, model })
                  },
                })
              },
              (error) => {
                runtimeError = error instanceof Error ? error : new Error(String(error))
              },
              { signal: abortController.signal },
              executionOptions,
              chatAttachments.length > 0 ? chatAttachments : undefined
            )

            if (runtimeError) {
              throw runtimeError
            }
            break
          } catch (error) {
            if (error instanceof DOMException && error.name === 'AbortError') {
              throw error
            }

            const normalizedError = error instanceof Error ? error : new Error(String(error))
            const hasPartialAssistantOutput = assistantMessageCreated || Boolean(bufferRef.current.content || bufferRef.current.reasoning)
            const canRetry = attempt < MAX_STREAM_RETRY_COUNT && !hasPartialAssistantOutput && shouldRetryStreamError(normalizedError)

            if (canRetry) {
              markStreamRetrying(attempt + 1)
              continue
            }

            streamErrorHandled = true
            flushBuffer(assistantMessageId)
            markStreamFailed(sanitizeDisplayedError(normalizedError.message))
            appLogger.error({
              event: 'chat_stream_error',
              module: 'chat_page',
              action: 'receive_stream',
              status: 'failure',
              message: 'chat stream error',
              extra: { error: normalizedError.message, retry_count: attempt },
            })
            if (!assistantMessageCreated) {
              const errorContent = `请求失败：${sanitizeDisplayedError(normalizedError.message)}`
              addMessage('assistant', errorContent, undefined, assistantMessageId)
              assistantMessageCreated = true
              updateAssistantSegments(assistantMessageId, (segments) => appendAssistantChunk(segments, {
                content: errorContent,
              }))
            } else {
              const errorContent = `\n\n[流中断：${sanitizeDisplayedError(normalizedError.message)}]`
              appendAssistantMessageText(assistantMessageId, errorContent)
              updateAssistantSegments(assistantMessageId, (segments) => appendAssistantChunk(segments, {
                content: errorContent,
              }))
            }
            finalizeAssistantMessageSegments(assistantMessageId)
            throw normalizedError
          }
        }
        flushBuffer(assistantMessageId)
        finalizeAssistantMessageSegments(assistantMessageId)
        clearStreamStageMessage()
        setIdleStreamState()

        if (!isMountedRef.current || activeRequestIdRef.current !== requestId || streamErrorHandled) {
          return
        }
      } else {
        const response = await chatAPI.sendMessage(fullMessage, targetSessionId, provider, model, 'direct', {
          signal: abortController.signal,
        }, executionOptions, chatAttachments.length > 0 ? chatAttachments : undefined)
        if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
          return
        }
        assistantMessageCreated = applyDirectAssistantResponse({
          assistantMessageId,
          responseData: response.data,
          addMessage: (role, content, reasoningContent, messageId) => {
            addMessage(role, content, reasoningContent, messageId)
          },
          updateMessage,
          setMessageMeta,
          sanitizeDisplayedError,
          dispatchUsageUpdated: ({ callId, provider, model }) => {
            dispatchBillingUsageUpdated({ callId, provider, model })
          },
        })
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        clearStreamStageMessage()
        setIdleStreamState()
        return
      }
      appLogger.error({
        event: 'chat_send',
        module: 'chat_page',
        action: 'send_message',
        status: 'failure',
        message: 'chat send failed',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      if (isMountedRef.current && activeRequestIdRef.current === requestId && !streamErrorHandled) {
        if (!assistantMessageCreated) {
          addMessage('assistant', t('chat.errorOccurred'), undefined, assistantMessageId)
          assistantMessageCreated = true
          updateAssistantSegments(assistantMessageId, (segments) => appendAssistantChunk(segments, {
            content: t('chat.errorOccurred'),
          }))
        } else {
          appendAssistantMessageText(assistantMessageId, t('chat.errorOccurred'))
          updateAssistantSegments(assistantMessageId, (segments) => appendAssistantChunk(segments, {
            content: t('chat.errorOccurred'),
          }))
        }
      }
    } finally {
      resetActiveToolCalls()
      flushConversationCache()
      if (targetSessionId && targetSessionId !== 'default') {
        void loadConversationList(1, false)
      }
      if (isMountedRef.current && activeRequestIdRef.current === requestId) {
        setLoading(false)
        setStreamingAssistantId(null)
        clearStreamStageMessage()
        if (!streamErrorHandled) {
          setIdleStreamState()
        }
      }
    }
  }

  handleSendRef.current = handleSend

  triggerSubagentContinuationRef.current = (assistantMessageId: string, aggregatedText: string) => {
    void handleSend(buildSubagentContinuationPrompt(), undefined, {
      assistantMessageId,
      hiddenUserMessage: true,
      continuation: {
        source: 'subagent',
        aggregated_context: aggregatedText,
        merge_with_last_assistant: true,
      },
    })
  }

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
  }, [addToast])

  const doAbort = useCallback(() => {
    setAborting(true)
    try {
      activeAbortControllerRef.current?.abort()
      if (sessionId && sessionId !== 'default') {
        chatAPI.cancelSession(sessionId).catch(() => { /* 静默，abort 已处理 */ })
      }
      setStreamingAssistantId(null)
      resetActiveToolCalls()
    } finally {
      setAborting(false)
      setShowAbortConfirm(false)
    }
  }, [sessionId, resetActiveToolCalls])

  const handleAbort = useCallback(() => {
    if (activeToolCalls.length > 0) {
      setShowAbortConfirm(true)
      return
    }
    doAbort()
  }, [activeToolCalls, doAbort])

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
      /* 静默失败，不影响 UI */
    })
  }, [sessionId])

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
    navigate(`/chat/${newConv.session_id}`, { replace: true })

    void handleSendRef.current(lastUserMsg.content, [])
  }, [sessionId, removeConversation, upsertConversation, setSessionId, setMessages, setMessageMeta, setStreamingAssistantId, resetStreamExecutionState, resetTaskPanelState, navigate])

  const handleCreateConversation = useCallback(async () => {
    setMessageMeta({})
    setStreamingAssistantId(null)
    resetStreamExecutionState()
    resetTaskPanelState()
    await createConversationAndNavigate(false)
  }, [createConversationAndNavigate, resetStreamExecutionState, resetTaskPanelState])

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
    upsertConversation(response.data as ConversationSessionSummary)
  }, [upsertConversation])

  const handleDeleteConversation = useCallback(async (targetSessionId: string) => {
    if (!window.confirm(t('chat.confirmDeleteConversation'))) {
      return
    }
    const nextCandidate = conversations.find((item) => item.session_id !== targetSessionId && !item.deleted_at)
    const response = await conversationAPI.deleteSession(targetSessionId)
    if (includeDeleted) {
      upsertConversation(response.data as ConversationSessionSummary)
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
  }, [conversations, createConversationAndNavigate, includeDeleted, navigate, removeConversation, sessionId, upsertConversation, loadConversationList])

  const handleRestoreConversation = useCallback(async (targetSessionId: string) => {
    const response = await conversationAPI.restoreSession(targetSessionId)
    upsertConversation(response.data as ConversationSessionSummary)
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
        upsertConversation(item as ConversationSessionSummary)
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
  }, [conversations, createConversationAndNavigate, includeDeleted, loadConversationList, navigate, removeConversation, sessionId, upsertConversation])

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
          scheduleSubagentAggregation(streamingAssistantId)
        }
        clearSubagentTimeout(agentId)
      }
    } catch (error) {
      appLogger.warning({
        event: 'stop_agent_failed',
        module: 'chat_page',
        message: 'failed to stop agent',
        extra: { agentId },
      })
    }
    }, [clearSubagentTimeout, scheduleSubagentAggregation, streamingAssistantId, updateAssistantMeta, updateAssistantSegments])

  const getStatusIcon = (status: TaskStatus) => {
    switch (status) {
      case 'completed': return <span className={styles['status-dot-completed']} title={t('chat.completed')} />
      case 'running': return <span className={styles['status-dot-running']} title={t('chat.running')} />
      case 'error': return <span className={styles['status-dot-error']} title={t('chat.failed')} />
      default: return <span className={styles['status-dot-pending']} title={t('chat.waiting')} />
    }
  }

  const renderFloatingExecutionPanel = () => {
    const active = activeExecution
    if (!active) return null
    const { meta: currentMeta, isStreaming } = active

    return (
      <div className={styles['floating-execution']}>
        <div className={styles['floating-execution-header']}>
          <span className={styles['floating-execution-label']}>
            {currentMeta.intent ? `${currentMeta.intent}` : '任务'}
            {isStreaming && <span className={styles['floating-dot-pulse']} />}
          </span>
          {currentMeta.usage && (
            <span className={styles['floating-execution-usage']}>
              {formatUsageTokens(currentMeta.usage.input_tokens)}/{formatUsageTokens(currentMeta.usage.output_tokens)} tokens
              {currentMeta.usage.total_cost ? ` ${formatUsageCost(currentMeta.usage.total_cost, currentMeta.usage.currency)}` : ''}
              {currentMeta.usage.duration_ms ? ` ${currentMeta.usage.duration_ms}ms` : ''}
            </span>
          )}
        </div>
        {currentMeta.steps.length > 0 && (
          <div className={styles['floating-execution-steps']}>
            {currentMeta.steps.map((step) => (
              <div key={`${step.step}-${step.action}`} className={styles['floating-step']}>
                {getStatusIcon(step.status)}
                <span className={styles['floating-step-title']}>{getTaskTitle(step)}</span>
              </div>
            ))}
          </div>
        )}
        {currentMeta.toolEvents.length > 0 && (
          <div className={styles['floating-execution-tools']}>
            {currentMeta.toolEvents.map((tool) => (
              <div key={tool.id} className={styles['floating-tool']}>
                {getStatusIcon(tool.status)}
                <span className={styles['floating-tool-kind']}>{tool.kind}</span>
                <span className={styles['floating-tool-name']}>{tool.name}</span>
                {(tool.kind === 'task' || tool.kind === 'subagent') && tool.status === 'running' && (
                  <button
                    type="button"
                    className={styles['stop-agent-btn']}
                    onClick={() => void handleStopAgent(tool.id)}
                    title="停止此代理"
                  >
                    x
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={styles['chat-page']}>
      <div className={styles['chat-header']}>
        <div className={styles['chat-header-title']}>
          <button
            type="button"
            className={styles['history-toggle']}
            onClick={toggleHistorySidebar}
            title={historySidebarOpen ? '收起历史记录' : '展开历史记录'}
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
          onCreateConversation={() => void handleCreateConversation()}
          onSelectConversation={handleSelectConversation}
          onRenameConversation={handleRenameConversation}
          onDeleteConversation={handleDeleteConversation}
          onBatchDeleteConversations={handleBatchDeleteConversations}
          onRestoreConversation={handleRestoreConversation}
          onLoadMore={handleLoadMoreConversations}
        />

        <div className={styles['chat-main']}>
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

          {false && renderFloatingExecutionPanel()}

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
            onSend={(content, atts) => void handleSend(content, atts)}
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
    </div>
  )
}

export default ChatPage
