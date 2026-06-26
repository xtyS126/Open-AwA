import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PanelLeft } from 'lucide-react'
import { chatAPI, conversationAPI, diaryAPI } from '@/shared/api/api'
import { useConversationHistory } from '@/features/chat/hooks/useConversationHistory'
import { useStreamExecutionState } from '@/features/chat/hooks/useStreamExecutionState'
import { useTaskPanelState } from '@/features/chat/hooks/useTaskPanelState'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useModelStore } from '@/features/chat/store/modelStore'
import { useToolCallStore } from '@/features/chat/store/toolCallStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'
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
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { useChatStream } from './hooks/useChatStream'
import { useSubagentSync } from './hooks/useSubagentSync'
import { useMessageCache } from './hooks/useMessageCache'
import { usePermissionRequest } from './hooks/usePermissionRequest'
import { useChatAutoScroll } from './hooks/useChatAutoScroll'
import { useChatBroadcast } from './hooks/useChatBroadcast'
import type { ChatBroadcastEvent } from './hooks/useChatBroadcast'
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
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const t = useI18nStore(s => s.t)
  const { conversationId } = useParams<{ conversationId?: string }>()
  // 原子化 store selector：避免流式输出期间 messages 等高频字段变化导致整个聊天页重渲染
  // 数组/对象字段使用 shallow 做浅比较，避免内容相同时的假阳性重渲染
  // 分域 Store 拆分后，各域状态独立订阅，互不影响
  const messages = useSessionStore(s => s.messages, shallow)
  const conversations = useSessionStore(s => s.conversations, shallow)
  // 标量字段使用简单 selector（默认 === 比较）
  const isLoading = useSessionStore(s => s.isLoading)
  const sessionId = useSessionStore(s => s.sessionId)
  const conversationsHasMore = useSessionStore(s => s.conversationsHasMore)
  const outputMode = usePreferenceStore(s => s.outputMode)
  const selectedModel = useModelStore(s => s.selectedModel)
  const thinkingEnabled = usePreferenceStore(s => s.thinkingEnabled)
  const thinkingDepth = usePreferenceStore(s => s.thinkingDepth)
  // Actions — 在 create() 中定义后引用永不变，单独提取避免触发数据订阅
  const setLoading = useSessionStore(s => s.setLoading)
  const setSessionId = useSessionStore(s => s.setSessionId)
  const setOutputMode = usePreferenceStore(s => s.setOutputMode)
  const setMessages = useSessionStore(s => s.setMessages)
  const updateMessage = useSessionStore(s => s.updateMessage)
  const upsertConversation = useSessionStore(s => s.upsertConversation)
  const removeConversation = useSessionStore(s => s.removeConversation)
  const setThinkingEnabled = usePreferenceStore(s => s.setThinkingEnabled)
  const setThinkingDepth = usePreferenceStore(s => s.setThinkingDepth)
  const resetActiveToolCalls = useToolCallStore(s => s.resetActiveToolCalls)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  // 自动滚动 hook：暴露容器 ref、未读新内容标记、强制滚动方法、内容增长回调
  // threshold=150 表示用户距底部 150px 内视为"在底部附近"，自动跟随流式输出
  const {
    containerRef: scrollContainerRef,
    onContentGrow,
    hasNewContent,
    scrollToLatest,
  } = useChatAutoScroll({ threshold: 150, behavior: 'smooth' })
  const isMountedRef = useRef(true)
  const pendingConversationCreationRef = useRef<Promise<string> | null>(null)
  const [messageMeta, setMessageMeta] = useState<Record<string, import('@/features/chat/types').AssistantExecutionMeta>>({})
  const [streamingAssistantId, setStreamingAssistantId] = useState<string | null>(null)
  const [editContent, setEditContent] = useState<string>('')
  const [shouldFocusInput, setShouldFocusInput] = useState<number>(0)
  const [feedbackState, setFeedbackState] = useState<Record<string, 1 | -1 | undefined>>({})
  // 跨标签页广播 hook：同步流式内容与会话列表变更到其他标签页
  const {
    broadcastStreamStart,
    broadcastStreamChunk,
    broadcastStreamEnd,
    broadcastConversationChange,
    subscribe,
  } = useChatBroadcast()
  // streamingAssistantId 的 ref 镜像，供订阅回调同步读取最新值，
  // 避免回调闭包捕获到过期的 streamingAssistantId 导致防重复失效
  const streamingAssistantIdRef = useRef<string | null>(null)
  useEffect(() => {
    streamingAssistantIdRef.current = streamingAssistantId
  }, [streamingAssistantId])
  // 标记当前流式是否需要广播到其他标签页。
  // 在 handleSend 中设置，在 streamingAssistantId 变化的 useEffect 中读取，
  // 用于判断是否发送 broadcastStreamStart。避免在 options 中注入 assistantMessageId
  // 导致 useChatStream 误判 assistantMessageCreated=true，从而破坏重试与消息创建逻辑。
  const shouldBroadcastCurrentStreamRef = useRef(false)
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
  // 密钥失效提示对话框：收到 llm_api_key_stale 错误码时弹出，引导用户跳转设置页
  const [showApiKeyStaleDialog, setShowApiKeyStaleDialog] = useState<boolean>(false)
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

  // P0: 监听消息数量与最后一条消息内容长度变化，触发自动滚动 hook
  // 流式输出期间 messages.length 不变，但 content 长度持续增长，需要同时监听两者
  const lastMessageContentLength = messages[messages.length - 1]?.content.length ?? 0
  useEffect(() => {
    onContentGrow()
  }, [messages.length, lastMessageContentLength, onContentGrow])

  useEffect(() => {
    messageMetaRef.current = messageMeta
  }, [messageMeta])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      // 组件卸载时取消进行中的流式请求并清理子代理定时器，防止资源泄露
      isMountedRef.current = false
      try {
        chatStream.abortStream()
      } catch (err) {
        // 卸载阶段忽略 abort 错误
        void err
      }
      try {
        subagentSync.cleanupAllSubagentTimers()
      } catch (err) {
        void err
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        flushBuffer()
        // 用户切回标签页时强制滚动到底部，重置未读新内容标记
        setTimeout(scrollToLatest, 50)
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [flushBuffer, scrollToLatest])

  useEffect(() => {
    appLogger.info({
      event: 'page_view',
      module: 'chat_page',
      action: 'mount',
      status: 'success',
      message: 'chat page mounted',
    })
  }, [])

  // 跨标签页广播订阅：接收其他标签页的流式与会话变更事件，应用到当前 store。
  // 防重复关键：若当前标签页正在主动流式该消息（streamingAssistantIdRef 与事件 messageId 一致），
  // 说明当前标签页是发起方，跳过应用远程事件，避免重复追加。
  useEffect(() => {
    const unsubscribe = subscribe((event: ChatBroadcastEvent) => {
      // 防重复：当前标签页正在主动流式该消息时，跳过远程事件
      if (
        streamingAssistantIdRef.current !== null &&
        event.type !== 'conversation_changed' &&
        event.messageId === streamingAssistantIdRef.current
      ) {
        return
      }
      switch (event.type) {
        case 'stream_start':
          useSessionStore.getState().applyRemoteStreamStart(
            event.sessionId,
            event.messageId,
            event.userMessage
          )
          break
        case 'stream_chunk':
          useSessionStore.getState().applyRemoteStreamChunk(
            event.sessionId,
            event.messageId,
            event.content,
            event.reasoning
          )
          break
        case 'stream_end':
          useSessionStore.getState().applyRemoteStreamEnd(
            event.sessionId,
            event.messageId,
            event.finalContent,
            event.finalReasoning
          )
          break
        case 'conversation_changed':
          useSessionStore.getState().applyRemoteConversationChange()
          break
      }
    })
    return unsubscribe
  }, [subscribe])

  // 节流广播流式 chunk：监听当前流式助手消息的 content/reasoning_content 变化，
  // 按 200ms 间隔或 50 字符增量的阈值节流广播，避免高频 chunk 淹没其他标签页。
  const lastChunkBroadcastRef = useRef<{ content: string; time: number }>({
    content: '',
    time: 0,
  })
  useEffect(() => {
    if (!streamingAssistantId) return
    const currentMessage = messages.find((m) => m.id === streamingAssistantId)
    if (!currentMessage || currentMessage.role !== 'assistant') return

    const now = Date.now()
    const contentDelta = currentMessage.content.length - lastChunkBroadcastRef.current.content.length
    // 节流：距上次广播不足 200ms 且内容增量不足 50 字符时跳过
    if (now - lastChunkBroadcastRef.current.time < 200 && contentDelta < 50) {
      return
    }

    // 使用 getState().sessionId 读取最新会话 ID，避免闭包捕获过期值
    const currentSessionId = useSessionStore.getState().sessionId
    if (currentSessionId === 'default') return

    broadcastStreamChunk(
      currentSessionId,
      streamingAssistantId,
      currentMessage.content,
      currentMessage.reasoning_content
    )
    lastChunkBroadcastRef.current = { content: currentMessage.content, time: now }
  }, [streamingAssistantId, messages, broadcastStreamChunk])

  // 流式开始/结束广播：检测 streamingAssistantId 的状态过渡。
  // - null → 非空：流式开始，广播 stream_start（携带最后一条用户消息）
  // - 非空 → null：流式结束，广播 stream_end（携带最终内容）
  // 同时在流式开始时重置节流状态。
  const prevStreamingIdRef = useRef<string | null>(null)
  useEffect(() => {
    const prevId = prevStreamingIdRef.current
    prevStreamingIdRef.current = streamingAssistantId

    if (prevId && !streamingAssistantId) {
      // 从非空变为 null：流式结束，广播最终内容
      const finalMessage = useSessionStore.getState().messages.find((m) => m.id === prevId)
      const currentSessionId = useSessionStore.getState().sessionId
      if (finalMessage && currentSessionId !== 'default') {
        broadcastStreamEnd(
          currentSessionId,
          prevId,
          finalMessage.content,
          finalMessage.reasoning_content
        )
      }
      // 重置节流状态，为下次流式做准备
      lastChunkBroadcastRef.current = { content: '', time: 0 }
      // 重置广播标记
      shouldBroadcastCurrentStreamRef.current = false
    } else if (!prevId && streamingAssistantId) {
      // 从 null 变为非空：流式开始
      // 重置节流状态，确保第一个 chunk 能立即广播
      lastChunkBroadcastRef.current = { content: '', time: 0 }
      // 仅在需要广播时（用户主动发送消息）发送 stream_start
      if (shouldBroadcastCurrentStreamRef.current) {
        const currentSessionId = useSessionStore.getState().sessionId
        if (currentSessionId !== 'default') {
          // 从 store 中读取最后一条用户消息作为广播内容
          const currentMessages = useSessionStore.getState().messages
          const lastUserMessage = [...currentMessages].reverse().find((m) => m.role === 'user')
          if (lastUserMessage) {
            broadcastStreamStart(currentSessionId, streamingAssistantId, lastUserMessage.content)
          }
        }
      }
    }
  }, [streamingAssistantId, broadcastStreamStart, broadcastStreamEnd])

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
  }, [broadcastConversationChange, clearHistoryError, navigate, resetStreamExecutionState, setMessages, setSessionId, upsertConversation])

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

    if (fallbackConversation) {
      navigate(`/chat/${fallbackConversation.session_id}`, { replace: true })
      return
    }

    await createConversationAndNavigate(true)
  }, [broadcastConversationChange, createConversationAndNavigate, navigate, removeConversation, resetStreamExecutionState, setMessages])

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
    onApiKeyStale: () => setShowApiKeyStaleDialog(true),
  })

  // 标记当前流式是否需要广播到其他标签页（声明于 hook 顶部，供 handleSend 与 useEffect 共享）
  const handleSend = useCallback(async (userMessage?: string, uploadedAttachments?: FileAttachment[], options?: import('./hooks/useChatStream').SendMessageOptions) => {
    const messageText = (userMessage || '').trim()
    // 仅在用户发送实际消息（非隐藏消息、非续流）时广播流式开始
    const shouldBroadcastStart =
      messageText.length > 0 && !options?.hiddenUserMessage && !options?.continuation
    shouldBroadcastCurrentStreamRef.current = shouldBroadcastStart

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
        // 流式结束后广播会话变更（last_message_at 等已更新）
        broadcastConversationChange()
      }
    )
  }, [chatStream, ensureConversationSession, flushConversationCache, sessionId, loadConversationList, broadcastConversationChange])

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
    if (useToolCallStore.getState().activeToolCalls.length > 0) {
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
    // 重新生成会话涉及会话增删，广播变更到其他标签页
    broadcastConversationChange()

    void handleSendRef.current?.(lastUserMsg.content, [])
  }, [broadcastConversationChange, sessionId, removeConversation, upsertConversation, setSessionId, setMessages, setStreamingAssistantId, resetStreamExecutionState, resetTaskPanelState, navigate])

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
    // 重命名后广播变更到其他标签页
    broadcastConversationChange()
  }, [broadcastConversationChange, upsertConversation])

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
    // 删除会话后广播变更到其他标签页
    broadcastConversationChange()
  }, [broadcastConversationChange, conversations, createConversationAndNavigate, includeDeleted, navigate, removeConversation, sessionId, upsertConversation, loadConversationList, pendingDeleteSessionId])

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
    // 恢复会话后广播变更到其他标签页
    broadcastConversationChange()
  }, [broadcastConversationChange, navigate, sessionId, upsertConversation, loadConversationList])

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
    // 批量删除会话后广播变更到其他标签页
    broadcastConversationChange()
  }, [broadcastConversationChange, conversations, createConversationAndNavigate, includeDeleted, loadConversationList, navigate, removeConversation, sessionId, upsertConversation, t])

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
        <ErrorBoundary name="ConversationSidebar">
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
        </ErrorBoundary>

        <div className={styles['chat-main']}>
          <ErrorBoundary name="ChatMain">
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
              scrollContainerRef={scrollContainerRef}
              showJumpToLatest={hasNewContent}
              onJumpToLatest={scrollToLatest}
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
          </ErrorBoundary>
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
      {/* 密钥失效提示对话框：点击「跳转设置」导航到 /settings 路由 */}
      {showApiKeyStaleDialog && (
        <ConfirmDialog
          isOpen={showApiKeyStaleDialog}
          title="API Key 已失效"
          message="该供应商 API Key 已失效，请在设置页重新录入"
          type="warning"
          confirmText="跳转设置"
          cancelText="稍后处理"
          onConfirm={() => {
            setShowApiKeyStaleDialog(false)
            navigate('/settings')
          }}
          onCancel={() => setShowApiKeyStaleDialog(false)}
        />
      )}
    </div>
  )
}

export default ChatPage
