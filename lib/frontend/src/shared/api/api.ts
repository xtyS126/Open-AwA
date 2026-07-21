/**
 * API 模块统一入口。
 * 客户端实例和认证逻辑已提取至 client.ts，类型定义已提取至 types.ts。
 * 本文件保留所有 API 端点函数，供全应用导入使用。
 *
 * 认证策略：
 *   - 单用户模式：使用 API Key (Bearer) 认证
 *   - 状态变更请求自动附加 X-CSRF-Token（CSRF 防御已恢复，对应 P0-9）
 *   - 应用启动或登录成功后调用 refreshCsrfToken() 拉取 per-session CSRF token
 */
import { appLogger, generateRequestId, setCurrentRequestId } from '@/shared/utils/logger'
import {
  api,
  getCachedApiKey,
  setTempApiKey,
  persistApiKey as _persistApiKey,
  clearCachedApiKey,
  refreshCsrfToken,
  getCachedCsrfToken,
  getApiErrorDetail,
  logStreamParseWarning,
  API_BASE_URL,
} from './client'
import type {
  SkillsListResponse,
  SkillItem,
  SkillParseUploadResponse,
  PluginsListResponse,
  PluginItem,
  PluginsDiscoverResponse,
  PluginInstallResponse,
  ShortTermMemoryItem,
  ShortTermMemoryListResponse,
  LongTermMemoryItem,
  LongTermMemoryListResponse,
  MemorySearchResponse,
  PromptItem,
  PromptsListResponse,
  BehaviorStatsResponse,
  BehaviorLogsResponse,
  ChatHistoryResponse,
  ChatUploadResponse,
  ChatCancelResponse,
  ChatFeedbackResponse,
  ChatUndoOperationResponse,
  IssueFeedbackPayload,
  IssueFeedbackSubmitResponse,
} from './types'

// 向后兼容：保持原有命名导出
export {
  getCachedApiKey,
  setTempApiKey,
  clearCachedApiKey,
  getApiErrorDetail,
  logStreamParseWarning,
  refreshCsrfToken,
  getCachedCsrfToken,
}

/**
 * 持久化 API Key 后异步拉取 CSRF token。
 *
 * 此函数包装了 client.ts 的 persistApiKey：在 API Key 持久化成功后，
 * 触发后台异步拉取 per-session CSRF token，确保后续状态变更请求携带 X-CSRF-Token。
 *
 * 调用时机：登录成功后由 LoginPage 调用。CSRF token 拉取失败不阻塞登录流程，
 * 后续 POST/PUT/PATCH/DELETE 请求会因缺失 CSRF token 被后端拒绝（响应拦截器会自动重试一次）。
 *
 * @param key 已验证通过的 API Key
 */
export function persistApiKey(key: string): void {
  _persistApiKey(key)
  // 异步拉取 CSRF token，不阻塞登录主流程；失败时仅记录警告
  void refreshCsrfToken()
}

// 端点函数内部使用的本地类型别名
type ApiPayload = Record<string, unknown>
type ApiObject = Record<string, unknown>
type ConversationSortKey = 'title' | 'created_at' | 'updated_at' | 'last_message_at' | 'message_count'
type ConversationSortOrder = 'asc' | 'desc'
type WeixinAutoReplyMatchType = 'keyword' | 'regex'
type ChatAttachmentType = 'image' | 'audio' | 'video'
type ScheduledTaskType = 'ai_prompt' | 'plugin_command'

// 端点函数内部使用的本地接口
interface ChatStreamEvent {
  type?: string
  content?: unknown
  reasoning_content?: unknown
  message?: unknown
  result?: ApiObject | null
  task?: ApiObject | null
  tool?: ApiObject | null
  usage?: ApiObject | null
  [key: string]: unknown
}

/**
 * 构造一个携带 error.code 的 Error 对象。
 * 当 code 存在时挂载到 Error 的 code 属性上，便于上层按错误码分支处理
 * （例如 llm_api_key_stale 触发跳转设置对话框）。
 * 不改变 Error.name，避免破坏既有 onError(new Error(msg)) 形态的断言。
 */
function createStreamError(message: string, code?: string): Error {
  const error = new Error(message) as Error & { code?: string }
  if (code) {
    error.code = code
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
          // 保留错误码，便于上层按 code 做分支处理（如 llm_api_key_stale）
          onError?.(createStreamError(errorMessage, errorCode))
        }
        // 其他有类型的事件：直接传递
        else if (data?.type) {
          onEvent?.(data)
        }
      } catch {
        logStreamParseWarning(dataStr, context)
      }

      // 重置事件类型
      currentEventType = ''
    }
  }
}

export const authAPI = {
  /** 使用用户名密码登录（兼容旧 JWT 路径，前端通常直接使用 API Key） */
  login: (username: string, password: string) => {
    let formData: string | URLSearchParams
    try {
      formData = new URLSearchParams({ username, password })
    } catch {
      formData = `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`
    }
    return api.post('/auth/login', formData, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    })
  },
  /** 获取当前用户信息（API Key 认证） */
  getMe: () => api.get('/auth/me'),
  /** 登出（清除 JWT Cookie，API Key 模式下通常不需要） */
  logout: () => api.post('/auth/logout'),
  /** 轮转 API Key */
  rotateApiKey: (confirm: boolean = true) =>
    api.post('/auth/rotate-api-key', { confirm }),
}

export interface UserProfileAnalysis {
  interests?: string[]
  total_actions?: number
  active_hours?: string[]
  [key: string]: unknown
}

export interface UserProfile {
  user_id: string
  username: string
  nickname?: string | null
  avatar_url?: string | null
  email?: string | null
  phone?: string | null
  profile: UserProfileAnalysis
}

export interface UserProfileUpdatePayload {
  nickname?: string
  email?: string
  phone?: string
}

export interface LoginDeviceItem {
  id: number
  device_type: string
  ip_address?: string | null
  user_agent?: string | null
  logged_in_at: string
  last_active_at: string
  is_online: boolean
  is_current: boolean
}

export interface UserPreferencesResponse {
  preferences: Record<string, unknown>
}

export interface AvatarUploadResponse {
  avatar_url: string
  message: string
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

export const userAPI = {
  getProfile: () => api.get<UserProfile>('/user/profile'),
  updateProfile: (payload: UserProfileUpdatePayload) => api.put<{ message: string }>('/user/profile', payload),
  uploadAvatar: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<AvatarUploadResponse>('/user/avatar', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },
  getDevices: () => api.get<LoginDeviceItem[]>('/user/devices'),
  revokeDevice: (deviceId: number) => api.post<{ message: string }>(`/user/devices/${deviceId}/revoke`),
  getPreferences: () => api.get<UserPreferencesResponse>('/user/preferences'),
  updatePreferences: (preferences: Record<string, unknown>) =>
    api.put<UserPreferencesResponse>('/user/preferences', { preferences }),
}

export const passwordAPI = {
  change: (oldPassword: string, newPassword: string, confirmPassword: string) =>
    api.put<{ message: string }>('/auth/me/password', {
      old_password: oldPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),
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

  return payload
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
    attachments?: ChatAttachmentPayload[]
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

      let response = await fetch(url, {
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
              const retryResponse = await fetch(url, {
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

export const skillsAPI = {
  getAll: () => api.get<SkillsListResponse>('/skills'),
  getOne: (id: string) => api.get<SkillItem>(`/skills/${id}`),
  install: (skill: ApiPayload) => api.post<SkillItem>('/skills', skill),
  uninstall: (id: string) => api.delete<{ ok: boolean; message?: string }>(`/skills/${id}`),
  toggle: (id: string) => api.put<SkillItem>(`/skills/${id}/toggle`),
  parseUpload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<SkillParseUploadResponse>('/skills/parse-upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },
}

export interface PluginPermissionStatus {
  plugin_id: string
  plugin_name: string
  requested_permissions: string[]
  granted_permissions: string[]
  missing_permissions: string[]
}

export interface PluginPermissionUpdateResponse extends PluginPermissionStatus {
  message: string
}

export interface PluginLogEntry {
  timestamp: string
  level: string
  message: string
  plugin_id: string
  extra: Record<string, unknown>
}

export interface PluginLogsResponse {
  plugin_id: string
  plugin_name: string
  level_filter: string | null
  total: number
  entries: PluginLogEntry[]
}

export interface PluginLogLevelResponse {
  plugin_id: string
  plugin_name: string
  level: string
}

export interface PluginConfigSchemaResponse {
  plugin_id: string
  plugin_name: string
  schema: Record<string, unknown>
  default_config: Record<string, unknown>
  current_config: Record<string, unknown>
  config_file_exists: boolean
}

export interface PluginConfigResponse {
  plugin_id: string
  plugin_name: string
  config: Record<string, unknown>
}

export interface SystemLogRecord {
  timestamp: string
  level: string
  service: string
  module: string
  event: string
  message: string
  request_id: string
  extra: Record<string, unknown>
}

export interface SystemLogsQueryResponse {
  total: number
  offset: number
  limit: number
  records: SystemLogRecord[]
}

export const pluginsAPI = {
  getAll: () => api.get<PluginsListResponse>('/plugins'),
  getOne: (id: string) => api.get<PluginItem>(`/plugins/${id}`),
  discover: () => api.get<PluginsDiscoverResponse>('/plugins/discover'),
  install: (plugin: ApiPayload) => api.post<PluginInstallResponse>('/plugins', plugin),
  execute: (id: string, method: string, params: Record<string, unknown> = {}) =>
    api.post<{ result: unknown; error?: string }>(`/plugins/${id}/execute`, { method, params }),
  update: (id: string, payload: ApiPayload) => api.put<PluginItem>(`/plugins/${id}`, payload),
  uninstall: (id: string) => api.delete<{ ok: boolean; message?: string }>(`/plugins/${id}`),
  toggle: (id: string) => api.put<PluginItem>(`/plugins/${id}/toggle`),
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<PluginInstallResponse>('/plugins/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },
  importFromUrl: (sourceUrl: string, timeoutSeconds: number = 30) =>
    api.post<PluginInstallResponse>('/plugins/import-url', { source_url: sourceUrl, timeout_seconds: timeoutSeconds }),
  getPermissions: (id: string) => api.get<PluginPermissionStatus>(`/plugins/${id}/permissions`),
  authorizePermissions: (id: string, permissions: string[]) =>
    api.post<PluginPermissionUpdateResponse>(`/plugins/${id}/permissions/authorize`, { permissions }),
  revokePermissions: (id: string, permissions: string[]) =>
    api.post<PluginPermissionUpdateResponse>(`/plugins/${id}/permissions/revoke`, { permissions }),
  getLogs: (id: string, level?: string, limit = 100, offset = 0) =>
    api.get<PluginLogsResponse>(`/plugins/${id}/logs`, { params: { level, limit, offset } }),
  setLogLevel: (id: string, level: string) =>
    api.put<PluginLogLevelResponse>(`/plugins/${id}/log-level`, { level }),
  getConfigSchema: (id: string) =>
    api.get<PluginConfigSchemaResponse>(`/plugins/${id}/config/schema`),
  saveConfig: (id: string, config: Record<string, unknown>) =>
    api.put<PluginConfigResponse>(`/plugins/${id}/config`, config),
  resetConfig: (id: string) =>
    api.post<PluginConfigResponse>(`/plugins/${id}/config/reset`),
  exportConfig: (id: string) =>
    api.get<PluginConfigResponse>(`/plugins/${id}/config/export`),
}

export const logsAPI = {
  query: (params?: {
    start_time?: string
    end_time?: string
    level?: string
    keyword?: string
    limit?: number
    offset?: number
  }) => api.get<SystemLogsQueryResponse>('/logs', { params }),
  export: (params?: {
    start_time?: string
    end_time?: string
    level?: string
    keyword?: string
  }) => api.get('/logs/export', { params, responseType: 'blob' }),
}

export interface SysDiagnosticsCheck {
  name: string
  label: string
  ok: boolean
  detail: Record<string, unknown> | null
}

export interface SysDiagnosticsResponse {
  timestamp: number
  overall: 'healthy' | 'degraded' | 'error' | string
  passed: number
  total: number
  checks: SysDiagnosticsCheck[]
}

export interface SystemPingResponse {
  pong: boolean
  timestamp: number
}

// 系统初始化状态响应（对应后端 GET /api/system/init-status）
export interface SystemInitStatusResponse {
  success: boolean
  data: {
    initialized: boolean
    has_users: boolean | null
    initialized_at?: string | null
    db_error?: string | null
  }
}

// 系统初始化请求体（对应后端 POST /api/system/init）
export interface SystemInitRequest {
  username: string
  password: string
  email?: string
  nickname?: string
  force?: boolean
  regenerate_secrets?: boolean
}

// 系统初始化响应体
export interface SystemInitResponse {
  success: boolean
  data: {
    user_id: string
    username: string
    secrets_generated: boolean
    api_key_generated: boolean
  }
}

export interface ScenarioDef {
  name: string
  label: string
  category: string
  description: string
}

export interface ScenarioListResponse {
  total: number
  scenarios: ScenarioDef[]
}

export interface ScenarioResultItem {
  name: string
  label: string
  category: string
  status: 'idle' | 'running' | 'ok' | 'fail' | string
  duration_ms: number
  message: string
  detail: Record<string, unknown> | null
}

export interface ScenarioRunResponse {
  results: ScenarioResultItem[]
  passed: number
  failed: number
  total: number
  duration_ms: number
}

export const systemAPI = {
  ping: () => api.get<SystemPingResponse>('/system/ping'),
  diagnostics: () => api.get<SysDiagnosticsResponse>('/system/diagnostics'),
  // 系统初始化状态检测（首次部署引导页用）
  getInitStatus: () => api.get<SystemInitStatusResponse>('/system/init-status'),
  // 执行系统初始化（创建 owner 用户并生成密钥）
  init: (payload: SystemInitRequest) =>
    api.post<SystemInitResponse>('/system/init', payload),
}

export const testRunnerAPI = {
  listScenarios: () => api.get<ScenarioListResponse>('/test-scenarios'),
  runScenario: (name: string) => api.post<ScenarioRunResponse>('/test-scenarios/run', { name }),
  runAllScenarios: () => api.post<ScenarioRunResponse>('/test-scenarios/run-all'),
}

export const memoryAPI = {
  getShortTerm: (sessionId: string) =>
    api.get<ShortTermMemoryListResponse>(`/memory/short-term/${sessionId}`),
  addShortTerm: (sessionId: string, role: string, content: string) =>
    api.post<ShortTermMemoryItem>('/memory/short-term', { session_id: sessionId, role, content }),
  deleteShortTerm: (id: number) =>
    api.delete<{ ok: boolean; message?: string }>(`/memory/short-term/${id}`),
  getLongTerm: () => api.get<LongTermMemoryListResponse>('/memory/long-term'),
  addLongTerm: (content: string, importance: number = 0.5) =>
    api.post<LongTermMemoryItem>('/memory/long-term', { content, importance }),
  deleteLongTerm: (id: number) =>
    api.delete<{ ok: boolean; message?: string }>(`/memory/long-term/${id}`),
  search: (query: string) => api.get<MemorySearchResponse>('/memory/search', { params: { query } }),
}

export const promptsAPI = {
  getAll: () => api.get<PromptsListResponse>('/prompts'),
  getActive: () => api.get<PromptItem>('/prompts/active'),
  getOne: (id: string) => api.get<PromptItem>(`/prompts/${id}`),
  create: (prompt: ApiPayload) => api.post<PromptItem>('/prompts', prompt),
  update: (id: string, prompt: ApiPayload) => api.put<PromptItem>(`/prompts/${id}`, prompt),
  delete: (id: string) => api.delete<{ ok: boolean; message?: string }>(`/prompts/${id}`),
}

export interface ConversationSessionSummary {
  session_id: string
  user_id: string
  title: string
  summary: string
  last_message_preview: string
  last_message_role?: string | null
  message_count: number
  created_at: string
  updated_at: string
  last_message_at?: string | null
  deleted_at?: string | null
  restored_at?: string | null
  purge_after?: string | null
  conversation_metadata: Record<string, unknown>
}

export interface ConversationSessionCreatePayload {
  title?: string
  session_id?: string
}

export interface ConversationSessionListParams {
  search?: string
  sort_by?: ConversationSortKey
  sort_order?: ConversationSortOrder
  page?: number
  page_size?: number
  include_deleted?: boolean
}

export interface ConversationSessionListResponse {
  items: ConversationSessionSummary[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export interface ScheduledTask {
  id: number
  user_id: string
  title: string
  prompt: string
  scheduled_at: string
  status: string
  provider: string | null
  model: string | null
  is_daily?: boolean | null
  cron_expression?: string | null
  weekdays?: string | null
  daily_time?: string | null
  task_type?: ScheduledTaskType | string | null
  plugin_name?: string | null
  command_name?: string | null
  command_params?: Record<string, unknown>
  last_error_message: string | null
  task_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  completed_at: string | null
  cancelled_at: string | null
  next_execution_at?: string | null
}

export interface ScheduledTaskExecution {
  id: number
  task_id: number
  user_id: string
  task_title: string
  prompt: string
  scheduled_for: string
  status: string
  response: string | null
  error_message: string | null
  provider: string | null
  model: string | null
  request_id: string | null
  execution_metadata: Record<string, unknown>
  started_at: string
  completed_at: string | null
}

export interface ScheduledTaskCreatePayload {
  title: string
  prompt: string
  scheduled_at: string
  provider?: string | null
  model?: string | null
  is_daily?: boolean | null
  cron_expression?: string | null
  weekdays?: string | null
  daily_time?: string | null
  task_type?: ScheduledTaskType | string
  plugin_name?: string | null
  command_name?: string | null
  command_params?: Record<string, unknown>
}

export interface ScheduledTaskUpdatePayload {
  title?: string
  prompt?: string
  scheduled_at?: string
  provider?: string | null
  model?: string | null
  is_daily?: boolean | null
  cron_expression?: string | null
  weekdays?: string | null
  daily_time?: string | null
  task_type?: ScheduledTaskType | string
  plugin_name?: string | null
  command_name?: string | null
  command_params?: Record<string, unknown>
}

export interface PluginCommandInfo {
  plugin_name: string
  plugin_version: string
  plugin_description: string
  command_name: string
  command_description: string
  command_method: string
  parameters: Record<string, unknown>
}

export const scheduledTasksAPI = {
  getAll: (params?: { status?: string; limit?: number }) =>
    api.get<ScheduledTask[]>('/scheduled-tasks', { params }),
  getOne: (id: number) =>
    api.get<ScheduledTask>(`/scheduled-tasks/${id}`),
  create: (payload: ScheduledTaskCreatePayload) =>
    api.post<ScheduledTask>('/scheduled-tasks', payload),
  update: (id: number, payload: ScheduledTaskUpdatePayload) =>
    api.put<ScheduledTask>(`/scheduled-tasks/${id}`, payload),
  cancel: (id: number) =>
    api.delete<{ message: string }>(`/scheduled-tasks/${id}`),
  getExecutions: (params?: { task_id?: number; limit?: number }) =>
    api.get<ScheduledTaskExecution[]>('/scheduled-tasks/executions', { params }),
  getPluginCommands: () =>
    api.get<PluginCommandInfo[]>('/scheduled-tasks/plugin-commands'),
}

export interface ConversationRecordItem {
  id: number
  session_id: string
  user_id: string
  node_type: string
  user_message: string
  timestamp: string | null
  provider: string | null
  model: string | null
  llm_input: unknown
  llm_output: unknown
  llm_tokens_used: number | null
  execution_duration_ms: number | null
  status: string
  error_message: string | null
  metadata: unknown
}

export interface ConversationRecordsResponse {
  records: ConversationRecordItem[]
  count: number
  limit: number
}

export interface ConversationCollectionStatusResponse {
  enabled: boolean
  stats: {
    queue_size: number
    queue_maxsize: number
    dropped_count: number
    tracked_user_count: number
  }
}

export const conversationAPI = {
  listSessions: (params?: ConversationSessionListParams) =>
    api.get<ConversationSessionListResponse>('/conversations', { params }),
  createSession: (payload: ConversationSessionCreatePayload = {}) =>
    api.post<ConversationSessionSummary>('/conversations', payload),
  renameSession: (sessionId: string, title: string) =>
    api.patch<ConversationSessionSummary>(`/conversations/${sessionId}`, { title }),
  deleteSession: (sessionId: string, retentionDays: number = 30) =>
    api.delete<ConversationSessionSummary>(`/conversations/${sessionId}`, {
      params: { retention_days: retentionDays },
    }),
  restoreSession: (sessionId: string) =>
    api.post<ConversationSessionSummary>(`/conversations/${sessionId}/restore`),
  batchDeleteSessions: (sessionIds: string[], retentionDays: number = 30) =>
    api.post<ConversationSessionListResponse>('/conversations/batch-delete', {
      session_ids: sessionIds,
      retention_days: retentionDays,
    }),
  getCollectionStatus: () =>
    api.get<ConversationCollectionStatusResponse>('/conversations/collection-status'),
  updateCollectionStatus: (enabled: boolean) =>
    api.put('/conversations/collection-status', null, { params: { enabled } }),
  getRecordsPreview: (limit: number = 20) =>
    api.get<ConversationRecordsResponse>('/conversations/records', { params: { limit } }),
  exportRecords: (params?: { start_time?: string; end_time?: string }) =>
    api.get('/conversations/export', { params, responseType: 'blob' }),
  cleanupRecords: (days: number = 30) =>
    api.delete('/conversations/records/cleanup', { params: { days } }),
}

export const behaviorAPI = {
  getStats: (days: number = 7) =>
    api.get<BehaviorStatsResponse>(`/behaviors/stats?days=${days}`),
  getLogs: (skip: number = 0, limit: number = 50) =>
    api.get<BehaviorLogsResponse>(`/behaviors/logs?skip=${skip}&limit=${limit}`),
  logBehavior: (actionType: string, details: string) =>
    api.post<{ ok: boolean; message?: string }>('/behaviors/log', { action_type: actionType, details }),
}

export interface WeixinConfig {
  account_id: string
  token: string
  base_url: string
  timeout_seconds: number
  user_id?: string
  binding_status?: string
  bot_token?: string
  ilink_bot_id?: string
  ilink_user_id?: string
  bot_type?: string
  channel_version?: string
}

export interface WeixinBindingInfo {
  id?: number
  user_id: string
  weixin_account_id: string
  base_url: string
  bot_type: string
  channel_version: string
  binding_status: string
  weixin_user_id: string
}

export interface WeixinBindingCreate {
  weixin_account_id: string
  token: string
  base_url?: string
  bot_type?: string
  channel_version?: string
  binding_status?: string
  weixin_user_id?: string
}

export interface WeixinParamsConfig {
  base_url: string
  bot_type: string
  channel_version: string
  weixin_default_base_url: string
  weixin_default_bot_type: string
  weixin_default_channel_version: string
  session_timeout_seconds: number
  token_refresh_enabled: boolean
  auto_start_reply?: boolean
}

export interface WeixinParamsUpdate {
  bot_type?: string
  channel_version?: string
  base_url?: string
  auto_start_reply?: boolean
}

export interface WeixinHealthCheckResult {
  ok: boolean
  issues: string[]
  suggestions: string[]
}

export interface WeixinQrStartRequest {
  session_key?: string
  base_url?: string
  bot_type?: string
  force?: boolean
  timeout_seconds?: number
}

export type WeixinQrState = 'pending' | 'half_success' | 'success' | 'failed'

export type WeixinQrStatus = 'idle' | 'waiting' | 'scanned' | 'scaned_but_redirect' | 'expired' | 'confirmed' | 'refreshing'

export interface WeixinQrStartResponse {
  success?: boolean
  state?: WeixinQrState
  message: string
  session_key: string
  status: 'wait' | 'waiting'
  qrcode?: string
  qrcode_url?: string
  qrcode_content?: string
  baseurl?: string
}

export interface WeixinQrWaitRequest {
  session_key: string
  timeout_seconds?: number
  qrcode?: string
  base_url?: string
}

export interface WeixinQrWaitResponse {
  success?: boolean
  state?: WeixinQrState
  connected: boolean
  session_key: string
  status: 'wait' | 'waiting' | 'scanned' | 'scaned' | 'scaned_but_redirect' | 'confirmed' | 'expired' | 'refreshing'
  message: string
  qrcode?: string
  qrcode_url?: string
  qrcode_content?: string
  auth_id?: string
  ticket?: string
  hint?: string
  account_id?: string
  ilink_bot_id?: string
  token?: string
  bot_token?: string
  base_url?: string
  baseurl?: string
  redirect_host?: string
  user_id?: string
  ilink_user_id?: string
  binding_status?: string
}

export interface WeixinQrExitRequest {
  session_key?: string
  clear_config?: boolean
}

export interface WeixinQrExitResponse {
  message: string
  cleared_sessions: number
}

export interface WeixinAutoReplyStatus {
  user_id: string
  binding_status: string
  binding_ready: boolean
  weixin_account_id?: string
  weixin_user_id?: string
  auto_reply_enabled: boolean
  auto_reply_running: boolean
  last_poll_at: string
  last_poll_status: string
  last_error: string
  last_error_at: string
  last_success_at: string
  last_reply_at: string
  last_replied_user_id: string
  last_processed_message_id: string
  cursor: string
  processed_message_count: number
}

export interface WeixinAutoReplyProcessResult {
  ok: boolean
  status: string
  processed: number
  skipped: number
  duplicates: number
  errors: number
  cursor_advanced: boolean
  cursor?: string
  error?: string
  poison_skipped?: number
}

export interface WeixinAutoReplyRule {
  id: number
  user_id: string
  rule_name: string
  match_type: WeixinAutoReplyMatchType
  match_pattern: string
  reply_content: string
  is_active: boolean
  priority: number
  created_at: string
  updated_at: string
}

export interface WeixinAutoReplyRuleCreate {
  rule_name: string
  match_type?: WeixinAutoReplyMatchType
  match_pattern: string
  reply_content: string
  is_active?: boolean
  priority?: number
}

export interface WeixinAutoReplyRuleUpdate {
  rule_name?: string
  match_type?: WeixinAutoReplyMatchType
  match_pattern?: string
  reply_content?: string
  is_active?: boolean
  priority?: number
}

export const weixinAPI = {
  getConfig: () => api.get<WeixinConfig>('/skills/weixin/config'),
  saveConfig: (config: WeixinConfig) => api.post('/skills/weixin/config', config),
  healthCheck: (config: WeixinConfig) => api.post<WeixinHealthCheckResult>('/skills/weixin/health-check', config),
  startQrLogin: (payload: WeixinQrStartRequest = {}) => api.post<WeixinQrStartResponse>('/skills/weixin/qr/start', payload),
  waitQrLogin: (payload: WeixinQrWaitRequest) => api.post<WeixinQrWaitResponse>('/skills/weixin/qr/wait', payload),
  exitQrLogin: (payload: WeixinQrExitRequest) => api.post<WeixinQrExitResponse>('/skills/weixin/qr/exit', payload),
  getBinding: () => api.get<WeixinBindingInfo>('/weixin/binding'),
  saveBinding: (data: WeixinBindingCreate) => api.post<WeixinBindingInfo>('/weixin/binding', data),
  deleteBinding: () => api.delete('/weixin/binding'),
  getParams: () => api.get<WeixinParamsConfig>('/weixin/config'),
  updateParams: (data: WeixinParamsUpdate) => api.put<WeixinParamsConfig>('/weixin/config', data),
  getAutoReplyStatus: () => api.get<WeixinAutoReplyStatus>('/weixin/auto-reply/status'),
  startAutoReply: () => api.post<WeixinAutoReplyStatus>('/weixin/auto-reply/start'),
  stopAutoReply: () => api.post<WeixinAutoReplyStatus>('/weixin/auto-reply/stop'),
  restartAutoReply: () => api.post<WeixinAutoReplyStatus>('/weixin/auto-reply/restart'),
  processAutoReplyOnce: () => api.post<WeixinAutoReplyProcessResult>('/weixin/auto-reply/process-once'),
  getRules: () => api.get<WeixinAutoReplyRule[]>('/weixin/auto-reply/rules'),
  createRule: (payload: WeixinAutoReplyRuleCreate) =>
    api.post<WeixinAutoReplyRule>('/weixin/auto-reply/rules', payload),
  updateRule: (ruleId: number, payload: WeixinAutoReplyRuleUpdate) =>
    api.put<WeixinAutoReplyRule>(`/weixin/auto-reply/rules/${ruleId}`, payload),
  deleteRule: (ruleId: number) =>
    api.delete<{ message: string }>(`/weixin/auto-reply/rules/${ruleId}`),
  // 多媒体消息查询
  listRecentMultimedia: (params?: { limit?: number; media_type?: 'image' | 'voice' | 'file' | 'video' }) =>
    api.get<WeixinMultimediaMessage[]>('/weixin/multimedia/recent', { params }),
  getMultimediaDetail: (messageId: string) =>
    api.get<WeixinMultimediaDetail>(`/weixin/multimedia/${messageId}`),
}

export interface WeixinMultimediaMessage {
  message_id: string
  from_user_id: string
  message_type: string
  text: string
  media_type: 'image' | 'voice' | 'file' | 'video' | ''
  media_id: string
  file_url: string
  file_name: string
  file_size: number
  duration_ms: number
  media_format: string
  timestamp: string
}

export interface WeixinMultimediaDetail {
  message_id: string
  session_id: string
  content: string
  role: string
  timestamp: string
  reasoning_content: string
  tool_events: Array<Record<string, unknown>>
}

// 微信 WebSocket 实时消息事件类型
export type WeixinWsEvent =
  | { event: 'connected'; user_id: string }
  | { event: 'new_message'; message_id: string; from_user_id: string; text: string; message_type: string; multimedia: WeixinMultimediaMessage | null; timestamp: string }
  | { event: 'ping'; timestamp: string }

export interface DiaryGenerateResponse {
  success: boolean
  file_path?: string
  content?: string
  logical_date?: string
  error?: string
}

export interface DiaryListResponse {
  success: boolean
  diaries: Array<{ name: string; date: string; size: number }>
  count: number
}

export interface DiaryReadResponse {
  success: boolean
  date: string
  content: string
}

export const diaryAPI = {
  async generate(): Promise<DiaryGenerateResponse> {
    const response = await api.post('/diary/generate')
    return response.data
  },

  async list(): Promise<DiaryListResponse> {
    const response = await api.get('/diary/list')
    return response.data
  },

  async get(date: string): Promise<DiaryReadResponse> {
    const response = await api.get(`/diary/${date}`)
    return response.data
  },
}

/**
 * 问题反馈 API。
 * 提交用户反馈到后端，后端落盘为 markdown 文件并返回 file_id。
 * 注意：api.post 返回 AxiosResponse，这里通过 .then(r => r.data) 直接返回业务数据，
 * 便于调用方处理与单元测试 mock。
 */
export const issueFeedbackAPI = {
  submit: (payload: IssueFeedbackPayload) =>
    api
      .post<IssueFeedbackSubmitResponse>('/feedback/issue', payload)
      .then((r) => r.data),
}

export { api as sharedApi }
export default api
