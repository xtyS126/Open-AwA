import axios, { type InternalAxiosRequestConfig } from 'axios'
import { appLogger, generateRequestId, setCurrentRequestId } from '@/shared/utils/logger'

type ApiPayload = Record<string, unknown>

type ApiObject = Record<string, unknown>

type RetriableApiRequest = InternalAxiosRequestConfig & {
  _csrfRetried?: boolean
}

type ConversationSortKey = 'title' | 'created_at' | 'updated_at' | 'last_message_at' | 'message_count'

type ConversationSortOrder = 'asc' | 'desc'

type WeixinAutoReplyMatchType = 'keyword' | 'regex'

type ChatAttachmentType = 'image' | 'audio' | 'video'

type ScheduledTaskType = 'ai_prompt' | 'plugin_command'

export interface ChatStreamTeamPayload {
  team_id?: string
  name?: string
  ok?: boolean
  state?: string
  [key: string]: unknown
}

export interface ChatStreamEvent {
  type?: string
  content?: unknown
  reasoning_content?: unknown
  message?: unknown
  result?: ApiObject | null
  task?: ApiObject | null
  tool?: ApiObject | null
  usage?: ApiObject | null
  team?: ChatStreamTeamPayload | null
  task_id?: unknown
  agent_id?: unknown
  agent_type?: unknown
  description?: unknown
  run_mode?: unknown
  summary?: unknown
  state?: unknown
  [key: string]: unknown
}

const API_BASE_URL = '/api'

const CSRF_EXEMPT_PATHS = new Set(['/auth/login', '/auth/register'])
const CSRF_TOKEN_URL = `${API_BASE_URL}/auth/csrf-token`

let _cachedCsrfToken = ''

export const getCsrfToken = (): string => _cachedCsrfToken

let csrfBootstrapPromise: Promise<string> | null = null

const clearCsrfTokenCache = (): void => {
  _cachedCsrfToken = ''
  csrfBootstrapPromise = null
}

const shouldAttachCsrfToken = (method?: string, url?: string): boolean => {
  const normalizedMethod = String(method || 'GET').toUpperCase()
  if (!['POST', 'PUT', 'DELETE', 'PATCH'].includes(normalizedMethod)) {
    return false
  }
  const normalizedUrl = String(url || '').split('?')[0]
  return !CSRF_EXEMPT_PATHS.has(normalizedUrl)
}

const logStreamParseWarning = (payload: string, source: 'chunk' | 'tail') => {
  appLogger.warning({
    event: 'chat_stream_parse_warning',
    module: 'api',
    action: 'POST',
    status: 'warning',
    message: 'failed to parse stream payload',
    extra: {
      source,
      payload_preview: payload.slice(0, 100),
    },
  })
}

const ensureCsrfToken = async (): Promise<string> => {
  if (_cachedCsrfToken) {
    return _cachedCsrfToken
  }

  appLogger.warning({
    event: 'csrf_token_missing',
    module: 'api',
    action: 'BOOTSTRAP',
    status: 'warning',
    message: 'csrf token missing before mutating request, trying bootstrap request',
    extra: {
      bootstrap_path: CSRF_TOKEN_URL,
    },
  })

  if (!csrfBootstrapPromise) {
    csrfBootstrapPromise = (async () => {
      try {
        const response = await fetch(CSRF_TOKEN_URL, {
          method: 'GET',
          credentials: 'same-origin',
        })
        if (!response.ok) {
          throw new Error(`CSRF token request failed: ${response.status}`)
        }
        const data = await response.json()
        _cachedCsrfToken = data.csrf_token || ''
      } catch (error) {
        appLogger.warning({
          event: 'csrf_token_bootstrap_failed',
          module: 'api',
          action: 'BOOTSTRAP',
          status: 'warning',
          message: 'csrf token bootstrap request failed',
          extra: {
            error: error instanceof Error ? error.message : String(error),
          },
        })
      }

      if (!_cachedCsrfToken) {
        throw new Error('CSRF token missing after bootstrap request')
      }
      return _cachedCsrfToken
    })().finally(() => {
      csrfBootstrapPromise = null
    })
  }

  return csrfBootstrapPromise
}

export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use(async (config) => {
  const requestId = generateRequestId()
  config.headers['X-Request-Id'] = requestId
  setCurrentRequestId(requestId)

  // 对状态变更请求注入 CSRF token header（Double Submit Cookie 模式）
  if (shouldAttachCsrfToken(config.method, config.url)) {
    const csrfToken = await ensureCsrfToken()
    config.headers['X-CSRF-Token'] = csrfToken
  }
  appLogger.info({
    event: 'api_request',
    module: 'api',
    action: config.method?.toUpperCase() || 'GET',
    status: 'start',
    request_id: requestId,
    message: 'api request started',
    extra: {
      url: config.url,
    },
  })
  return config
})

api.interceptors.response.use(
  (response) => {
    const responseRequestId = String(response.headers?.['x-request-id'] || '')
    if (responseRequestId) {
      setCurrentRequestId(responseRequestId)
    }
    appLogger.info({
      event: 'api_response',
      module: 'api',
      action: response.config.method?.toUpperCase() || 'GET',
      status: 'success',
      request_id: responseRequestId,
      message: 'api request finished',
      extra: {
        url: response.config.url,
        status_code: response.status,
      },
    })
    return response
  },
  async (error) => {
    const responseRequestId = String(error?.response?.headers?.['x-request-id'] || '')
    if (responseRequestId) {
      setCurrentRequestId(responseRequestId)
    }

    const originalRequest = error?.config as RetriableApiRequest | undefined
    const shouldRetryInvalidCsrf = (
      error?.response?.status === 403 &&
      error?.response?.data?.error === 'invalid_csrf_token' &&
      originalRequest &&
      !originalRequest._csrfRetried &&
      shouldAttachCsrfToken(originalRequest.method, originalRequest.url)
    )

    if (shouldRetryInvalidCsrf && originalRequest) {
      originalRequest._csrfRetried = true
      clearCsrfTokenCache()

      try {
        const csrfToken = await ensureCsrfToken()
        const retryHeaders = axios.AxiosHeaders.from(originalRequest.headers || {})
        retryHeaders.set('X-CSRF-Token', csrfToken)
        originalRequest.headers = retryHeaders
        return api(originalRequest)
      } catch (refreshError) {
        appLogger.warning({
          event: 'csrf_token_refresh_retry_failed',
          module: 'api',
          action: originalRequest.method?.toUpperCase() || 'UNKNOWN',
          status: 'warning',
          request_id: responseRequestId,
          message: 'csrf token refresh retry failed',
          extra: {
            url: originalRequest.url,
            error: refreshError instanceof Error ? refreshError.message : String(refreshError),
          },
        })
      }
    }
    
    const isExpectedAuthError = (
      (error?.config?.url === '/auth/me' && error?.response?.status === 401) ||
      (error?.config?.url === '/auth/register' && error?.response?.status === 400)
    );

    if (!isExpectedAuthError) {
      const errorUrl = error?.config?.url || 'unknown'
      const errorStatus = error?.response?.status || 0
      const errorMessage = error?.message || ''
      const backendDetail = error?.response?.data?.detail || ''
      
      console.error(
        `[API ERROR] ${error?.config?.method?.toUpperCase() || 'GET'} ${errorUrl} -> ${errorStatus}` +
        (errorMessage ? ` | ${errorMessage}` : '') +
        (backendDetail ? ` | Detail: ${backendDetail}` : '') +
        (responseRequestId ? ` | Request-ID: ${responseRequestId}` : '')
      )
      
      appLogger.error({
        event: 'api_response',
        module: 'api',
        action: error?.config?.method?.toUpperCase() || 'GET',
        status: 'failure',
        request_id: responseRequestId,
        message: 'api request failed',
        extra: {
          url: errorUrl,
          status_code: errorStatus,
          error: errorMessage,
          detail: backendDetail,
        },
      })
    }
    return Promise.reject(error)
  }
)

export const authAPI = {
  login: (username: string, password: string) => {
    try {
      const formData = new URLSearchParams({ username, password })
      return api.post('/auth/login', formData, {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
      })
    } catch {
      const formData = `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`
      return api.post('/auth/login', formData, {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
      })
    }
  },
  register: (username: string, password: string) =>
    api.post('/auth/register', { username, password }),
  getMe: () => api.get('/auth/me'),
  logout: () => api.post('/auth/logout'),
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
  error?: { message?: string; [key: string]: unknown } | null
  request_id?: string | null
}

export const getApiErrorDetail = (error: unknown): string => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') {
          return item
        }
        if (item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string') {
          return item.msg
        }
        return ''
      })
      .filter(Boolean)
    if (messages.length > 0) {
      return messages.join('；')
    }
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return ''
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
    requestOptions?: { signal?: AbortSignal },
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

    try {
      const csrfToken = await ensureCsrfToken()
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'X-Request-Id': requestId,
        'X-CSRF-Token': csrfToken,
      }

      const response = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers,
        signal: requestOptions?.signal,
        body: JSON.stringify(
          buildChatRequestPayload(message, sessionId, provider, model, 'stream', executionOptions, attachments)
        )
      })

      const responseRequestId = response.headers.get('x-request-id') || requestId
      if (responseRequestId) {
        setCurrentRequestId(responseRequestId)
      }

      if (!response.ok) {
        isErrorLogged = true
        const err = await response.json().catch(() => ({}))
        const errorMessage = err?.detail || err?.error?.message || 'Request failed'
        
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
        throw new Error(errorMessage)
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

      while (!done) {
        const { value, done: doneReading } = await reader.read()
        done = doneReading
        if (value) {
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          // 当前 SSE 事件类型，用于区分 reasoning 和普通 chunk
          let currentEventType = ''
          for (const line of lines) {
            if (line.trim() === '') {
              currentEventType = ''
              continue
            }
            if (line.startsWith('event: ')) {
              currentEventType = line.slice(7).trim()
              continue
            }
            if (line.startsWith('data: ')) {
              const dataStr = line.slice(6)
              if (dataStr === '[DONE]') {
                break
              }
              try {
                const data = JSON.parse(dataStr)
                if (currentEventType === 'reasoning') {
                  onEvent?.({ type: 'chunk', content: '', reasoning_content: data.content || '' })
                } else if (data.type === 'chunk') {
                  onEvent?.({ type: 'chunk', content: data.content || '', reasoning_content: data.reasoning_content || '' })
                } else if (data.type === 'error') {
                  onError?.(new Error(data.error?.message || 'Stream error'))
                } else if (data?.type) {
                  onEvent?.(data)
                }
              } catch {
                logStreamParseWarning(dataStr, 'chunk')
              }
              currentEventType = ''
            }
          }
        }
      }

      if (buffer.trim()) {
        const remainingLines = buffer.trim().split('\n')
        let remainingEventType = ''
        for (const line of remainingLines) {
          if (line.startsWith('event: ')) {
            remainingEventType = line.slice(7).trim()
            continue
          }
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6)
            if (dataStr !== '[DONE]') {
              try {
                const data = JSON.parse(dataStr)
                if (remainingEventType === 'reasoning') {
                  onEvent?.({ type: 'chunk', content: '', reasoning_content: data.content || '' })
                } else if (data.type === 'chunk') {
                  onEvent?.({ type: 'chunk', content: data.content || '', reasoning_content: data.reasoning_content || '' })
                } else if (data.type === 'error') {
                  onError?.(new Error(data.error?.message || 'Stream error'))
                } else if (data?.type) {
                  onEvent?.(data)
                }
              } catch {
                logStreamParseWarning(dataStr, 'tail')
              }
            }
            remainingEventType = ''
          }
        }
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
    api.get(`/chat/history/${sessionId}`),
  confirmOperation: (confirmed: boolean, step: unknown) =>
    api.post('/chat/confirm', { confirmed, step }),
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/chat/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  /** 取消正在执行的 Agent 任务 */
  cancelSession: (sessionId: string) =>
    api.post(`/chat/cancel/${sessionId}`),

  /** 提交用户消息反馈（点赞/点踩） */
  sendFeedback: (payload: ChatFeedbackPayload) =>
    api.post('/chat/feedback', payload),

  /** 撤销 AI 执行的文件操作 */
  undoOperation: (payload: UndoOperationPayload) =>
    api.post('/chat/undo-operation', payload),
}

export const skillsAPI = {
  getAll: () => api.get('/skills'),
  getOne: (id: string) => api.get(`/skills/${id}`),
  install: (skill: ApiPayload) => api.post('/skills', skill),
  uninstall: (id: string) => api.delete(`/skills/${id}`),
  toggle: (id: string) => api.put(`/skills/${id}/toggle`),
  parseUpload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/skills/parse-upload', formData, {
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
  getAll: () => api.get('/plugins'),
  getOne: (id: string) => api.get(`/plugins/${id}`),
  discover: () => api.get('/plugins/discover'),
  install: (plugin: ApiPayload) => api.post('/plugins', plugin),
  execute: (id: string, method: string, params: Record<string, unknown> = {}) =>
    api.post(`/plugins/${id}/execute`, { method, params }),
  update: (id: string, payload: ApiPayload) => api.put(`/plugins/${id}`, payload),
  uninstall: (id: string) => api.delete(`/plugins/${id}`),
  toggle: (id: string) => api.put(`/plugins/${id}/toggle`),
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/plugins/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },
  importFromUrl: (sourceUrl: string, timeoutSeconds: number = 30) =>
    api.post('/plugins/import-url', { source_url: sourceUrl, timeout_seconds: timeoutSeconds }),
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
}

export const testRunnerAPI = {
  listScenarios: () => api.get<ScenarioListResponse>('/test-scenarios'),
  runScenario: (name: string) => api.post<ScenarioRunResponse>('/test-scenarios/run', { name }),
  runAllScenarios: () => api.post<ScenarioRunResponse>('/test-scenarios/run-all'),
}

export const memoryAPI = {
  getShortTerm: (sessionId: string) =>
    api.get(`/memory/short-term/${sessionId}`),
  addShortTerm: (sessionId: string, role: string, content: string) =>
    api.post('/memory/short-term', { session_id: sessionId, role, content }),
  deleteShortTerm: (id: number) =>
    api.delete(`/memory/short-term/${id}`),
  getLongTerm: () => api.get('/memory/long-term'),
  addLongTerm: (content: string, importance: number = 0.5) =>
    api.post('/memory/long-term', { content, importance }),
  deleteLongTerm: (id: number) =>
    api.delete(`/memory/long-term/${id}`),
  search: (query: string) => api.get(`/memory/search?query=${query}`),
}

export const promptsAPI = {
  getAll: () => api.get('/prompts'),
  getActive: () => api.get('/prompts/active'),
  getOne: (id: string) => api.get(`/prompts/${id}`),
  create: (prompt: ApiPayload) => api.post('/prompts', prompt),
  update: (id: string, prompt: ApiPayload) => api.put(`/prompts/${id}`, prompt),
  delete: (id: string) => api.delete(`/prompts/${id}`),
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
    api.get(`/behaviors/stats?days=${days}`),
  getLogs: (skip: number = 0, limit: number = 50) =>
    api.get(`/behaviors/logs?skip=${skip}&limit=${limit}`),
  logBehavior: (actionType: string, details: string) =>
    api.post('/behaviors/log', { action_type: actionType, details }),
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
}

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

export { api as sharedApi }
export default api
