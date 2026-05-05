import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PanelLeft } from 'lucide-react'
import { chatAPI, conversationAPI, type ChatContinuationPayload } from '@/shared/api/api'
import { useChatStore } from '@/features/chat/store/chatStore'
import {
  flushCachedConversationMessages,
  getActiveConversationId,
  getCachedConversationMessages,
} from '@/features/chat/utils/chatCache'
import { safeGetJsonItem } from '@/shared/utils/safeStorage'
import type {
  AssistantExecutionMeta,
  AssistantMessageSegment,
  ChatMessage,
  ConversationSessionSummary,
  TaskStatus,
} from '@/features/chat/types'
import {
  applySubagentMessage,
  applySubagentStart,
  applySubagentStop,
  syncSubagentSnapshot,
  applySubagentTimeout,
  buildSubagentTranscriptText,
  summarizeExecutionResult,
  setSubagentAggregation,
  SUBAGENT_INACTIVITY_TIMEOUT_MS,
  applyTaskUpdate,
  applyToolUpdate,
  buildExecutionMetaFromPayload,
  createEmptyExecutionMeta,
  formatUsageCost,
  formatUsageTokens,
  getTaskTitle,
  hasExecutionMeta,
  mergeExecutionMeta,
  normalizeUsage,
} from '@/features/chat/utils/executionMeta'
import {
  appendAssistantChunk,
  applyIntentToSegments,
  applyStepToSegments,
  applyToolEventToSegments,
  applyToolPatchToSegments,
  applyUsageToSegments,
  finalizeAssistantSegments,
  buildSegmentsFromLegacyMessage,
} from '@/features/chat/utils/assistantSegments'
import { getAgent, getTranscript, stopAgent } from '@/shared/api/taskRuntimeApi'
import { appLogger } from '@/shared/utils/logger'
import { dispatchBillingUsageUpdated } from '@/shared/events/billingEvents'
import { useToast } from '@/shared/components/Toast'
import ConversationSidebar from './components/ConversationSidebar'
import { MessageList } from './components/MessageList'
import { ChatInput } from './components/ChatInput'
import type { FileAttachment } from './components/ChatInput'
import { TaskPanel } from './components/TaskPanel'
import styles from './ChatPage.module.css'

function sanitizeDisplayedError(message: string): string {
  return String(message || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

type StreamConnectionState = 'idle' | 'connecting' | 'streaming' | 'retrying' | 'error'

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

function getStreamStatusText(
  state: StreamConnectionState,
  retryCount: number,
  errorMessage: string | null,
  stageMessage: string | null
): string {
  switch (state) {
    case 'error':
      return errorMessage ? `流式连接失败：${errorMessage}` : '流式连接失败'
    case 'retrying':
      return `正在重连流式通道（第 ${retryCount} 次）`
    case 'connecting':
      return '正在连接流式通道'
    case 'streaming':
      return stageMessage || '正在流式生成'
    default:
      return ''
  }
}

type ConversationSortKey = 'last_message_at' | 'title'

interface ChatAppSettings {
  maxToolCallRounds?: number
}

const HISTORY_PAGE_SIZE = 20

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
    setConversations,
    upsertConversation,
    removeConversation,
    conversationsHasMore,
    thinkingEnabled,
    setThinkingEnabled,
    thinkingDepth,
    setThinkingDepth,
  } = useChatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const activeRequestIdRef = useRef(0)
  const activeAbortControllerRef = useRef<AbortController | null>(null)
  const isMountedRef = useRef(true)
  const pendingConversationCreationRef = useRef<Promise<string> | null>(null)
  const [messageMeta, setMessageMeta] = useState<Record<string, AssistantExecutionMeta>>({})
  const [streamingAssistantId, setStreamingAssistantId] = useState<string | null>(null)
  const [historySidebarOpen, setHistorySidebarOpen] = useState(() => window.innerWidth > 960)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historySearchInput, setHistorySearchInput] = useState('')
  const [historySearch, setHistorySearch] = useState('')
  const [historySort, setHistorySort] = useState<ConversationSortKey>('last_message_at')
  const [historyPage, setHistoryPage] = useState(1)
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [historyInitialized, setHistoryInitialized] = useState(false)
  const [streamConnectionState, setStreamConnectionState] = useState<StreamConnectionState>('idle')
  const [streamRetryCount, setStreamRetryCount] = useState(0)
  const [streamErrorMessage, setStreamErrorMessage] = useState<string | null>(null)
  const [streamStageMessage, setStreamStageMessage] = useState<string | null>(null)
  const [taskPanelManuallyToggled, setTaskPanelManuallyToggled] = useState(false)
  const [taskPanelExpanded, setTaskPanelExpanded] = useState(false)
  const { addToast, ToastContainer } = useToast()
  const messageMetaRef = useRef<Record<string, AssistantExecutionMeta>>({})
  const subagentTimeoutRef = useRef<Record<string, number>>({})
  const subagentSyncTimerRef = useRef<Record<string, number>>({})
  const subagentSyncInFlightRef = useRef<Record<string, boolean>>({})
  const subagentAggregationTimerRef = useRef<Record<string, number>>({})
  const aggregatedSubagentIdsRef = useRef<Record<string, Set<string>>>({})
  const syncSubagentRuntimeRef = useRef<(assistantMessageId: string, agentId: string, agentType?: string) => void>(() => {})
  const triggerSubagentContinuationRef = useRef<(assistantMessageId: string, aggregatedText: string) => void>(() => {})

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

  const flushConversationCache = useCallback((targetSessionId?: string) => {
    const resolvedSessionId = targetSessionId || useChatStore.getState().sessionId
    if (!resolvedSessionId || resolvedSessionId === 'default') {
      return
    }
    flushCachedConversationMessages(resolvedSessionId, useChatStore.getState().messages)
  }, [])

  const scrollToBottom = useCallback(() => {
    if (document.hidden) return
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, messageMeta, scrollToBottom])

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

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setHistorySearch(historySearchInput)
    }, 250)

    return () => {
      window.clearTimeout(timer)
    }
  }, [historySearchInput])

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
      const existingItems = append ? useChatStore.getState().conversations : []
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

  const createConversationAndNavigate = useCallback(async (replace: boolean = false) => {
    if (pendingConversationCreationRef.current) {
      return pendingConversationCreationRef.current
    }

    const pendingRequest = (async () => {
      setHistoryError(null)
      const response = await conversationAPI.createSession()
      const nextConversation = response.data as ConversationSessionSummary
      upsertConversation(nextConversation)
      setSessionId(nextConversation.session_id)
      setMessages([])
      setMessageMeta({})
      setStreamingAssistantId(null)
      setStreamConnectionState('idle')
      setStreamRetryCount(0)
      setStreamErrorMessage(null)
      setStreamStageMessage(null)
      navigate(`/chat/${nextConversation.session_id}`, { replace })
      return nextConversation.session_id
    })()

    pendingConversationCreationRef.current = pendingRequest

    try {
      return await pendingRequest
    } finally {
      pendingConversationCreationRef.current = null
    }
  }, [navigate, setMessages, setSessionId, upsertConversation])

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
    setStreamConnectionState('idle')
    setStreamRetryCount(0)
    setStreamErrorMessage(null)
    setStreamStageMessage(null)

    const fallbackConversation = useChatStore.getState().conversations.find(
      (item) => item.session_id !== missingSessionId && !item.deleted_at
    )

    if (fallbackConversation) {
      navigate(`/chat/${fallbackConversation.session_id}`, { replace: true })
      return
    }

    await createConversationAndNavigate(true)
  }, [createConversationAndNavigate, navigate, removeConversation, setMessages])

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
      setStreamConnectionState('idle')
      setStreamRetryCount(0)
      setStreamErrorMessage(null)
      setStreamStageMessage(null)
    }
  }, [conversationId, loadCachedMessages, sessionId, setSessionId])

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
      setStreamConnectionState('idle')
      setStreamRetryCount(0)
      setStreamErrorMessage(null)
      setStreamStageMessage(null)
      return
    }
    let cancelled = false
    const loadHistory = async () => {
      try {
        const response = await chatAPI.getHistory(sessionId)
        if (cancelled) return
        const history = response.data
        if (Array.isArray(history)) {
          const restored = history.map((msg: {
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
          flushConversationCache(sessionId)
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
  }, [flushConversationCache, historyInitialized, recoverUnavailableConversation, sessionId, setMessages])

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
      const toolMeta = applySubagentTimeout(createEmptyExecutionMeta(), {
        agentId,
        agentType,
        message: timeoutMessage,
      }).toolEvents[0]

      updateAssistantMeta(assistantMessageId, (current) => applySubagentTimeout(current, {
        agentId,
        agentType,
        message: timeoutMessage,
      }))
      if (toolMeta) {
        updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
      }
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
      return { provider: undefined, model: undefined }
    }

    return {
      provider: value.slice(0, separatorIndex),
      model: value.slice(separatorIndex + 1)
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

    if (!fullMessage) return

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
    setStreamErrorMessage(null)
    setStreamRetryCount(0)
    setStreamStageMessage(null)
    setStreamConnectionState(outputMode === 'stream' ? 'connecting' : 'idle')

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
            setStreamRetryCount(attempt)
            setStreamConnectionState('retrying')
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

                setStreamConnectionState('streaming')
                setStreamErrorMessage(null)

                if (event?.type === 'status') {
                  const nextStageMessage = typeof event.message === 'string' ? event.message.trim() : ''
                  setStreamStageMessage(nextStageMessage || null)
                  return
                }

                if (event?.type === 'chunk') {
                  const content = typeof event.content === 'string' ? event.content : ''
                  const reasoning = typeof event.reasoning_content === 'string' ? event.reasoning_content : ''
                  if (!assistantMessageCreated) {
                    ensureAssistantMessage(content, reasoning)
                    bufferRef.current.lastUpdateTime = Date.now()
                    return
                  }

                  if (content || reasoning) {
                    updateAssistantSegments(assistantMessageId, (segments) => appendAssistantChunk(segments, {
                      content,
                      reasoningContent: reasoning,
                    }))
                  }

                  if (document.hidden) {
                    bufferRef.current.content += content
                    bufferRef.current.reasoning += reasoning
                    const now = Date.now()
                    if (now - bufferRef.current.lastUpdateTime > 1000) {
                      flushBuffer(assistantMessageId)
                    }
                  } else {
                    if (bufferRef.current.content || bufferRef.current.reasoning) {
                      appendAssistantMessageText(
                        assistantMessageId,
                        bufferRef.current.content + content,
                        bufferRef.current.reasoning + reasoning
                      )
                      bufferRef.current.content = ''
                      bufferRef.current.reasoning = ''
                      bufferRef.current.lastUpdateTime = Date.now()
                    } else {
                      appendAssistantMessageText(assistantMessageId, content, reasoning)
                    }
                  }
                  return
                }

                ensureAssistantMessage()

                if (event?.type === 'plan' || event?.type === 'result') {
                  const nextMeta = buildExecutionMetaFromPayload(event)
                  updateAssistantMeta(assistantMessageId, (current) => {
                    const merged = mergeExecutionMeta(current, nextMeta)
                    // 对于 result 事件，尝试提取 output 更新到对应 toolEvent
                    if (event?.type === 'result' && event.result && typeof event.result === 'object') {
                      const resultData = event.result as Record<string, unknown>
                      const toolId = typeof resultData.tool_id === 'string' ? resultData.tool_id : undefined
                      const output = resultData.output !== undefined ? resultData.output : resultData
                      if (toolId && output) {
                        const toolEvents = merged.toolEvents.map((t) =>
                          t.id === toolId
                            ? { ...t, output, completedAt: t.completedAt || Date.now(), status: t.status === 'running' ? ('completed' as const) : t.status }
                            : t
                        )
                        return { ...merged, toolEvents }
                      }
                    }
                    return merged
                  })
                  if (nextMeta.intent) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyIntentToSegments(segments, nextMeta.intent!))
                  }
                  if (nextMeta.steps.length > 0) {
                    updateAssistantSegments(assistantMessageId, (segments) => {
                      let nextSegments = segments || []
                      for (const step of nextMeta.steps) {
                        nextSegments = applyStepToSegments(nextSegments, step)
                      }
                      return nextSegments
                    })
                  }
                  if (event?.type === 'result' && event.result && typeof event.result === 'object') {
                    const resultData = event.result as Record<string, unknown>
                    const toolId = typeof resultData.tool_id === 'string' ? resultData.tool_id : undefined
                    const output = resultData.output !== undefined ? resultData.output : resultData
                    if (toolId && output !== undefined) {
                      updateAssistantSegments(assistantMessageId, (segments) => applyToolPatchToSegments(segments, toolId, {
                        output,
                        detail: summarizeExecutionResult(output),
                        status: 'completed',
                        completedAt: Date.now(),
                      }))
                    }
                  }
                  return
                }

                if (event?.type === 'task' && event.task && typeof event.task === 'object') {
                  updateAssistantMeta(assistantMessageId, (current) => applyTaskUpdate(current, event.task))
                  const stepMeta = applyTaskUpdate(createEmptyExecutionMeta(), event.task as Record<string, unknown>).steps[0]
                  if (stepMeta) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyStepToSegments(segments, stepMeta))
                  }
                  return
                }

                if (event?.type === 'tool' && event.tool && typeof event.tool === 'object') {
                  const toolData = event.tool as Record<string, unknown>
                  const normalizedToolData = {
                    ...toolData,
                    sequence: toolData.sequence ?? ((messageMeta[assistantMessageId]?.toolEvents.length || 0) + 1),
                    input: toolData.input || toolData.arguments || toolData.args,
                  }
                  updateAssistantMeta(assistantMessageId, (current) => {
                    const nextSequence = current.toolEvents.length + 1
                    return applyToolUpdate(current, {
                      ...normalizedToolData,
                      sequence: toolData.sequence ?? nextSequence,
                    })
                  })
                  const toolMeta = applyToolUpdate(createEmptyExecutionMeta(), normalizedToolData).toolEvents[0]
                  if (toolMeta) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
                  }
                  return
                }

                if (event?.type === 'subagent_start' && event.agent_id) {
                  const agentId = event.agent_id as string
                  const agentType = typeof event.agent_type === 'string' ? event.agent_type : undefined
                  const runMode = typeof event.run_mode === 'string' ? event.run_mode : undefined
                  const toolMeta = applySubagentStart(createEmptyExecutionMeta(), {
                    agentId,
                    agentType,
                    description: typeof event.description === 'string' ? event.description : '子代理已启动',
                  }).toolEvents[0]
                  updateAssistantMeta(assistantMessageId, (current) => applySubagentStart(current, {
                    agentId,
                    agentType,
                    description: typeof event.description === 'string' ? event.description : '子代理已启动',
                  }))
                  if (toolMeta) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
                  }
                  clearSubagentAggregationTimer(assistantMessageId)
                  scheduleSubagentTimeout(assistantMessageId, agentId, agentType)
                  if (!agentId.startsWith('sub_') && runMode !== 'foreground') {
                    syncSubagentRuntimeRef.current(assistantMessageId, agentId, agentType)
                  }
                  return
                }

                if (event?.type === 'subagent_stop' && event.agent_id) {
                  const agentId = event.agent_id as string
                  const agentType = typeof event.agent_type === 'string' ? event.agent_type : undefined
                  const summary = typeof event.summary === 'string' ? event.summary : `状态: ${event.state}`
                  const toolMeta = applySubagentStop(createEmptyExecutionMeta(), {
                    agentId,
                    agentType,
                    state: typeof event.state === 'string' ? event.state : undefined,
                    summary,
                  }).toolEvents[0]
                  updateAssistantMeta(assistantMessageId, (current) => applySubagentStop(current, {
                    agentId,
                    agentType,
                    state: typeof event.state === 'string' ? event.state : undefined,
                    summary,
                  }))
                  if (toolMeta) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
                    if (toolMeta.status === 'error') {
                      addToast(`Subagent ${agentType || agentId} 执行失败`, 'error')
                    }
                  }
                  clearSubagentTimeout(agentId)
                  clearSubagentSyncTimer(agentId)
                  scheduleSubagentAggregation(assistantMessageId)
                  return
                }

                if (event?.type === 'agent_message' && event.agent_id) {
                  const agentId = event.agent_id as string
                  const agentType = typeof event.agent_type === 'string' ? event.agent_type : undefined
                  const toolMeta = applySubagentMessage(createEmptyExecutionMeta(), {
                    agentId,
                    agentType,
                    message: typeof event.message === 'string' ? event.message : '子代理消息',
                  }).toolEvents[0]
                  updateAssistantMeta(assistantMessageId, (current) => applySubagentMessage(current, {
                    agentId,
                    agentType,
                    message: typeof event.message === 'string' ? event.message : '子代理消息',
                  }))
                  if (toolMeta) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
                  }
                  scheduleSubagentTimeout(assistantMessageId, agentId, agentType)
                  return
                }

                // 任务清单生命周期事件
                if (event?.type === 'task_created' && event.task) {
                  updateAssistantMeta(assistantMessageId, (current) => {
                    return applyTaskUpdate(current, {
                      ...event.task,
                      status: 'created',
                    })
                  })
                  const stepMeta = applyTaskUpdate(createEmptyExecutionMeta(), {
                    ...(event.task as Record<string, unknown>),
                    status: 'created',
                  }).steps[0]
                  if (stepMeta) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyStepToSegments(segments, stepMeta))
                  }
                  return
                }

                if (event?.type === 'task_updated' && event.task) {
                  updateAssistantMeta(assistantMessageId, (current) => {
                    return applyTaskUpdate(current, event.task)
                  })
                  const stepMeta = applyTaskUpdate(createEmptyExecutionMeta(), event.task as Record<string, unknown>).steps[0]
                  if (stepMeta) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyStepToSegments(segments, stepMeta))
                  }
                  return
                }

                if (event?.type === 'task_stopped' && event.task_id) {
                  const toolPayload = {
                    id: event.task_id as string,
                    kind: 'task',
                    name: '任务已停止',
                    status: 'completed',
                    detail: typeof event.summary === 'string' ? event.summary : '任务已停止',
                  }
                  updateAssistantMeta(assistantMessageId, (current) => {
                    return applyToolUpdate(current, toolPayload)
                  })
                  const toolMeta = applyToolUpdate(createEmptyExecutionMeta(), toolPayload).toolEvents[0]
                  if (toolMeta) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
                  }
                  return
                }

                // 团队生命周期事件（Phase 4）
                if (event?.type === 'team_event' && event.team) {
                  const toolPayload = {
                    id: event.team.team_id || `team_${Date.now()}`,
                    kind: 'task',
                    name: `团队: ${event.team.name || '未命名'}`,
                    status: event.team.ok === false ? 'failed' : 'running',
                    detail:
                      typeof event.team.state === 'string'
                        ? `团队状态: ${event.team.state}`
                        : '团队操作已完成',
                  }
                  updateAssistantMeta(assistantMessageId, (current) => {
                    return applyToolUpdate(current, toolPayload)
                  })
                  const toolMeta = applyToolUpdate(createEmptyExecutionMeta(), toolPayload).toolEvents[0]
                  if (toolMeta) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
                  }
                  return
                }

                if (event?.type === 'usage' && event.usage) {
                  const usage = normalizeUsage(event.usage)
                  updateAssistantMeta(assistantMessageId, (current) => ({
                    ...current,
                    usage: usage || current.usage,
                  }))
                  if (usage) {
                    dispatchBillingUsageUpdated({
                      callId: usage.call_id,
                      provider: usage.provider,
                      model: usage.model,
                    })
                  }
                  if (usage) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyUsageToSegments(segments, usage))
                  }
                }
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
              setStreamRetryCount(attempt + 1)
              setStreamConnectionState('retrying')
              continue
            }

            streamErrorHandled = true
            flushBuffer(assistantMessageId)
            setStreamConnectionState('error')
            setStreamErrorMessage(sanitizeDisplayedError(normalizedError.message))
            appLogger.error({
              event: 'chat_stream_error',
              module: 'chat_page',
              action: 'receive_stream',
              status: 'failure',
              message: 'chat stream error',
              extra: { error: normalizedError.message, retry_count: attempt },
            })
            if (!assistantMessageCreated) {
              addMessage('assistant', `请求失败：${sanitizeDisplayedError(normalizedError.message)}`, undefined, assistantMessageId)
              assistantMessageCreated = true
              updateAssistantSegments(assistantMessageId, (segments) => appendAssistantChunk(segments, {
                content: `请求失败：${sanitizeDisplayedError(normalizedError.message)}`,
              }))
            } else {
              appendAssistantMessageText(assistantMessageId, `\n\n[流中断：${sanitizeDisplayedError(normalizedError.message)}]`)
              updateAssistantSegments(assistantMessageId, (segments) => appendAssistantChunk(segments, {
                content: `\n\n[流中断：${sanitizeDisplayedError(normalizedError.message)}]`,
              }))
            }
            finalizeAssistantMessageSegments(assistantMessageId)
            throw normalizedError
          }
        }
        flushBuffer(assistantMessageId)
        finalizeAssistantMessageSegments(assistantMessageId)
        setStreamStageMessage(null)
        setStreamConnectionState('idle')

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
        const assistantText = response.data.response
        const backendError = response.data.error
        const reasoningContent = response.data.reasoning_content
        const nextMeta = buildExecutionMetaFromPayload(response.data)

        if (assistantText && assistantText.trim()) {
          addMessage('assistant', assistantText, reasoningContent || undefined, assistantMessageId)
          updateMessage(assistantMessageId, (message) => ({
            ...message,
            segments: buildSegmentsFromLegacyMessage({
              content: assistantText,
              reasoningContent: reasoningContent || undefined,
              meta: nextMeta,
            }),
          }))
          if (hasExecutionMeta(nextMeta)) {
            setMessageMeta((prev) => ({ ...prev, [assistantMessageId]: nextMeta }))
            // 直接模式下同步持久化 toolEvents
            if (nextMeta.toolEvents.length > 0) {
              updateMessage(assistantMessageId, (msg) => ({
                ...msg,
                toolEvents: nextMeta.toolEvents,
              }))
            }
          }
          if (nextMeta.usage) {
            dispatchBillingUsageUpdated({
              callId: nextMeta.usage.call_id,
              provider: nextMeta.usage.provider,
              model: nextMeta.usage.model,
            })
          }
        } else if (backendError?.message) {
          addMessage('assistant', `请求失败：${sanitizeDisplayedError(backendError.message)}`)
          updateMessage(assistantMessageId, (message) => ({
            ...message,
            segments: buildSegmentsFromLegacyMessage({
              content: `请求失败：${sanitizeDisplayedError(backendError.message)}`,
            }),
          }))
        } else if (reasoningContent || hasExecutionMeta(nextMeta)) {
          addMessage('assistant', '', reasoningContent || undefined, assistantMessageId)
          updateMessage(assistantMessageId, (message) => ({
            ...message,
            segments: buildSegmentsFromLegacyMessage({
              reasoningContent: reasoningContent || undefined,
              meta: nextMeta,
            }),
          }))
          if (hasExecutionMeta(nextMeta)) {
            setMessageMeta((prev) => ({ ...prev, [assistantMessageId]: nextMeta }))
            if (nextMeta.toolEvents.length > 0) {
              updateMessage(assistantMessageId, (msg) => ({
                ...msg,
                toolEvents: nextMeta.toolEvents,
              }))
            }
          }
          if (nextMeta.usage) {
            dispatchBillingUsageUpdated({
              callId: nextMeta.usage.call_id,
              provider: nextMeta.usage.provider,
              model: nextMeta.usage.model,
            })
          }
        } else {
          addMessage('assistant', '抱歉，当前未返回有效内容，请稍后重试。', undefined, assistantMessageId)
          updateMessage(assistantMessageId, (message) => ({
            ...message,
            segments: buildSegmentsFromLegacyMessage({
              content: '抱歉，当前未返回有效内容，请稍后重试。',
              reasoningContent: reasoningContent || undefined,
              meta: nextMeta,
            }),
          }))
          if (hasExecutionMeta(nextMeta)) {
            setMessageMeta((prev) => ({ ...prev, [assistantMessageId]: nextMeta }))
          }
          if (nextMeta.usage) {
            dispatchBillingUsageUpdated({
              callId: nextMeta.usage.call_id,
              provider: nextMeta.usage.provider,
              model: nextMeta.usage.model,
            })
          }
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        setStreamStageMessage(null)
        setStreamConnectionState('idle')
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
          addMessage('assistant', '抱歉，发生了错误。请稍后重试。', undefined, assistantMessageId)
          assistantMessageCreated = true
        } else {
          appendAssistantMessageText(assistantMessageId, '抱歉，发生了错误。请稍后重试。')
        }
        updateAssistantSegments(assistantMessageId, (segments) => appendAssistantChunk(segments, {
          content: '抱歉，发生了错误。请稍后重试。',
        }))
      }
    } finally {
      flushConversationCache(targetSessionId)
      if (targetSessionId && targetSessionId !== 'default') {
        void loadConversationList(1, false)
      }
      if (isMountedRef.current && activeRequestIdRef.current === requestId) {
        setLoading(false)
        setStreamingAssistantId(null)
        setStreamStageMessage(null)
        if (!streamErrorHandled) {
          setStreamConnectionState('idle')
        }
      }
    }
  }

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

  const handleCreateConversation = useCallback(async () => {
    setMessageMeta({})
    setStreamingAssistantId(null)
    setStreamConnectionState('idle')
    setStreamRetryCount(0)
    setStreamErrorMessage(null)
    setStreamStageMessage(null)
    setTaskPanelManuallyToggled(false)
    setTaskPanelExpanded(false)
    await createConversationAndNavigate(false)
  }, [createConversationAndNavigate])

  const handleSelectConversation = useCallback((nextSessionId: string) => {
    if (!nextSessionId || nextSessionId === sessionId) {
      if (window.innerWidth <= 960) {
        setHistorySidebarOpen(false)
      }
      return
    }
    setMessageMeta({})
    setStreamingAssistantId(null)
    setStreamConnectionState('idle')
    setStreamRetryCount(0)
    setStreamErrorMessage(null)
    setStreamStageMessage(null)
    setTaskPanelManuallyToggled(false)
    setTaskPanelExpanded(false)
    navigate(`/chat/${nextSessionId}`)
    if (window.innerWidth <= 960) {
      setHistorySidebarOpen(false)
    }
  }, [navigate, sessionId])

  const handleRenameConversation = useCallback(async (targetSessionId: string, title: string) => {
    const response = await conversationAPI.renameSession(targetSessionId, title)
    upsertConversation(response.data as ConversationSessionSummary)
  }, [upsertConversation])

  const handleDeleteConversation = useCallback(async (targetSessionId: string) => {
    if (!window.confirm('确认删除这个对话吗？删除后可在 30 天内恢复。')) {
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
    if (!window.confirm(`确认删除选中的 ${sessionIds.length} 个对话吗？删除后可在 30 天内恢复。`)) {
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
              summary: '已手动停止',
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
      case 'completed': return <span className={styles['status-dot-completed']} title="已完成" />
      case 'running': return <span className={styles['status-dot-running']} title="执行中" />
      case 'error': return <span className={styles['status-dot-error']} title="失败" />
      default: return <span className={styles['status-dot-pending']} title="等待" />
    }
  }

  const getLatestActiveExecution = (): { meta: AssistantExecutionMeta; isStreaming: boolean } | null => {
    if (streamingAssistantId && messageMeta[streamingAssistantId]) {
      return { meta: messageMeta[streamingAssistantId], isStreaming: true }
    }
    if (streamingAssistantId) {
      return { meta: createEmptyExecutionMeta(), isStreaming: true }
    }
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i]
      if (msg.role === 'assistant' && messageMeta[msg.id] && hasExecutionMeta(messageMeta[msg.id])) {
        return { meta: messageMeta[msg.id], isStreaming: false }
      }
    }
    return null
  }

  // 任务面板自动折叠/展开
  const activeMetaForPanel = getLatestActiveExecution()
  const hasActiveTasks = activeMetaForPanel
    ? activeMetaForPanel.meta.steps.some((s) => s.status === 'running' || s.status === 'pending') ||
      activeMetaForPanel.meta.toolEvents.some((t) => t.status === 'running' || t.status === 'pending') ||
      activeMetaForPanel.isStreaming
    : false

  useEffect(() => {
    if (taskPanelManuallyToggled) return
    setTaskPanelExpanded(hasActiveTasks)
  }, [hasActiveTasks, taskPanelManuallyToggled])

  const renderFloatingExecutionPanel = () => {
    const active = getLatestActiveExecution()
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

  const isCompactViewport = window.innerWidth <= 960
  const streamStatusText = getStreamStatusText(
    streamConnectionState,
    streamRetryCount,
    streamErrorMessage,
    streamStageMessage
  )

  return (
    <div className={styles['chat-page']}>
      <div className={styles['chat-header']}>
        <div className={styles['chat-header-title']}>
          <button
            type="button"
            className={styles['history-toggle']}
            onClick={() => setHistorySidebarOpen((prev) => !prev)}
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
          <button className={styles['history-overlay']} onClick={() => setHistorySidebarOpen(false)} aria-label="关闭历史记录遮罩" />
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
          onToggle={() => setHistorySidebarOpen((prev) => !prev)}
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
          />

          {false && renderFloatingExecutionPanel()}

          <TaskPanel
            steps={activeMetaForPanel?.meta.steps || []}
            toolEvents={activeMetaForPanel?.meta.toolEvents || []}
            isStreaming={activeMetaForPanel?.isStreaming || false}
            onStopAgent={(agentId) => void handleStopAgent(agentId)}
            expanded={taskPanelExpanded}
            onToggle={() => {
              setTaskPanelManuallyToggled(true)
              setTaskPanelExpanded((prev) => !prev)
            }}
          />

          <ChatInput
            onSend={(content, atts) => void handleSend(content, atts)}
            isLoading={isLoading}
            streamingAssistantId={streamingAssistantId}
            onAbort={() => activeAbortControllerRef.current?.abort()}
          />
        </div>
      </div>
      <ToastContainer />
    </div>
  )
}

export default ChatPage
