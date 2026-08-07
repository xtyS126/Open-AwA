/**
 * 聊天 API 模块。封装对话发送、SSE 流式、任务断连恢复、消息反馈、文件操作撤销等端点。自 api.ts 拆分而来。
 */
import { appLogger, generateRequestId, setCurrentRequestId } from '@/shared/utils/logger'
import { api, getCachedApiKey, refreshCsrfToken, getCachedCsrfToken, API_BASE_URL } from './client'
import type { ApiObject, ChatAttachmentType, ChatHistoryResponse, ChatUploadResponse, ChatCancelResponse, ChatTaskSummary, ChatTaskStatus, ChatFeedbackResponse, ChatUndoOperationResponse } from './types'

interface ChatStreamEvent {
  type?: string
  content?: unknown
  reasoning_content?: unknown
  message?: unknown
  result?: ApiObject | null
  task?: ApiObject | null
  tool?: ApiObject | null
  usage?: ApiObject | null
  /** 后端注入的事件序列号，用于断连重连时定位 from_seq */
  _seq?: number
  [key: string]: unknown
}

/**
 * 构造一个携带 error.code / error.retryable 的 Error 对象。
 * 当 code 存在时挂载到 Error 的 code 属性上，便于上层按错误码分支处理
 * （例如 llm_api_key_stale 触发跳转设置对话框）。
 * retryable 同步挂载，让 useChatStream 直接消费而无需重复字符串匹配。
 * 不改变 Error.name，避免破坏既有 onError(new Error(msg)) 形态的断言。
 */
function createStreamError(message: string, code?: string, retryable?: boolean): Error {
  const error = new Error(message) as Error & { code?: string; retryable?: boolean }
  if (code) {
    error.code = code
  }
  if (typeof retryable === 'boolean') {
    error.retryable = retryable
  }
  return error
}

/**
 * 解析 SSE 事件行并触发相应的回调。
 * 用于处理流式响应中的 chunk 和 tail 数据。
 *
 * @param lines SSE 事件行数组
 * @param onEvent 事件回调函数
 * @param onError 错误回调函数
 * @param context 日志上下文标识（'chunk' 或 'tail'）
 */
export function parseSSELines(
  lines: string[],
  onEvent?: (event: ChatStreamEvent) => void,
  onError?: (error: Error) => void,
  context: 'chunk' | 'tail' = 'chunk'
): void {
  let currentEventType = ''

  for (const line of lines) {
    // 空行重置事件类型
    if (line.trim() === '') {
      currentEventType = ''
      continue
    }

    // 解析事件类型
    if (line.startsWith('event: ')) {
      currentEventType = line.slice(7).trim()
      continue
    }

    // 解析数据行（兼容 "data: " 和 "data:" 两种格式）
    if (line.startsWith('data:')) {
      const dataStr = line.startsWith('data: ') ? line.slice(6) : line.slice(5)

      // 完成标记，停止解析
      if (dataStr === '[DONE]') {
        break
      }

      try {
        const data = JSON.parse(dataStr)

        // reasoning 事件：提取推理内容
        if (currentEventType === 'reasoning') {
          onEvent?.({ type: 'chunk', content: '', reasoning_content: data.content || '' })
        }
        // chunk 类型：提取内容和推理内容
        else if (data.type === 'chunk') {
          onEvent?.({ type: 'chunk', content: data.content || '', reasoning_content: data.reasoning_content || '' })
        }
        // error 类型：触发错误回调
        else if (data.type === 'error') {
          const errorCode = typeof data.error?.code === 'string' ? data.error.code : undefined
          const errorMessage = typeof data.error?.message === 'string' ? data.error.message : 'Stream error'
          const errorRetryable = typeof data.error?.retryable === 'boolean' ? data.error.retryable : undefined
          // 保留错误码与 retryable，便于上层按 code 做分支处理（如 llm_api_key_stale）
          // 与按 retryable 决策重试（避免重复字符串匹配 message）
          onError?.(createStreamError(errorMessage, errorCode, errorRetryable))
        }
        // 其他有类型的事件：直接传递
        else if (data?.type) {
          onEvent?.(data)
        }
      } catch {
        // 数据块解析失败：触发错误回调（标记可重试），不吞块 —— 回复内容缺失必须可见
        onError?.(createStreamError(`SSE 数据块解析失败（${context}），内容可能不完整，可重试`, undefined, true))
      }

      // 重置事件类型
      currentEventType = ''
    }
  }
}

export interface ChatContinuationPayload {
  source: string
  aggregated_context: string
  merge_with_last_assistant?: boolean
}

export interface ChatAttachmentPayload {
  type: ChatAttachmentType | string
  data: string
  mime_type: string
  file_name?: string
}

/** 用户消息反馈请求 */
export interface ChatFeedbackPayload {
  session_id: string
  message_id: string
  rating: 1 | -1
  comment?: string
}

/** AI 文件操作撤销请求 */
export interface UndoOperationPayload {
  operation_id: string
}

/** ask_user 提问回答提交请求 */
export interface AskUserReplyPayload {
  request_id: string
  session_id: string
  answer: string
  selected_options: string[]
}

/** ask_user 提问回答提交响应 */
export interface AskUserReplyResponse {
  ok: boolean
  message?: string
}

export interface ChatExecutionOptions {
  thinking_enabled?: boolean
  thinking_depth?: number
  max_tool_call_rounds?: number
  continuation?: ChatContinuationPayload
  // 任务 ID：前端生成，用于支持 SSE 断连重连恢复
  // 缺省时后端自动生成并在响应头 X-Chat-Task-Id 中返回
  task_id?: string
}

export interface ChatResponsePayload {
  status: string
  response: string
  reasoning_content?: string | null
  session_id?: string | null
  // error.code 用于上层分支处理，如 llm_api_key_stale 触发跳转设置
  error?: { code?: string; message?: string; [key: string]: unknown } | null
  request_id?: string | null
}

const buildChatRequestPayload = (
  message: string,
  sessionId: string,
  provider?: string,
  model?: string,
  mode: 'stream' | 'direct' = 'direct',
  executionOptions?: ChatExecutionOptions,
  attachments?: ChatAttachmentPayload[]
) => {
  const payload: ApiObject = {
    message,
    session_id: sessionId,
    provider,
    model,
    mode,
  }

  if (attachments && attachments.length > 0) {
    payload.attachments = attachments
  }
  if (executionOptions?.thinking_enabled !== undefined) {
    payload.thinking_enabled = executionOptions.thinking_enabled
  }
  if (executionOptions?.thinking_depth !== undefined) {
    payload.thinking_depth = executionOptions.thinking_depth
  }
  if (executionOptions?.max_tool_call_rounds !== undefined) {
    payload.max_tool_call_rounds = executionOptions.max_tool_call_rounds
  }
  if (executionOptions?.continuation) {
    payload.continuation = executionOptions.continuation
  }
  if (executionOptions?.task_id) {
    payload.task_id = executionOptions.task_id
  }

  return payload
}

async function fetchWithResponseTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number = 30_000,
): Promise<Response> {
  const controller = new AbortController()
  const sourceSignal = init.signal
  let timedOut = false
  const forwardAbort = () => controller.abort(sourceSignal?.reason)

  if (sourceSignal?.aborted) {
    forwardAbort()
  } else {
    sourceSignal?.addEventListener('abort', forwardAbort, { once: true })
  }

  const timeoutId = window.setTimeout(() => {
    timedOut = true
    controller.abort(new DOMException('请求连接超时', 'TimeoutError'))
  }, timeoutMs)

  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } catch (error) {
    if (timedOut) {
      throw Object.assign(new Error('请求连接超时，请稍后重试'), { cause: error })
    }
    throw error
  } finally {
    window.clearTimeout(timeoutId)
    sourceSignal?.removeEventListener('abort', forwardAbort)
  }
}

export const chatAPI = {
  sendMessage: (
    message: string,
    sessionId: string = 'default',
    provider?: string,
    model?: string,
    mode: 'stream' | 'direct' = 'direct',
    requestOptions?: { signal?: AbortSignal },
    executionOptions?: ChatExecutionOptions,
    attachments?: ChatAttachmentPayload[]
  ) =>
    api.post<ChatResponsePayload>(
      '/chat',
      buildChatRequestPayload(message, sessionId, provider, model, mode, executionOptions, attachments),
      { signal: requestOptions?.signal }
    ),
  sendMessageStream: async (
    message: string,
    sessionId: string = 'default',
    provider?: string,
    model?: string,
    onEvent?: (event: ChatStreamEvent) => void,
    onError?: (error: unknown) => void,
    requestOptions?: { signal?: AbortSignal; _csrfRetried?: boolean },
    executionOptions?: ChatExecutionOptions,
    attachments?: ChatAttachmentPayload[],
    onTaskId?: (taskId: string) => void
  ) => {
    let isErrorLogged = false
    const url = `${API_BASE_URL}/chat`
    const requestId = generateRequestId()
    setCurrentRequestId(requestId)

    appLogger.info({
      event: 'api_request',
      module: 'api',
      action: 'POST',
      status: 'start',
      request_id: requestId,
      message: 'api request started',
      extra: { url },
    })

    // TTFT 诊断：记录 fetch 发起时间，用于定位"正在连接流式通道"延迟根因
    const _ttft_t0 = Date.now()

    try {
      const apiKey = getCachedApiKey()
      const csrfToken = getCachedCsrfToken()
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'X-Request-Id': requestId,
      }
      if (apiKey) {
        headers['Authorization'] = `Bearer ${apiKey}`
      }
      // fetch 绕过 axios 拦截器，需手动附加 X-CSRF-Token
      // 否则 same-origin 携带 access_token Cookie 时会被 CSRF 中间件拒绝
      if (csrfToken) {
        headers['X-CSRF-Token'] = csrfToken
      }

      // 防御性清洗：移除 header 值中的非 ISO-8859-1 字符
      for (const hKey of Object.keys(headers)) {
        // eslint-disable-next-line no-control-regex
        headers[hKey] = headers[hKey].replace(/[^\x00-\xFF]/g, '')
      }

      let response = await fetchWithResponseTimeout(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers,
        signal: requestOptions?.signal,
        body: JSON.stringify(
          buildChatRequestPayload(message, sessionId, provider, model, 'stream', executionOptions, attachments)
        )
      })

      // TTFT 诊断：fetch 返回响应头的时间（TTFB 的网络+中间件+认证部分）
      const _ttft_fetch_ms = Date.now() - _ttft_t0
      appLogger.info({
        event: 'ttft_fetch_responded',
        module: 'api',
        request_id: requestId,
        message: `fetch 响应到达（含网络+中间件+认证）`,
        extra: { fetch_ms: _ttft_fetch_ms, status: response.status },
      })

      const responseRequestId = response.headers.get('x-request-id') || requestId
      if (responseRequestId) {
        setCurrentRequestId(responseRequestId)
      }

      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        const errorMessage = err?.detail || err?.error?.message || 'Request failed'
        // 保留后端返回的错误码，便于上层按 code 分支处理（如 llm_api_key_stale）
        const errorCode = typeof err?.error?.code === 'string' ? err.error.code : undefined

        // CSRF token 缺失或失效时自动刷新并重试一次（与 axios 拦截器逻辑一致）
        // fetch 绕过 axios 拦截器，需在此手动处理 403 missing_csrf_token / invalid_csrf_token
        const isCsrfError = (
          response.status === 403 &&
          (errorCode === 'missing_csrf_token' || errorCode === 'invalid_csrf_token' ||
           err?.error === 'missing_csrf_token' || err?.error === 'invalid_csrf_token')
        )
        if (isCsrfError && !requestOptions?._csrfRetried) {
          try {
            await refreshCsrfToken()
            const refreshedToken = getCachedCsrfToken()
            if (refreshedToken) {
              // 重发请求时携带新 token
              const retriedHeaders: Record<string, string> = {
                ...headers,
                'X-CSRF-Token': refreshedToken,
              }
              // 防御性清洗
              for (const hKey of Object.keys(retriedHeaders)) {
                // eslint-disable-next-line no-control-regex
                retriedHeaders[hKey] = retriedHeaders[hKey].replace(/[^\x00-\xFF]/g, '')
              }
              const retryResponse = await fetchWithResponseTimeout(url, {
                method: 'POST',
                credentials: 'same-origin',
                headers: retriedHeaders,
                signal: requestOptions?.signal,
                body: JSON.stringify(
                  buildChatRequestPayload(message, sessionId, provider, model, 'stream', executionOptions, attachments)
                )
              })
              // 用重试响应替换原响应，继续走下面的正常流程
              response = retryResponse
              if (response.ok) {
                appLogger.info({
                  event: 'csrf_retry_succeeded',
                  module: 'api',
                  action: 'POST',
                  status: 'success',
                  message: 'CSRF token 重试成功',
                })
              } else {
                // 重试仍失败，走错误处理
                const retryErr = await response.json().catch(() => ({}))
                const retryErrorMessage = retryErr?.detail || retryErr?.error?.message || 'Request failed'
                const retryErrorCode = typeof retryErr?.error?.code === 'string' ? retryErr.error.code : undefined
                isErrorLogged = true
                appLogger.error({
                  event: 'api_response',
                  module: 'api',
                  action: 'POST',
                  status: 'failure',
                  request_id: responseRequestId,
                  message: 'api request failed after CSRF retry',
                  extra: {
                    url,
                    status_code: response.status,
                    error: retryErrorMessage,
                  },
                })
                throw createStreamError(retryErrorMessage, retryErrorCode)
              }
            }
          } catch (refreshError) {
            // createStreamError 抛出的错误需要透传，避免被吞掉
            if (typeof refreshError === 'object' && refreshError !== null && 'code' in refreshError) {
              throw refreshError
            }
            appLogger.warning({
              event: 'csrf_retry_failed',
              module: 'api',
              action: 'POST',
              status: 'warning',
              message: 'CSRF token 自动重试失败',
              extra: { error: refreshError instanceof Error ? refreshError.message : String(refreshError) },
            })
          }
        }

        if (!response.ok) {
          isErrorLogged = true
          appLogger.error({
            event: 'api_response',
            module: 'api',
            action: 'POST',
            status: 'failure',
            request_id: responseRequestId,
            message: 'api request failed',
            extra: {
              url,
              status_code: response.status,
              error: errorMessage,
            },
          })
          throw createStreamError(errorMessage, errorCode)
        }
      }

      // 读取后端返回的 task_id（用于 SSE 断连重连恢复）
      // 后端在响应头 X-Chat-Task-Id 中返回 task_id，前端记录后切回页面时可重连
      // 放在 CSRF 重试之后，确保从最终有效的 response 读取
      const responseTaskId = response.headers.get('x-chat-task-id')
      if (responseTaskId && onTaskId) {
        try {
          onTaskId(responseTaskId)
        } catch (callbackErr) {
          appLogger.warning({
            event: 'chat_stream_task_id_callback_error',
            module: 'api',
            message: 'onTaskId 回调异常',
            extra: { error: String(callbackErr) },
          })
        }
      }

      appLogger.info({
        event: 'api_response',
        module: 'api',
        action: 'POST',
        status: 'success',
        request_id: responseRequestId,
        message: 'api request finished',
        extra: {
          url,
          status_code: response.status,
        },
      })

      if (!response.body) throw new Error('ReadableStream not yet supported in this browser.')

      const reader = response.body.getReader()
      try {
      const decoder = new TextDecoder('utf-8')
      let done = false
      let buffer = ''
      let _first_chunk_logged = false

      // SSE 流式响应最大大小限制 —— 防止后端异常/恶意推送导致前端内存耗尽
      const MAX_RESPONSE_BYTES = 10 * 1024 * 1024 // 10MB 上限
      let totalBytes = 0

      while (!done) {
        const { value, done: doneReading } = await reader.read()
        done = doneReading
        if (value) {
          // TTFT 诊断：首次读到响应体的时间（完整 TTFT）
          if (!_first_chunk_logged) {
            _first_chunk_logged = true
            const _ttft_total_ms = Date.now() - _ttft_t0
            appLogger.info({
              event: 'ttft_first_chunk',
              module: 'api',
              request_id: requestId,
              message: `首次收到流式数据（完整 TTFT）`,
              extra: {
                total_ms: _ttft_total_ms,
                fetch_to_first_chunk_ms: _ttft_total_ms - _ttft_fetch_ms,
              },
            })
          }
          // 累计已接收字节数，超过上限主动取消流并抛出错误
          totalBytes += value.byteLength
          if (totalBytes > MAX_RESPONSE_BYTES) {
            // 取消流读取，触发后端连接关闭
            void reader.cancel().catch(() => {
              // 忽略取消流时的异常（连接已关闭等情况）
            })
            throw new Error('响应超过 10MB 上限，已中止')
          }
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          // 解析当前批次的 SSE 事件行
          parseSSELines(lines, onEvent, onError, 'chunk')
        }
      }

      // 处理缓冲区中剩余的 SSE 事件
      if (buffer.trim()) {
        const remainingLines = buffer.trim().split('\n')
        parseSSELines(remainingLines, onEvent, onError, 'tail')
      }
      } finally {
        // 无论正常完成、解析失败还是主动取消，都必须释放流读取锁。
        reader.releaseLock()
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        throw e
      }
      if (!isErrorLogged) {
        appLogger.error({
          event: 'api_response',
          module: 'api',
          action: 'POST',
          status: 'failure',
          request_id: requestId,
          message: 'api stream request failed',
          extra: {
            url,
            error: e instanceof Error ? e.message : String(e),
          },
        })
      }
      onError?.(e)
      throw e
    }
  },
  getHistory: (sessionId: string) =>
    api.get<ChatHistoryResponse>(`/chat/history/${sessionId}`),
  confirmOperation: (confirmed: boolean, step: unknown) =>
    api.post('/chat/confirm', { confirmed, step }),
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<ChatUploadResponse>('/chat/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  /** 取消正在执行的 Agent 任务 */
  cancelSession: (sessionId: string) =>
    api.post<ChatCancelResponse>(`/chat/cancel/${sessionId}`),

  /** 取消指定聊天任务（按 task_id，级联清理子任务） */
  cancelTask: (taskId: string) =>
    api.post<{ status: string; task_id: string; message: string }>(`/chat/cancel-task/${taskId}`),

  /** 列出当前用户的聊天任务（用于切回页面时检查可恢复任务） */
  listTasks: (params?: { session_id?: string; include_finished?: boolean }) =>
    api.get<{ tasks: Array<ChatTaskSummary>; count: number }>('/chat/tasks', { params }),

  /** 查询指定聊天任务状态 */
  getTaskStatus: (taskId: string) =>
    api.get<ChatTaskStatus>(`/chat/tasks/${taskId}`),

  /**
   * 重连订阅聊天任务 SSE 流。
   * 前端切换页面或网络断开后，通过 task_id 重连订阅任务事件流，
   * 后端先回放历史事件（seq >= from_seq）再继续推送实时事件。
   */
  resubscribeStream: async (
    taskId: string,
    onEvent?: (event: ChatStreamEvent) => void,
    onError?: (error: unknown) => void,
    requestOptions?: { signal?: AbortSignal; from_seq?: number }
  ) => {
    let isErrorLogged = false
    const fromSeq = requestOptions?.from_seq ?? 0
    const url = `${API_BASE_URL}/chat/stream/${encodeURIComponent(taskId)}?from_seq=${fromSeq}`
    const requestId = generateRequestId()

    appLogger.info({
      event: 'api_request',
      module: 'api',
      action: 'GET',
      status: 'start',
      request_id: requestId,
      message: 'resubscribe chat task stream',
      extra: { url, task_id: taskId, from_seq: fromSeq },
    })

    try {
      const apiKey = getCachedApiKey()
      const csrfToken = getCachedCsrfToken()
      const headers: Record<string, string> = {
        'X-Request-Id': requestId,
      }
      if (apiKey) {
        headers['Authorization'] = `Bearer ${apiKey}`
      }
      if (csrfToken) {
        headers['X-CSRF-Token'] = csrfToken
      }
      for (const hKey of Object.keys(headers)) {
        // eslint-disable-next-line no-control-regex
        headers[hKey] = headers[hKey].replace(/[^\x00-\xFF]/g, '')
      }

      const response = await fetchWithResponseTimeout(url, {
        method: 'GET',
        credentials: 'same-origin',
        headers,
        signal: requestOptions?.signal,
      })

      if (!response.ok) {
        isErrorLogged = true
        const err = await response.json().catch(() => ({}))
        const errorMessage = err?.detail || err?.error?.message || 'Resubscribe failed'
        appLogger.error({
          event: 'api_response',
          module: 'api',
          action: 'GET',
          status: 'failure',
          request_id: requestId,
          message: 'resubscribe failed',
          extra: { url, status_code: response.status, error: errorMessage },
        })
        throw createStreamError(errorMessage)
      }

      if (!response.body) throw new Error('ReadableStream not yet supported in this browser.')

      const reader = response.body.getReader()
      try {
      const decoder = new TextDecoder('utf-8')
      let done = false
      let buffer = ''
      const MAX_RESPONSE_BYTES = 10 * 1024 * 1024
      let totalBytes = 0

      while (!done) {
        const { value, done: doneReading } = await reader.read()
        done = doneReading
        if (value) {
          totalBytes += value.byteLength
          if (totalBytes > MAX_RESPONSE_BYTES) {
            void reader.cancel().catch(() => {})
            throw new Error('响应超过 10MB 上限，已中止')
          }
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          parseSSELines(lines, onEvent, onError, 'chunk')
        }
      }

      if (buffer.trim()) {
        const remainingLines = buffer.trim().split('\n')
        parseSSELines(remainingLines, onEvent, onError, 'tail')
      }
      } finally {
        // 无论正常完成、解析失败还是主动取消，都必须释放流读取锁。
        reader.releaseLock()
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        throw e
      }
      if (!isErrorLogged) {
        appLogger.error({
          event: 'api_response',
          module: 'api',
          action: 'GET',
          status: 'failure',
          request_id: requestId,
          message: 'resubscribe stream failed',
          extra: {
            url,
            error: e instanceof Error ? e.message : String(e),
          },
        })
      }
      onError?.(e)
      throw e
    }
  },

  /** 提交用户消息反馈（点赞/点踩） */
  sendFeedback: (payload: ChatFeedbackPayload) =>
    api.post<ChatFeedbackResponse>('/chat/feedback', payload),

  /** 撤销 AI 执行的文件操作 */
  undoOperation: (payload: UndoOperationPayload) =>
    api.post<ChatUndoOperationResponse>('/chat/undo-operation', payload),

  /** 提交用户对 ask_user 提问的回答 */
  replyAskUser: (payload: AskUserReplyPayload) =>
    api.post<AskUserReplyResponse>('/chat/ask-user/reply', payload),
}
