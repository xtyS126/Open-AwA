import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { X, Paperclip, Send, Square, PanelLeft } from 'lucide-react'
import { chatAPI, conversationAPI } from '@/shared/api/api'
import { useChatStore } from '@/features/chat/store/chatStore'
import { getActiveConversationId } from '@/features/chat/utils/chatCache'
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
import AssistantExecutionDetails from './components/AssistantExecutionDetails'
import { ReasoningContent } from './components/ReasoningContent'
import { MessageContent } from './components/MessageContent'
import styles from './ChatPage.module.css'

function sanitizeDisplayedError(message: string): string {
  return String(message || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/* 附件类型 */
interface FileAttachment {
  id: string
  file: File
  preview?: string   // 图片 blob URL
  uploading: boolean
  uploaded?: { url: string; name: string; size: number; type: 'image' | 'file' }
  error?: string
}

const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.txt', '.md', '.csv']
const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB
const IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp'])

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
  const [input, setInput] = useState('')
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
    loadCachedMessages,
    conversations,
    setConversations,
    upsertConversation,
    removeConversation,
    conversationsHasMore,
  } = useChatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const activeRequestIdRef = useRef(0)
  const activeAbortControllerRef = useRef<AbortController | null>(null)
  const isMountedRef = useRef(true)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const pendingConversationCreationRef = useRef<Promise<string> | null>(null)
  const [attachments, setAttachments] = useState<FileAttachment[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
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

  // Buffer references for background throttling
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
        // Adding a slight delay to ensure DOM is updated before scrolling
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
      loadCachedMessages(conversationId)
      setMessageMeta({})
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

  // 页面挂载或会话切换时加载历史消息
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

        // 历史加载失败不阻塞用户操作
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

  /* ---- 附件处理 ---- */

  const getFileExtension = (name: string) => {
    const dot = name.lastIndexOf('.')
    return dot >= 0 ? name.slice(dot).toLowerCase() : ''
  }

  const addAttachments = useCallback((files: File[]) => {
    const newAttachments: FileAttachment[] = []
    for (const file of files) {
      const ext = getFileExtension(file.name)
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        appLogger.warning({ event: 'file_rejected', module: 'chat_page', action: 'attach', status: 'failure', message: `不支持的文件类型: ${ext}` })
        continue
      }
      if (file.size > MAX_FILE_SIZE) {
        appLogger.warning({ event: 'file_rejected', module: 'chat_page', action: 'attach', status: 'failure', message: `文件过大: ${file.name}` })
        continue
      }
      const attachment: FileAttachment = {
        id: crypto.randomUUID(),
        file,
        uploading: false,
      }
      // 图片创建预览 URL
      if (IMAGE_EXTENSIONS.has(ext)) {
        attachment.preview = URL.createObjectURL(file)
      }
      newAttachments.push(attachment)
    }
    if (newAttachments.length > 0) {
      setAttachments(prev => [...prev, ...newAttachments])
    }
  }, [])

  const removeAttachment = useCallback((id: string) => {
    setAttachments(prev => {
      const removed = prev.find(a => a.id === id)
      if (removed?.preview) URL.revokeObjectURL(removed.preview)
      return prev.filter(a => a.id !== id)
    })
  }, [])

  const uploadAttachments = useCallback(async (items: FileAttachment[]): Promise<FileAttachment[]> => {
    const results: FileAttachment[] = []
    for (const item of items) {
      setAttachments(prev => prev.map(a => a.id === item.id ? { ...a, uploading: true } : a))
      try {
        const res = await chatAPI.upload(item.file)
        const data = res.data
        const uploaded = { ...item, uploading: false, uploaded: { url: data.url, name: data.original_name, size: data.size, type: data.type as 'image' | 'file' } }
        setAttachments(prev => prev.map(a => a.id === item.id ? uploaded : a))
        results.push(uploaded)
      } catch {
        setAttachments(prev => prev.map(a => a.id === item.id ? { ...a, uploading: false, error: '上传失败' } : a))
      }
    }
    return results
  }, [])

  /* 拖拽事件 */
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) addAttachments(files)
  }, [addAttachments])

  /* 粘贴图片 */
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files)
    if (files.length > 0) {
      addAttachments(files)
    }
  }, [addAttachments])

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : []
    if (files.length > 0) addAttachments(files)
    // 重置 input 以允许选择相同文件
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [addAttachments])

  /* 清理附件预览 URL */
  useEffect(() => {
    return () => {
      attachments.forEach(a => { if (a.preview) URL.revokeObjectURL(a.preview) })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const handleSend = async () => {
    if ((!input.trim() && attachments.length === 0) || isLoading) return

    let targetSessionId = sessionId
    if (!targetSessionId || targetSessionId === 'default') {
      targetSessionId = await ensureConversationSession()
    }

    const userMessage = input.trim()
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

    // 先上传待上传的附件
    let uploadedAttachments: FileAttachment[] = []
    const pendingUploads = attachments.filter(a => !a.uploaded && !a.error)
    if (pendingUploads.length > 0) {
      uploadedAttachments = await uploadAttachments(pendingUploads)
    } else {
      uploadedAttachments = attachments.filter(a => a.uploaded)
    }

    // 构造消息文本（附件信息附加到消息末尾）
    let fullMessage = userMessage
    if (uploadedAttachments.length > 0) {
      const fileRefs = uploadedAttachments
        .filter(a => a.uploaded)
        .map(a => `[附件: ${a.uploaded!.name}](${a.uploaded!.url})`)
        .join('\n')
      if (fileRefs) {
        fullMessage = fullMessage ? `${fullMessage}\n\n${fileRefs}` : fileRefs
      }
    }

    if (!fullMessage) return

    const currentConversation = conversations.find((item) => item.session_id === targetSessionId)
    const nowIso = new Date().toISOString()
    if (currentConversation) {
      upsertConversation({
        ...currentConversation,
        title: currentConversation.title || userMessage.slice(0, 80) || '新对话',
        summary: userMessage.slice(0, 160),
        last_message_preview: userMessage.slice(0, 160),
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
      extra: { session_id: targetSessionId, input_length: fullMessage.length, mode: outputMode, attachments: uploadedAttachments.length },
    })
    setInput('')
    setAttachments([])
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
                  updateAssistantMeta(assistantMessageId, (current) => mergeExecutionMeta(current, nextMeta))
                  return
                }

                if (event?.type === 'task' && event.task && typeof event.task === 'object') {
                  updateAssistantMeta(assistantMessageId, (current) => applyTaskUpdate(current, event.task))
                  return
                }

                if (event?.type === 'tool' && event.tool && typeof event.tool === 'object') {
                  updateAssistantMeta(assistantMessageId, (current) => applyToolUpdate(current, event.tool))
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
                }
              },
              (error) => {
                runtimeError = error instanceof Error ? error : new Error(String(error))
              },
              { signal: abortController.signal }
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

        if (!isMountedRef.current || activeRequestIdRef.current !== requestId || streamErrorHandled) {
          return
        }
      } else {
        const response = await chatAPI.sendMessage(fullMessage, targetSessionId, provider, model, 'direct', {
          signal: abortController.signal,
        })
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

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

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
          <div
            className={`${styles['chat-messages']} ${isDragOver ? styles['drag-over'] : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {messages.length === 0 && (
              <div className={styles['chat-empty']}>
                <p>你好！有什么可以帮助你的吗？</p>
              </div>
            )}

            {messages.map((message, index) => {
              const isLastMessage = index === messages.length - 1
              const isCurrentlyStreaming = streamingAssistantId === message.id && isLastMessage && message.role === 'assistant'
              
              return (
                <div
                  key={message.id}
                  className={`${styles['message']} ${message.role === 'user' ? styles['user'] : styles['assistant']}`}
                >
                  <div className={styles['message-content']}>
                    {message.reasoning_content && (
                      <ReasoningContent 
                        messageId={message.id}
                        content={message.reasoning_content}
                        isStreaming={isCurrentlyStreaming}
                      />
                    )}
                    {message.content && <MessageContent content={message.content} role={message.role} />}
                    {message.role === 'assistant' && messageMeta[message.id] && hasExecutionMeta(messageMeta[message.id]) && (
                      <AssistantExecutionDetails
                        messageId={message.id}
                        meta={messageMeta[message.id]}
                        isStreaming={isCurrentlyStreaming}
                      />
                    )}
                  </div>
                </div>
              )
            })}

            {isLoading && !streamingAssistantId && (
              <div className={`${styles['message']} ${styles['assistant']}`}>
                <div className={styles['message-content']}>
                  <p className={styles['loading-text']}>
                    {outputMode === 'stream' && streamStatusText ? `${streamStatusText}...` : '思考中...'}
                  </p>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {renderFloatingExecutionPanel()}
          <div className={styles['chat-input-container']}>
            {attachments.length > 0 && (
              <div className={styles['attachments-preview']}>
                {attachments.map(att => (
                  <div key={att.id} className={styles['attachment-item']}>
                    {att.preview ? (
                      <img src={att.preview} alt={att.file.name} className={styles['attachment-thumb']} />
                    ) : (
                      <div className={styles['attachment-file-icon']}>
                        <span>{getFileExtension(att.file.name).slice(1).toUpperCase()}</span>
                      </div>
                    )}
                    {att.uploading && <div className={styles['attachment-uploading']} />}
                    {att.error && <div className={styles['attachment-error']} title={att.error}>!</div>}
                    <button
                      className={styles['attachment-remove']}
                      onClick={() => removeAttachment(att.id)}
                      title="移除附件"
                    >
                      <X size={10} strokeWidth={2.5} />
                    </button>
                    <span className={styles['attachment-name']}>{att.file.name}</span>
                  </div>
                ))}
              </div>
            )}
            <div className={styles['input-row']}>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={ALLOWED_EXTENSIONS.join(',')}
                onChange={handleFileInputChange}
                style={{ display: 'none' }}
              />
              <button
                className={styles['attach-btn']}
                onClick={() => fileInputRef.current?.click()}
                title="添加附件"
                disabled={isLoading}
              >
                <Paperclip size={20} strokeWidth={2} />
              </button>
              <textarea
                className={styles['chat-input']}
                placeholder="输入你的问题..."
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={handleKeyPress}
                onPaste={handlePaste}
                rows={1}
              />
              {streamingAssistantId ? (
                <button
                  className={`btn ${styles['stop-btn']}`}
                  onClick={() => activeAbortControllerRef.current?.abort()}
                  title="停止生成"
                >
                  <Square size={18} />
                </button>
              ) : (
                <button
                  className={`btn btn-primary ${styles['send-btn']}`}
                  onClick={() => void handleSend()}
                  disabled={(!input.trim() && attachments.length === 0) || isLoading}
                >
                  <Send size={18} />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ChatPage
