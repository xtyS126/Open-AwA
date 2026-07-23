import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PanelLeft } from 'lucide-react'
import { chatAPI, diaryAPI } from '@/shared/api/api'
import { useConversationHistory } from '@/features/chat/hooks/useConversationHistory'
import { useStreamExecutionState } from '@/features/chat/hooks/useStreamExecutionState'
import { useChatBroadcastEffects } from '@/features/chat/hooks/useChatBroadcastEffects'
import { useChatConversationActions } from '@/features/chat/hooks/useChatConversationActions'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useModelStore } from '@/features/chat/store/modelStore'
import { useToolCallStore } from '@/features/chat/store/toolCallStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'
import { shallow } from 'zustand/shallow'
import { useI18nStore } from '@/i18n'
import { appLogger } from '@/shared/utils/logger'
import { useToast } from '@/shared/components/Toast'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { useChatStream } from './hooks/useChatStream'
import { useSubagentSync } from './hooks/useSubagentSync'
import { useMessageCache } from './hooks/useMessageCache'
import { usePermissionRequest } from './hooks/usePermissionRequest'
import { useChatAutoScroll } from './hooks/useChatAutoScroll'
import { useChatBroadcast } from './hooks/useChatBroadcast'
import ConversationSidebar from './components/ConversationSidebar'
import { MessageList } from './components/MessageList'
import { ChatInput } from './components/ChatInput'
import { PermissionRequestNotification } from './components/PermissionRequestNotification'
import type { FileAttachment } from './components/ChatInput'
// P1: TaskPanel/TodoPanel 按需懒加载，减少聊天页首屏 JS
const TodoPanel = React.lazy(() => import('./components/TodoPanel').then(m => ({ default: m.TodoPanel })))
const AskUserCard = React.lazy(() => import('./components/AskUserCard').then(m => ({ default: m.AskUserCard })))
import type { TodoItem } from './components/TodoPanel'
import type { AskUserRequest } from './types'
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
  // ask_user 挂起的问题请求：同一时刻最多一个（后端 is_concurrency_safe=False）
  const [askUserRequest, setAskUserRequest] = useState<AskUserRequest | null>(null)
  const [aborting, setAborting] = useState<boolean>(false)
  const [showAbortConfirm, setShowAbortConfirm] = useState<boolean>(false)
  // 密钥失效提示对话框：收到 llm_api_key_stale 错误码时弹出，引导用户跳转设置页
  const [showApiKeyStaleDialog, setShowApiKeyStaleDialog] = useState<boolean>(false)
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
    // 初始化为 0，首次 chunk 到达时会被立即更新
    // 避免在 useRef 初始化中调用 Date.now()（impure function）违反纯渲染规则
    lastUpdateTime: 0
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

  // 组件卸载清理逻辑已移至 chatStream/subagentSync 声明之后，避免变量在声明前被访问

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

  // 使用 ref 守卫避免 React StrictMode 开发模式双重挂载时重复触发 mount 日志
  const mountLoggedRef = useRef(false)
  useEffect(() => {
    if (mountLoggedRef.current) return
    mountLoggedRef.current = true
    appLogger.info({
      event: 'page_view',
      module: 'chat_page',
      action: 'mount',
      status: 'success',
      message: 'chat page mounted',
    })
  }, [])

  // 跨标签页广播副作用：订阅远程事件 + 节流广播 chunk + 流式开始/结束过渡广播。
  // 详细逻辑见 useChatBroadcastEffects，主组件仅需传入流式状态与广播方法。
  useChatBroadcastEffects({
    streamingAssistantId,
    streamingAssistantIdRef,
    messages,
    subscribe,
    broadcastStreamStart,
    broadcastStreamChunk,
    broadcastStreamEnd,
    shouldBroadcastCurrentStreamRef,
  })

  // handleSend 的 ref 镜像：供 useChatConversationActions 中的 handleRegenerate 调用。
  // 必须在 useChatConversationActions 之前声明，避免变量在声明前被访问。
  // 真正的 handleSend 在 chatStream 初始化后定义，并通过 useEffect 同步到 ref。
  const handleSendRef = useRef<((message?: string, attachments?: FileAttachment[], options?: import('./hooks/useChatStream').SendMessageOptions) => Promise<void>) | undefined>(undefined)

  // 会话生命周期与 CRUD 动作：创建/恢复/重命名/删除/批量删除/重新生成等。
  // 详细逻辑见 useChatConversationActions，主组件仅需传入 store 动作与缓存方法。
  const {
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
    pendingDeleteSessionId,
  } = useChatConversationActions({
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
    resetTaskPanelState: () => undefined,
    setMessageMeta,
    setStreamingAssistantId,
    setFeedbackState,
    broadcastConversationChange,
    getLocalMessagesForRestore,
    mergeServerHistoryWithCached,
    flushConversationCache,
    getActiveConversationId,
    buildMessageMetaFromMessages,
    t,
    handleSendRef: handleSendRef as React.MutableRefObject<((message?: string | undefined, attachments?: unknown[] | undefined) => Promise<void>) | undefined>,
  })

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

  const subagentSync = useSubagentSync({
    updateAssistantMeta,
    updateAssistantSegments,
    addToast,
    isMountedRef,
    messageMetaRef,
    handleSendRef: handleSendRef as React.MutableRefObject<((message?: string | undefined, attachments?: unknown[] | undefined, options?: import('@/features/chat/hooks/useSubagentSync').SendOptions | undefined) => Promise<void>) | undefined>,
  })

  // ---- SSE 断连重连恢复：sessionStorage 持久化活跃任务 ----
  // 用户切换页面时 ChatPage 卸载，SSE 连接断开但后端任务继续运行。
  // 这里把 task_id + assistantMessageId + lastSeq 持久化到 sessionStorage，
  // 用户切回页面时通过 resubscribeToTask 恢复流式输出。
  const ACTIVE_TASK_STORAGE_KEY = 'chat:active-task'
  const activeTaskLastSeqRef = useRef<number>(-1)

  const persistActiveTask = useCallback(
    (taskId: string, assistantMessageId: string, taskSessionId: string) => {
      try {
        activeTaskLastSeqRef.current = -1
        sessionStorage.setItem(
          ACTIVE_TASK_STORAGE_KEY,
          JSON.stringify({
            taskId,
            assistantMessageId,
            sessionId: taskSessionId,
            lastSeq: -1,
            createdAt: Date.now(),
          })
        )
      } catch (err) {
        // sessionStorage 写入失败（如隐私模式）不阻塞主流程
        appLogger.warning({
          event: 'chat_task_persist_failed',
          module: 'chat_page',
          message: '持久化活跃任务到 sessionStorage 失败',
          extra: { error: err instanceof Error ? err.message : String(err) },
        })
      }
    },
    []
  )

  const updateActiveTaskSeq = useCallback((taskId: string, seq: number) => {
    activeTaskLastSeqRef.current = seq
    try {
      const raw = sessionStorage.getItem(ACTIVE_TASK_STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as { taskId?: string; lastSeq?: number }
      if (parsed.taskId !== taskId) return
      parsed.lastSeq = seq
      sessionStorage.setItem(ACTIVE_TASK_STORAGE_KEY, JSON.stringify(parsed))
    } catch {
      // 序列化失败时静默，不阻塞流式输出
    }
  }, [])

  const clearActiveTask = useCallback((taskId?: string) => {
    try {
      if (taskId) {
        const raw = sessionStorage.getItem(ACTIVE_TASK_STORAGE_KEY)
        if (raw) {
          const parsed = JSON.parse(raw) as { taskId?: string }
          if (parsed.taskId !== taskId) return
        }
      }
      sessionStorage.removeItem(ACTIVE_TASK_STORAGE_KEY)
      activeTaskLastSeqRef.current = -1
    } catch {
      // 清理失败静默
    }
  }, [])

  const loadActiveTask = useCallback(() => {
    try {
      const raw = sessionStorage.getItem(ACTIVE_TASK_STORAGE_KEY)
      if (!raw) return null
      const parsed = JSON.parse(raw) as {
        taskId: string
        assistantMessageId: string
        sessionId: string
        lastSeq: number
        createdAt: number
      }
      return parsed
    } catch {
      return null
    }
  }, [])

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
    setAskUserRequest,
    setStreamingAssistantId,
    setLoading,
    messageMeta,
    setMessageMeta,
    onApiKeyStale: () => setShowApiKeyStaleDialog(true),
    onTaskStarted: persistActiveTask,
    onTaskSeq: updateActiveTaskSeq,
    onTaskFinished: clearActiveTask,
  })

  // 组件卸载时取消进行中的流式请求并清理子代理定时器，防止资源泄露。
  // 注意：abortStream 仅断开 SSE 连接（AbortController.abort），
  // 后端任务在 ChatTaskManager 中独立运行，不会被取消。
  // 用户切回页面时通过 resubscribeToTask 恢复流式输出。
  useEffect(() => {
    isMountedRef.current = true
    return () => {
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

  // 页面切换回来后恢复进行中的流式任务。
  // 检查 sessionStorage 中是否有活跃任务，若有且 sessionId 匹配则重连订阅。
  // 仅在组件首次挂载时执行一次（通过 ref 守卫避免 StrictMode 双调用重复重连）。
  const resubscribeAttemptedRef = useRef(false)
  useEffect(() => {
    if (resubscribeAttemptedRef.current) return
    resubscribeAttemptedRef.current = true
    const activeTask = loadActiveTask()
    if (!activeTask) return
    // 仅当任务的目标会话与当前会话一致时才重连；
    // 会话不匹配说明用户已切换到其他对话，不在此恢复（任务仍在后端运行）
    if (!sessionId || sessionId === 'default') {
      // 当前会话未确定时也尝试恢复（覆盖从 default 会话发起的任务）
      void sessionId
    } else if (activeTask.sessionId !== sessionId) {
      // 会话不匹配：清除过期记录，不重连
      clearActiveTask(activeTask.taskId)
      return
    }
    // 异步检查任务是否仍在运行或已完成，然后重连
    void (async () => {
      try {
        const statusResp = await chatAPI.getTaskStatus(activeTask.taskId)
        const status = statusResp.data
        if (!status) {
          clearActiveTask(activeTask.taskId)
          return
        }
        // 任务已结束且无新事件可回放：清除记录，不重连
        const lastSeq = activeTask.lastSeq ?? -1
        if (
          (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') &&
          status.next_seq <= lastSeq + 1
        ) {
          clearActiveTask(activeTask.taskId)
          return
        }
        // 任务仍在运行或有未消费事件：重连订阅
        activeTaskLastSeqRef.current = lastSeq
        await chatStream.resubscribeToTask(
          activeTask.taskId,
          activeTask.assistantMessageId,
          lastSeq
        )
      } catch (err) {
        appLogger.warning({
          event: 'chat_resubscribe_mount_failed',
          module: 'chat_page',
          message: '恢复流式任务失败',
          extra: {
            task_id: activeTask.taskId,
            error: err instanceof Error ? err.message : String(err),
          },
        })
        clearActiveTask(activeTask.taskId)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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

  // 在 useEffect 中更新 ref，避免在 render 阶段修改 ref 违反 React 纯渲染规则
  useEffect(() => {
    handleSendRef.current = handleSend
  }, [handleSend])

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
      // 用户主动 abort：取消后端任务（ChatTaskManager 取消 background_task）
      // 避免 SSE 断开后后端任务继续运行浪费资源
      const activeTaskId = chatStream.getActiveTaskId()
      if (activeTaskId) {
        chatAPI.cancelTask(activeTaskId).catch(() => { /* 静默，任务可能已结束 */ })
        clearActiveTask(activeTaskId)
      }
      setStreamingAssistantId(null)
      resetActiveToolCalls()
    } finally {
      setAborting(false)
      setShowAbortConfirm(false)
    }
  }, [sessionId, resetActiveToolCalls, chatStream, clearActiveTask])

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

  /*
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
    } catch {
      appLogger.warning({
        event: 'stop_agent_failed',
        module: 'chat_page',
        message: 'failed to stop agent',
        extra: { agentId },
      })
    }
  }, [subagentSync, streamingAssistantId, updateAssistantMeta, updateAssistantSegments, t])
  */

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

            <React.Suspense fallback={(
              <div style={{ padding: 'var(--space-2) var(--space-3)' }}>
                <Skeleton variant="rectangular" height="var(--space-6)" width="40%" />
              </div>
            )}>
              <TodoPanel
                items={todoItems}
                summary={todoSummary}
              />
            </React.Suspense>

            <React.Suspense fallback={(
              <div style={{ padding: 'var(--space-2) var(--space-3)' }}>
                <Skeleton variant="rectangular" height="var(--space-6)" width="40%" />
              </div>
            )}>
              <AskUserCard
                request={askUserRequest}
                onResolved={() => setAskUserRequest(null)}
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
