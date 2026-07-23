import { useRef, useCallback } from 'react'
import { chatAPI } from '@/shared/api/api'
import type { ChatContinuationPayload } from '@/shared/api/api'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useToolCallStore } from '@/features/chat/store/toolCallStore'
import { handleStreamChunkEvent } from '@/features/chat/utils/handleStreamChunkEvent'
import { dispatchStructuredStreamEvent } from '@/features/chat/utils/dispatchStructuredStreamEvent'
import { applyDirectAssistantResponse } from '@/features/chat/utils/applyDirectAssistantResponse'
import {
  appendAssistantChunk,
} from '@/features/chat/utils/assistantSegments'
import { appLogger } from '@/shared/utils/logger'
import { dispatchBillingUsageUpdated } from '@/shared/events/billingEvents'
import { asRecord } from '@/shared/types/api'
import type { AssistantExecutionMeta, AssistantMessageSegment, AskUserRequest } from '@/features/chat/types'
import type { FileAttachment } from '@/features/chat/components/ChatInput'
import type { TodoItem } from '@/features/chat/components/TodoPanel'

const MAX_STREAM_RETRY_COUNT = 1

/** 后端返回的密钥失效错误码，需引导用户跳转设置页重新录入 */
const LLM_API_KEY_STALE_CODE = 'llm_api_key_stale'

/** 密钥失效时展示给用户的提示文案 */
const LLM_API_KEY_STALE_USER_MESSAGE = '[!] 该供应商 API Key 已失效，请在设置页重新录入'

/**
 * 从 Error 对象中提取流式错误携带的 code 字段。
 * api.ts 的 createStreamError 会将后端 error.code 挂载到 Error.code 属性上，
 * 这里读取该属性；不存在或非字符串时返回 undefined。
 */
function extractStreamErrorCode(error: Error): string | undefined {
  const code = (error as { code?: unknown }).code
  return typeof code === 'string' ? code : undefined
}

function sanitizeDisplayedError(message: string): string {
  return String(message || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

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

/** 错误类型分类 */
type ErrorCategory = 'auth' | 'timeout' | 'server' | 'network' | 'unknown'

/** 分类错误类型 */
function classifyError(error: Error): ErrorCategory {
  const message = String(error.message || '').toLowerCase()
  const statusMatch = message.match(/(\d{3})/)
  const statusCode = statusMatch ? parseInt(statusMatch[1], 10) : 0

  // 认证错误：401/403 或包含 API Key 相关关键词
  if (
    statusCode === 401 ||
    statusCode === 403 ||
    message.includes('api key') ||
    message.includes('api_key') ||
    message.includes('apikey') ||
    message.includes('authentication') ||
    message.includes('unauthorized') ||
    message.includes('forbidden') ||
    message.includes('未检测到任何已配置') ||
    message.includes('未配置')
  ) {
    return 'auth'
  }

  // 超时错误
  if (
    message.includes('timeout') ||
    message.includes('超时') ||
    message.includes('timed out')
  ) {
    return 'timeout'
  }

  // 服务器错误
  if (statusCode >= 500) {
    return 'server'
  }

  // 网络错误
  if (
    message.includes('failed to fetch') ||
    message.includes('network') ||
    message.includes('networkerror') ||
    message.includes('load failed') ||
    message.includes('econnreset') ||
    message.includes('econnrefused') ||
    message.includes('abort')
  ) {
    return 'network'
  }

  return 'unknown'
}

/** 根据错误类型生成用户友好的中文提示 */
function getUserFriendlyErrorMessage(error: Error): string {
  const category = classifyError(error)
  const rawMessage = sanitizeDisplayedError(error.message)

  switch (category) {
    case 'auth':
      return '[!] 模型服务未配置或认证失败。请前往设置页面检查 API Key 配置。'
    case 'timeout':
      return '[!] 连接超时，请检查网络连接后重试。'
    case 'server':
      return '[!] 服务器内部错误，请稍后重试。'
    case 'network':
      return '[!] 网络连接失败，请检查网络后重试。'
    default:
      return `[!] 消息发送失败：${rawMessage}`
  }
}

function parseSelectedModel(value: string): { provider?: string; model?: string } {
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

function getConfiguredMaxToolCallRounds(): number {
  const appSettings = JSON.parse(
    typeof window !== 'undefined' ? localStorage.getItem('app_settings') || 'null' : 'null'
  ) as { maxToolCallRounds?: number } | null
  const rawValue = appSettings?.maxToolCallRounds
  if (typeof rawValue !== 'number' || Number.isNaN(rawValue)) {
    return 12
  }
  return Math.max(1, Math.min(50000, Math.trunc(rawValue)))
}

export interface SendMessageOptions {
  assistantMessageId?: string
  hiddenUserMessage?: boolean
  continuation?: ChatContinuationPayload
}

export interface UseChatStreamParams {
  /** 当前会话 ID */
  sessionId: string
  /** 输出模式 */
  outputMode: 'stream' | 'direct'
  /** 当前选中的模型 */
  selectedModel: string
  /** 思考模式是否启用 */
  thinkingEnabled: boolean
  /** 思考深度 */
  thinkingDepth: number
  /** 组件挂载状态引用 */
  isMountedRef: React.MutableRefObject<boolean>
  /** 更新消息执行元数据 */
  updateAssistantMeta: (messageId: string, updater: (current: AssistantExecutionMeta) => AssistantExecutionMeta) => void
  /** 更新消息分段 */
  updateAssistantSegments: (messageId: string, updater: (current: AssistantMessageSegment[] | undefined) => AssistantMessageSegment[]) => void
  /** 最终化消息分段 */
  finalizeAssistantMessageSegments: (messageId: string) => void
  /** 追加助手消息文本 */
  appendAssistantMessageText: (assistantMessageId: string, content: string, reasoningContent?: string) => void
  /** 刷新缓冲区 */
  flushBuffer: (assistantMessageId?: string) => void
  /** 显示提示信息 */
  addToast: (message: string, type: 'success' | 'warning' | 'error' | 'info') => void
  /** 流式执行状态管理 */
  streamExecution: {
    beginStreamExecution: (outputMode: 'stream' | 'direct') => void
    markStreamRetrying: (attempt: number) => void
    markStreamStreaming: () => void
    markStreamFailed: (message: string) => void
    clearStreamStageMessage: () => void
    setIdleStreamState: () => void
    setStreamStageMessage: (message: string | null) => void
  }
  /** 子代理同步 */
  subagentSync: {
    clearSubagentAggregationTimer: (assistantMessageId: string) => void
    scheduleSubagentTimeout: (assistantMessageId: string, agentId: string, agentType?: string) => void
    syncSubagentRuntime: (assistantMessageId: string, agentId: string, agentType?: string) => void
    clearSubagentTimeout: (agentId: string) => void
    clearSubagentSyncTimer: (agentId: string) => void
    scheduleSubagentAggregation: (assistantMessageId: string) => void
  }
  /** 设置 Todo 列表 */
  setTodoItems: React.Dispatch<React.SetStateAction<TodoItem[]>>
  /** 设置 Todo 摘要 */
  setTodoSummary: React.Dispatch<React.SetStateAction<string>>
  /** 设置挂起的 ask_user 问题请求（null 清空） */
  setAskUserRequest: React.Dispatch<React.SetStateAction<AskUserRequest | null>>
  /** 设置流式助手消息 ID */
  setStreamingAssistantId: React.Dispatch<React.SetStateAction<string | null>>
  /** 设置加载状态 */
  setLoading: (loading: boolean) => void
  /** 获取当前消息元数据映射 */
  messageMeta: Record<string, AssistantExecutionMeta>
  /** 更新消息元数据映射（direct 模式需要） */
  setMessageMeta: React.Dispatch<React.SetStateAction<Record<string, AssistantExecutionMeta>>>
  /**
   * 当后端返回 llm_api_key_stale 错误码时触发，调用方应弹出引导用户
   * 跳转设置页重新录入 API Key 的对话框。
   */
  onApiKeyStale?: () => void
  /**
   * 后端为本次流式任务分配 task_id 后回调（仅 stream 模式触发）。
   * 调用方通常在此持久化 task_id + assistantMessageId + sessionId 到 sessionStorage，
   * 以便页面切换后通过 resubscribeToTask 恢复。
   */
  onTaskStarted?: (taskId: string, assistantMessageId: string, sessionId: string) => void
  /**
   * 每收到一个带 _seq 的事件时回调，调用方据此更新 sessionStorage 中的 lastSeq，
   * 用于断连重连时定位 from_seq。
   */
  onTaskSeq?: (taskId: string, seq: number) => void
  /**
   * 任务结束（正常完成、失败、取消）后回调，调用方应清除 sessionStorage 中的任务记录。
   */
  onTaskFinished?: (taskId: string) => void
}

export interface UseChatStreamReturn {
  /** 发送消息（流式或直接） */
  handleSendMessage: (
    userMessage: string | undefined,
    uploadedAttachments: FileAttachment[] | undefined,
    options: SendMessageOptions | undefined,
    ensureConversationSession: () => Promise<string>,
    onFinally: () => void
  ) => Promise<void>
  /** 中止当前流式请求（仅断开 SSE 连接，不取消后端任务，用于页面切换） */
  abortStream: () => void
  /**
   * 重连订阅已存在的后端任务事件流。
   * 用于页面切换回来后恢复被中断的流式输出。
   *
   * 调用前需由调用方校验 sessionId 匹配，本函数仅依据 task_id 重连后端事件流。
   *
   * @param taskId 后端任务 ID
   * @param assistantMessageId 前端已存在的助手消息 ID（用于继续追加内容）
   * @param fromSeq 起始事件 seq（含），默认 -1 表示从头回放
   */
  resubscribeToTask: (
    taskId: string,
    assistantMessageId: string,
    fromSeq?: number
  ) => Promise<void>
  /** 获取当前活跃任务 ID（供 ChatPage 在用户主动 abort 时取消后端任务） */
  getActiveTaskId: () => string | null
}

/**
 * 管理聊天流式传输与直接输出的核心逻辑。
 *
 * 包含 SSE 连接建立、chunk 解析、错误处理、重试逻辑、
 * 流式状态管理以及消息追加和最终化。
 */
export function useChatStream({
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
  streamExecution,
  subagentSync,
  setTodoItems,
  setTodoSummary,
  setAskUserRequest,
  setStreamingAssistantId,
  setLoading,
  messageMeta,
  setMessageMeta,
  onApiKeyStale,
  onTaskStarted,
  onTaskSeq,
  onTaskFinished,
}: UseChatStreamParams): UseChatStreamReturn {
  const activeRequestIdRef = useRef(0)
  const activeAbortControllerRef = useRef<AbortController | null>(null)
  const bufferRef = useRef({
    content: '',
    reasoning: '',
    // 初始化为 0，首次 chunk 到达时会被 handleStreamChunkEvent 立即更新
    // 避免在 useRef 初始化中调用 Date.now()（impure function）违反纯渲染规则
    lastUpdateTime: 0,
  })
  // 当前活跃的后端任务 ID（用于 ChatPage 用户主动 abort 时取消后端任务）
  const activeTaskIdRef = useRef<string | null>(null)
  // 当前活跃任务已处理到的最大 seq（用于断连重连时定位 from_seq）
  const activeTaskLastSeqRef = useRef<number>(-1)

  const addMessage = useSessionStore((s) => s.addMessage)
  const addActiveToolCall = useToolCallStore((s) => s.addActiveToolCall)
  const removeActiveToolCall = useToolCallStore((s) => s.removeActiveToolCall)
  const resetActiveToolCalls = useToolCallStore((s) => s.resetActiveToolCalls)
  const upsertConversation = useSessionStore((s) => s.upsertConversation)

  const abortStream = useCallback(() => {
    activeAbortControllerRef.current?.abort()
  }, [])

  const getActiveTaskId = useCallback(() => activeTaskIdRef.current, [])

  /**
   * 从事件中提取 _seq 并更新 activeTaskLastSeqRef + 触发 onTaskSeq 回调。
   * 返回 true 表示事件携带了有效 _seq。
   */
  const trackEventSeq = useCallback(
    (event: { _seq?: number } | undefined, taskId: string): boolean => {
      const seq = typeof event?._seq === 'number' ? event._seq : undefined
      if (seq === undefined) {
        return false
      }
      if (seq > activeTaskLastSeqRef.current) {
        activeTaskLastSeqRef.current = seq
        onTaskSeq?.(taskId, seq)
      }
      return true
    },
    [onTaskSeq]
  )

  const handleSendMessage = useCallback(
    async (
      userMessage: string | undefined,
      uploadedAttachments: FileAttachment[] | undefined,
      options: SendMessageOptions | undefined,
      ensureConversationSession: () => Promise<string>,
      onFinally: () => void
    ) => {
      const messageText = (userMessage || '').trim()
      const safeAttachments = uploadedAttachments || []
      if (!messageText && safeAttachments.length === 0 && !options?.continuation) return
      if (useSessionStore.getState().isLoading && !options?.continuation) return

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
            updateAssistantSegments(assistantMessageId, (segments) =>
              appendAssistantChunk(segments, {
                content,
                reasoningContent: reasoning,
              })
            )
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
              type: att.mimeType.startsWith('image/')
                ? 'image'
                : att.mimeType.startsWith('audio/')
                  ? 'audio'
                  : att.mimeType.startsWith('video/')
                    ? 'video'
                    : 'image',
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

      if (!fullMessage && chatAttachments.length === 0) {
        setLoading(false)
        return
      }

      const currentConversation = useSessionStore.getState().conversations.find((item) => item.session_id === targetSessionId)
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
        extra: {
          session_id: targetSessionId,
          input_length: fullMessage.length,
          mode: outputMode,
          attachments: safeAttachments.length,
        },
      })
      if (!hiddenUserMessage) {
        addMessage('user', fullMessage, undefined, userMessageId)
      }
      setLoading(true)
      setStreamingAssistantId(assistantMessageId)
      streamExecution.beginStreamExecution(outputMode)

      // 生成 task_id：前端先生成，传给后端，便于页面切换后通过 task_id 重连恢复
      // 仅 stream 模式需要（direct 模式无 SSE，无需重连）
      // 声明在 try 外部以便 finally 块访问（任务结束时清理追踪状态）
      const streamTaskId = outputMode === 'stream' ? crypto.randomUUID() : undefined
      if (streamTaskId) {
        activeTaskIdRef.current = streamTaskId
        activeTaskLastSeqRef.current = -1
        // 通知 ChatPage 持久化 task_id + assistantMessageId + sessionId
        onTaskStarted?.(streamTaskId, assistantMessageId, targetSessionId)
      }

      try {
        const { provider, model } = parseSelectedModel(selectedModel)
        const executionOptions = {
          ...(thinkingEnabled ? { thinking_enabled: true, thinking_depth: thinkingDepth } : {}),
          max_tool_call_rounds: getConfiguredMaxToolCallRounds(),
          ...(options?.continuation ? { continuation: options.continuation } : {}),
          ...(streamTaskId ? { task_id: streamTaskId } : {}),
        }

        if (outputMode === 'stream') {
          bufferRef.current = { content: '', reasoning: '', lastUpdateTime: Date.now() }

          for (let attempt = 0; attempt <= MAX_STREAM_RETRY_COUNT; attempt += 1) {
            let runtimeError: Error | null = null
            if (attempt > 0) {
              streamExecution.markStreamRetrying(attempt)
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

                  // 追踪事件 seq（用于断连重连时定位 from_seq）
                  if (streamTaskId) {
                    trackEventSeq(event, streamTaskId)
                  }

                  streamExecution.markStreamStreaming()

                  if (event?.type === 'status') {
                    const nextStageMessage =
                      typeof event.message === 'string' ? event.message.trim() : ''
                    streamExecution.setStreamStageMessage(nextStageMessage || null)
                    return
                  }

                  if (event?.type === 'chunk') {
                    assistantMessageCreated = handleStreamChunkEvent({
                      assistantMessageId,
                      event,
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
                  if (event?.type === 'tool') {
                    const toolData = event.tool
                    const toolId = String(toolData?.id || '')
                    const toolStatus = String(toolData?.status || '')
                    if (toolStatus === 'running') {
                      addActiveToolCall(toolId)
                    } else if (toolStatus === 'completed' || toolStatus === 'error') {
                      removeActiveToolCall(toolId)
                    }
                  }
                  dispatchStructuredStreamEvent(event, {
                    assistantMessageId,
                    messageMeta,
                    addToast,
                    updateAssistantMeta,
                    updateAssistantSegments,
                    clearSubagentAggregationTimer: subagentSync.clearSubagentAggregationTimer,
                    scheduleSubagentTimeout: subagentSync.scheduleSubagentTimeout,
                    syncSubagentRuntime: subagentSync.syncSubagentRuntime,
                    clearSubagentTimeout: subagentSync.clearSubagentTimeout,
                    clearSubagentSyncTimer: subagentSync.clearSubagentSyncTimer,
                    scheduleSubagentAggregation: subagentSync.scheduleSubagentAggregation,
                    setTodoItems,
                    setTodoSummary,
                    setAskUserRequest,
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
              const hasPartialAssistantOutput =
                assistantMessageCreated ||
                Boolean(bufferRef.current.content || bufferRef.current.reasoning)
              const canRetry =
                attempt < MAX_STREAM_RETRY_COUNT &&
                !hasPartialAssistantOutput &&
                shouldRetryStreamError(normalizedError)

              if (canRetry) {
                streamExecution.markStreamRetrying(attempt + 1)
                continue
              }

              const friendlyErrorMessage = getUserFriendlyErrorMessage(normalizedError)
              streamErrorHandled = true
              flushBuffer(assistantMessageId)
              streamExecution.markStreamFailed(sanitizeDisplayedError(friendlyErrorMessage))
              appLogger.error({
                event: 'chat_stream_error',
                module: 'chat_page',
                action: 'receive_stream',
                status: 'failure',
                message: 'chat stream error',
                extra: {
                  error_category: classifyError(normalizedError),
                  error: normalizedError.message,
                  retry_count: attempt,
                },
              })
              // 密钥失效错误：使用专用提示文案并通知上层弹出跳转设置对话框
              const streamErrorCode = extractStreamErrorCode(normalizedError)
              const displayedMessage = streamErrorCode === LLM_API_KEY_STALE_CODE
                ? LLM_API_KEY_STALE_USER_MESSAGE
                : friendlyErrorMessage
              if (streamErrorCode === LLM_API_KEY_STALE_CODE) {
                onApiKeyStale?.()
              }
              if (!assistantMessageCreated) {
                addMessage('assistant', displayedMessage, undefined, assistantMessageId, true)
                assistantMessageCreated = true
                updateAssistantSegments(assistantMessageId, (segments) =>
                  appendAssistantChunk(segments, {
                    content: displayedMessage,
                  })
                )
              } else {
                const errorContent = `\n\n${displayedMessage}`
                appendAssistantMessageText(assistantMessageId, errorContent)
                updateAssistantSegments(assistantMessageId, (segments) =>
                  appendAssistantChunk(segments, {
                    content: errorContent,
                  })
                )
              }
              finalizeAssistantMessageSegments(assistantMessageId)
              throw normalizedError
            }
          }
          flushBuffer(assistantMessageId)
          finalizeAssistantMessageSegments(assistantMessageId)
          streamExecution.clearStreamStageMessage()
          streamExecution.setIdleStreamState()

          if (
            !isMountedRef.current ||
            activeRequestIdRef.current !== requestId ||
            streamErrorHandled
          ) {
            return
          }
        } else {
          const response = await chatAPI.sendMessage(
            fullMessage,
            targetSessionId,
            provider,
            model,
            'direct',
            { signal: abortController.signal },
            executionOptions,
            chatAttachments.length > 0 ? chatAttachments : undefined
          )
          if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
            return
          }
          // 密钥失效错误：跳过默认渲染流程，直接展示专用提示并通知上层弹出对话框
          const directErrorCode = response.data?.error?.code
          if (directErrorCode === LLM_API_KEY_STALE_CODE) {
            streamErrorHandled = true
            onApiKeyStale?.()
            addMessage('assistant', LLM_API_KEY_STALE_USER_MESSAGE, undefined, assistantMessageId, true)
            updateAssistantSegments(assistantMessageId, (segments) =>
              appendAssistantChunk(segments, {
                content: LLM_API_KEY_STALE_USER_MESSAGE,
              })
            )
            finalizeAssistantMessageSegments(assistantMessageId)
            streamExecution.clearStreamStageMessage()
            streamExecution.setIdleStreamState()
          } else {
            applyDirectAssistantResponse({
              assistantMessageId,
              responseData: asRecord(response.data),
              addMessage: (role, content, reasoningContent, messageId) => {
                addMessage(role, content, reasoningContent, messageId)
              },
              updateMessage: useSessionStore.getState().updateMessage,
              setMessageMeta: (updater) => {
                setMessageMeta(updater)
              },
              sanitizeDisplayedError,
              dispatchUsageUpdated: ({ callId, provider, model }) => {
                dispatchBillingUsageUpdated({ callId, provider, model })
              },
            })
          }
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          streamExecution.clearStreamStageMessage()
          streamExecution.setIdleStreamState()
          return
        }
        const normalizedError = error instanceof Error ? error : new Error(String(error))
        appLogger.error({
          event: 'chat_send',
          module: 'chat_page',
          action: 'send_message',
          status: 'failure',
          message: 'chat send failed',
          extra: { error: normalizedError.message },
        })
        if (
          isMountedRef.current &&
          activeRequestIdRef.current === requestId &&
          !streamErrorHandled
        ) {
          const friendlyErrorMessage = getUserFriendlyErrorMessage(normalizedError)
          if (!assistantMessageCreated) {
            addMessage('assistant', friendlyErrorMessage, undefined, assistantMessageId, true)
            assistantMessageCreated = true
            updateAssistantSegments(assistantMessageId, (segments) =>
              appendAssistantChunk(segments, {
                content: friendlyErrorMessage,
              })
            )
          } else {
            const errorContent = `\n\n${friendlyErrorMessage}`
            appendAssistantMessageText(assistantMessageId, errorContent)
            updateAssistantSegments(assistantMessageId, (segments) =>
              appendAssistantChunk(segments, {
                content: errorContent,
              })
            )
          }
        }
      } finally {
        resetActiveToolCalls()
        if (targetSessionId && targetSessionId !== 'default') {
          // 由调用方在 onFinally 中触发 loadConversationList
        }
        if (isMountedRef.current && activeRequestIdRef.current === requestId) {
          setLoading(false)
          setStreamingAssistantId(null)
          streamExecution.clearStreamStageMessage()
          if (!streamErrorHandled) {
            streamExecution.setIdleStreamState()
          }
        }
        // 任务结束（无论成功/失败/取消）：通知 ChatPage 清除 sessionStorage 任务记录
        // 仅在当前请求仍是活跃请求时触发，避免被新的请求覆盖后误清
        if (streamTaskId && activeRequestIdRef.current === requestId) {
          const finishedTaskId = streamTaskId
          activeTaskIdRef.current = null
          activeTaskLastSeqRef.current = -1
          onTaskFinished?.(finishedTaskId)
        }
        onFinally()
      }
    },
    [
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
      streamExecution,
      subagentSync,
      setTodoItems,
      setTodoSummary,
      setAskUserRequest,
      setStreamingAssistantId,
      setLoading,
      messageMeta,
      addMessage,
      addActiveToolCall,
      removeActiveToolCall,
      resetActiveToolCalls,
      upsertConversation,
      setMessageMeta,
      onApiKeyStale,
      onTaskStarted,
      onTaskSeq,
      onTaskFinished,
      trackEventSeq,
    ]
  )

  /**
   * 重连订阅已存在的后端任务事件流。
   *
   * 使用场景：用户切换到其他页面后切回 ChatPage，此时原 SSE 连接已断开，
   * 但后端任务仍在运行（或已完成）。前端通过 task_id + from_seq 重连订阅，
   * 后端从 from_seq 开始回放历史事件 + 继续推送实时事件。
   *
   * 与 handleSendMessage 的差异：
   * - 不发送新的用户消息
   * - 复用已存在的 assistantMessageId（不创建新消息）
   * - 调用 GET /chat/stream/{taskId} 而非 POST /chat
   * - 不传 executionOptions（任务已在使用原始参数运行）
   */
  const resubscribeToTask = useCallback(
    async (
      taskId: string,
      assistantMessageId: string,
      fromSeq: number = -1
    ) => {
      const requestId = activeRequestIdRef.current + 1
      activeRequestIdRef.current = requestId
      activeAbortControllerRef.current?.abort()
      const abortController = new AbortController()
      activeAbortControllerRef.current = abortController

      // 设置任务追踪状态
      activeTaskIdRef.current = taskId
      activeTaskLastSeqRef.current = fromSeq

      let streamErrorHandled = false
      // 重连场景下助手消息已存在（由 handleSendMessage 首次创建并持久化到 sessionStore）
      // 标记为 true 以跳过 ensureAssistantMessage 的创建逻辑
      let assistantMessageCreated = true

      // 重置缓冲区：重连后从 fromSeq 开始接收事件，缓冲区需清空以避免旧内容残留
      bufferRef.current = { content: '', reasoning: '', lastUpdateTime: Date.now() }

      setLoading(true)
      setStreamingAssistantId(assistantMessageId)
      streamExecution.beginStreamExecution('stream')

      try {
        await chatAPI.resubscribeStream(
          taskId,
          (event) => {
            if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
              return
            }

            // 追踪事件 seq
            trackEventSeq(event, taskId)

            streamExecution.markStreamStreaming()

            if (event?.type === 'status') {
              const nextStageMessage =
                typeof event.message === 'string' ? event.message.trim() : ''
              streamExecution.setStreamStageMessage(nextStageMessage || null)
              return
            }

            if (event?.type === 'chunk') {
              assistantMessageCreated = handleStreamChunkEvent({
                assistantMessageId,
                event,
                assistantMessageCreated,
                // 重连场景：消息已存在，ensureAssistantMessage 为空操作
                ensureAssistantMessage: () => false,
                updateAssistantSegments,
                appendAssistantMessageText,
                flushBuffer,
                buffer: bufferRef.current,
                isDocumentHidden: document.hidden,
              })
              return
            }

            // 工具调用追踪
            if (event?.type === 'tool') {
              const toolData = event.tool
              const toolId = String(toolData?.id || '')
              const toolStatus = String(toolData?.status || '')
              if (toolStatus === 'running') {
                addActiveToolCall(toolId)
              } else if (toolStatus === 'completed' || toolStatus === 'error') {
                removeActiveToolCall(toolId)
              }
            }

            // 结构化事件分发（子代理、todo、usage 等）
            dispatchStructuredStreamEvent(event, {
              assistantMessageId,
              messageMeta,
              addToast,
              updateAssistantMeta,
              updateAssistantSegments,
              clearSubagentAggregationTimer: subagentSync.clearSubagentAggregationTimer,
              scheduleSubagentTimeout: subagentSync.scheduleSubagentTimeout,
              syncSubagentRuntime: subagentSync.syncSubagentRuntime,
              clearSubagentTimeout: subagentSync.clearSubagentTimeout,
              clearSubagentSyncTimer: subagentSync.clearSubagentSyncTimer,
              scheduleSubagentAggregation: subagentSync.scheduleSubagentAggregation,
              setTodoItems,
              setTodoSummary,
              setAskUserRequest,
              dispatchUsageUpdated: ({ callId, provider, model }) => {
                dispatchBillingUsageUpdated({ callId, provider, model })
              },
            })
          },
          (error) => {
            const normalizedError = error instanceof Error ? error : new Error(String(error))
            const friendlyErrorMessage = getUserFriendlyErrorMessage(normalizedError)
            streamErrorHandled = true
            flushBuffer(assistantMessageId)
            streamExecution.markStreamFailed(sanitizeDisplayedError(friendlyErrorMessage))
            appLogger.error({
              event: 'chat_resubscribe_error',
              module: 'chat_page',
              action: 'receive_resubscribe_stream',
              status: 'failure',
              message: 'chat resubscribe stream error',
              extra: {
                error_category: classifyError(normalizedError),
                error: normalizedError.message,
                task_id: taskId,
              },
            })
            const errorContent = `\n\n${friendlyErrorMessage}`
            appendAssistantMessageText(assistantMessageId, errorContent)
            updateAssistantSegments(assistantMessageId, (segments) =>
              appendAssistantChunk(segments, {
                content: errorContent,
              })
            )
            finalizeAssistantMessageSegments(assistantMessageId)
          },
          { signal: abortController.signal, from_seq: Math.max(0, fromSeq + 1) }
        )

        flushBuffer(assistantMessageId)
        finalizeAssistantMessageSegments(assistantMessageId)
        streamExecution.clearStreamStageMessage()
        streamExecution.setIdleStreamState()
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          // 组件卸载或新请求中断：清理流式状态，不展示错误
          streamExecution.clearStreamStageMessage()
          streamExecution.setIdleStreamState()
          return
        }
        const normalizedError = error instanceof Error ? error : new Error(String(error))
        appLogger.error({
          event: 'chat_resubscribe_failed',
          module: 'chat_page',
          action: 'resubscribe',
          status: 'failure',
          message: 'chat resubscribe failed',
          extra: { error: normalizedError.message, task_id: taskId },
        })
        if (isMountedRef.current && activeRequestIdRef.current === requestId && !streamErrorHandled) {
          const friendlyErrorMessage = getUserFriendlyErrorMessage(normalizedError)
          const errorContent = `\n\n${friendlyErrorMessage}`
          appendAssistantMessageText(assistantMessageId, errorContent)
          updateAssistantSegments(assistantMessageId, (segments) =>
            appendAssistantChunk(segments, {
              content: errorContent,
            })
          )
        }
      } finally {
        resetActiveToolCalls()
        if (isMountedRef.current && activeRequestIdRef.current === requestId) {
          setLoading(false)
          setStreamingAssistantId(null)
          streamExecution.clearStreamStageMessage()
          if (!streamErrorHandled) {
            streamExecution.setIdleStreamState()
          }
        }
        // 任务结束：清除追踪状态并通知 ChatPage 清除 sessionStorage
        if (activeRequestIdRef.current === requestId) {
          const finishedTaskId = taskId
          activeTaskIdRef.current = null
          activeTaskLastSeqRef.current = -1
          onTaskFinished?.(finishedTaskId)
        }
      }
    },
    [
      isMountedRef,
      updateAssistantMeta,
      updateAssistantSegments,
      finalizeAssistantMessageSegments,
      appendAssistantMessageText,
      flushBuffer,
      addToast,
      streamExecution,
      subagentSync,
      setTodoItems,
      setTodoSummary,
      setAskUserRequest,
      setStreamingAssistantId,
      setLoading,
      messageMeta,
      addActiveToolCall,
      removeActiveToolCall,
      resetActiveToolCalls,
      onTaskFinished,
      trackEventSeq,
    ]
  )

  return {
    handleSendMessage,
    abortStream,
    resubscribeToTask,
    getActiveTaskId,
  }
}
