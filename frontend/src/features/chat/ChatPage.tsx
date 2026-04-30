import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PanelLeft } from 'lucide-react'
import { chatAPI, conversationAPI } from '@/shared/api/api'
import { useChatStore } from '@/features/chat/store/chatStore'
import { getActiveConversationId, getCachedConversationMessages } from '@/features/chat/utils/chatCache'
import type { AssistantExecutionMeta, ConversationSessionSummary, TaskStatus } from '@/features/chat/types'
import {
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
import { appLogger } from '@/shared/utils/logger'
import { dispatchBillingUsageUpdated } from '@/shared/events/billingEvents'
import ConversationSidebar from './components/ConversationSidebar'
import { MessageList } from './components/MessageList'
import { ChatInput } from './components/ChatInput'
import type { FileAttachment } from './components/ChatInput'
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

function ChatPage() {
  const navigate = useNavigate()
  const { conversationId } = useParams<{ conversationId?: string }>()
  const {
    messages,
    addMessage,
    updateLastMessage,
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

  const bufferRef = useRef({
    content: '',
    reasoning: '',
    lastUpdateTime: Date.now()
  })

  const flushBuffer = useCallback(() => {
    if (bufferRef.current.content || bufferRef.current.reasoning) {
      updateLastMessage(bufferRef.current.content, bufferRef.current.reasoning)
      bufferRef.current.content = ''
      bufferRef.current.reasoning = ''
      bufferRef.current.lastUpdateTime = Date.now()
    }
  }, [updateLastMessage])

  const scrollToBottom = useCallback(() => {
    if (document.hidden) return
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, messageMeta, scrollToBottom])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      activeAbortControllerRef.current?.abort()
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
      const cachedMsgs = getCachedConversationMessages(conversationId)
      // 从缓存恢复 messageMeta
      const restoredMeta: Record<string, AssistantExecutionMeta> = {}
      for (const msg of cachedMsgs) {
        if (msg.role === 'assistant' && msg.toolEvents && msg.toolEvents.length > 0) {
          restoredMeta[msg.id] = {
            steps: [],
            toolEvents: msg.toolEvents,
          }
        }
      }
      loadCachedMessages(conversationId)
      setMessageMeta(restoredMeta)
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
        if (Array.isArray(history) && history.length > 0) {
          const restored = history.map((msg: { id: string; role: string; content: string; timestamp: string }) => ({
            id: msg.id?.toString() || crypto.randomUUID(),
            role: msg.role as 'user' | 'assistant',
            content: msg.content,
            timestamp: new Date(msg.timestamp),
          }))
          setMessages(restored)
          setMessageMeta({})
          appLogger.info({
            event: 'chat_history_loaded',
            module: 'chat_page',
            action: 'load_history',
            status: 'success',
            message: `loaded ${restored.length} history messages`,
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
  }, [historyInitialized, recoverUnavailableConversation, sessionId, setMessages])

  const updateAssistantMeta = useCallback((messageId: string, updater: (current: AssistantExecutionMeta) => AssistantExecutionMeta) => {
    setMessageMeta((prev) => ({
      ...prev,
      [messageId]: updater(prev[messageId] || createEmptyExecutionMeta()),
    }))
  }, [])

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

  const handleSend = async (userMessage?: string, uploadedAttachments?: FileAttachment[]) => {
    const messageText = (userMessage || '').trim()
    const safeAttachments = uploadedAttachments || []
    if (!messageText && safeAttachments.length === 0) return
    if (isLoading) return

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
    let assistantMessageCreated = false
    const userMessageId = crypto.randomUUID()
    const assistantMessageId = crypto.randomUUID()

    const ensureAssistantMessage = (content = '', reasoning = '') => {
      if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
        return false
      }
      if (!assistantMessageCreated) {
        addMessage('assistant', content, reasoning || undefined, assistantMessageId)
        assistantMessageCreated = true
        setStreamingAssistantId(assistantMessageId)
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
    if (currentConversation) {
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
    addMessage('user', fullMessage, undefined, userMessageId)
    setLoading(true)
    setStreamingAssistantId(null)
    setStreamErrorMessage(null)
    setStreamRetryCount(0)
    setStreamStageMessage(null)
    setStreamConnectionState(outputMode === 'stream' ? 'connecting' : 'idle')

    try {
      const { provider, model } = parseSelectedModel(selectedModel)

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

                  if (document.hidden) {
                    bufferRef.current.content += content
                    bufferRef.current.reasoning += reasoning
                    const now = Date.now()
                    if (now - bufferRef.current.lastUpdateTime > 1000) {
                      flushBuffer()
                    }
                  } else {
                    if (bufferRef.current.content || bufferRef.current.reasoning) {
                      updateLastMessage(
                        bufferRef.current.content + content,
                        bufferRef.current.reasoning + reasoning
                      )
                      bufferRef.current.content = ''
                      bufferRef.current.reasoning = ''
                      bufferRef.current.lastUpdateTime = Date.now()
                    } else {
                      updateLastMessage(content, reasoning)
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
                  return
                }

                if (event?.type === 'task' && event.task && typeof event.task === 'object') {
                  updateAssistantMeta(assistantMessageId, (current) => applyTaskUpdate(current, event.task))
                  return
                }

                if (event?.type === 'tool' && event.tool && typeof event.tool === 'object') {
                  updateAssistantMeta(assistantMessageId, (current) => {
                    // 自动计算 sequence 序号
                    const toolData = event.tool as Record<string, unknown>
                    const nextSequence = current.toolEvents.length + 1
                    return applyToolUpdate(current, {
                      ...toolData,
                      sequence: toolData.sequence ?? nextSequence,
                      // 捕获 input 字段
                      input: toolData.input || toolData.arguments || toolData.args,
                    })
                  })
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
                  // 流结束时的持久化同步
                  setMessageMeta((prev) => {
                    const currentMeta = prev[assistantMessageId]
                    if (currentMeta?.toolEvents && currentMeta.toolEvents.length > 0) {
                      updateMessage(assistantMessageId, (msg) => ({
                        ...msg,
                        toolEvents: currentMeta.toolEvents,
                      }))
                    }
                    return prev
                  })
                }
              },
              (error) => {
                runtimeError = error instanceof Error ? error : new Error(String(error))
              },
              { signal: abortController.signal },
              thinkingEnabled ? { thinking_enabled: true, thinking_depth: thinkingDepth } : undefined,
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
            flushBuffer()
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
            } else {
              updateLastMessage(`\n\n[流中断：${sanitizeDisplayedError(normalizedError.message)}]`)
            }
            throw normalizedError
          }
        }
        flushBuffer()
        setStreamStageMessage(null)
        setStreamConnectionState('idle')

        // 流式完成时，将 toolEvents 持久化到消息对象
        setMessageMeta((prev) => {
          const metaForMsg = prev[assistantMessageId]
          if (metaForMsg?.toolEvents && metaForMsg.toolEvents.length > 0) {
            updateMessage(assistantMessageId, (msg) => ({
              ...msg,
              toolEvents: metaForMsg.toolEvents,
            }))
          }
          return prev
        })

        if (!isMountedRef.current || activeRequestIdRef.current !== requestId || streamErrorHandled) {
          return
        }
      } else {
        const response = await chatAPI.sendMessage(fullMessage, targetSessionId, provider, model, 'direct', {
          signal: abortController.signal,
        }, thinkingEnabled ? { thinking_enabled: true, thinking_depth: thinkingDepth } : undefined, chatAttachments.length > 0 ? chatAttachments : undefined)
        if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
          return
        }
        const assistantText = response.data.response
        const backendError = response.data.error
        const reasoningContent = response.data.reasoning_content
        const nextMeta = buildExecutionMetaFromPayload(response.data)

        if (assistantText && assistantText.trim()) {
          addMessage('assistant', assistantText, reasoningContent || undefined, assistantMessageId)
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
        } else {
          addMessage('assistant', '抱歉，当前未返回有效内容，请稍后重试。', undefined, assistantMessageId)
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
        addMessage('assistant', '抱歉，发生了错误。请稍后重试。')
      }
    } finally {
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

  const handleCreateConversation = useCallback(async () => {
    setMessageMeta({})
    setStreamingAssistantId(null)
    setStreamConnectionState('idle')
    setStreamRetryCount(0)
    setStreamErrorMessage(null)
    setStreamStageMessage(null)
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

          {renderFloatingExecutionPanel()}
          <ChatInput
            onSend={(content, atts) => void handleSend(content, atts)}
            isLoading={isLoading}
            streamingAssistantId={streamingAssistantId}
            onAbort={() => activeAbortControllerRef.current?.abort()}
          />
        </div>
      </div>
    </div>
  )
}

export default ChatPage
