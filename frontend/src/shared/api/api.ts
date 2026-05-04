import axios from 'axios'
import { appLogger, generateRequestId, setCurrentRequestId } from '@/shared/utils/logger'

const API_BASE_URL = '/api'

const CSRF_EXEMPT_PATHS = new Set(['/auth/login', '/auth/register'])
const CSRF_TOKEN_ENDPOINT = `${API_BASE_URL}/auth/csrf-token`

let csrfTokenValue = ''
let csrfTokenPromise: Promise<void> | null = null

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

const isExpectedApiError = (error: unknown): boolean => {
  const normalizedUrl = String((error as { config?: { url?: string } })?.config?.url || '').split('?')[0]
  const statusCode = (error as { response?: { status?: number } })?.response?.status

  return (
    (normalizedUrl === '/auth/me' && statusCode === 401) ||
    (normalizedUrl === '/auth/login' && statusCode === 401) ||
    (normalizedUrl === '/auth/register' && statusCode === 400) ||
    (statusCode === 404 && normalizedUrl.startsWith('/chat/history/'))
  )
}

export const getApiErrorDetail = (error: unknown): string => {
  const err = error as any
  return err?.response?.data?.error?.message || err?.response?.data?.detail || err?.message || '未知错误'
}

const fetchCsrfToken = async (): Promise<string> => {
  try {
    const response = await fetch(CSRF_TOKEN_ENDPOINT, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' },
    })
    if (!response.ok) {
      throw new Error(`csrf token fetch failed: ${response.status}`)
    }
    const data = await response.json()
    csrfTokenValue = data.csrf_token || ''
    return csrfTokenValue
  } catch (error) {
    appLogger.warning({
      event: 'csrf_token_fetch_failed',
      module: 'api',
      action: 'BOOTSTRAP',
      status: 'warning',
      message: 'csrf token fetch failed',
      extra: {
        error: error instanceof Error ? error.message : String(error),
      },
    })
    return ''
  }
}

const ensureCsrfToken = async (): Promise<string> => {
  if (csrfTokenValue) {
    return csrfTokenValue
  }

  if (!csrfTokenPromise) {
    csrfTokenPromise = fetchCsrfToken().then(() => {}).finally(() => {
      csrfTokenPromise = null
    })
  }

  await csrfTokenPromise
  return csrfTokenValue
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
  (error) => {
    const responseRequestId = String(error?.response?.headers?.['x-request-id'] || '')
    if (responseRequestId) {
      setCurrentRequestId(responseRequestId)
    }

    if (!isExpectedApiError(error)) {
      const errorUrl = error?.config?.url || 'unknown'
      const errorStatus = error?.response?.status || 0
      const errorMessage = error?.message || ''
      const backendDetail = getApiErrorDetail(error)

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

export interface ChatAttachmentPayload {
  type: string
  data: string
  mime_type: string
  file_name?: string
}

export interface ChatExecutionOptions {
  thinking_enabled?: boolean
  thinking_depth?: number
  max_tool_call_rounds?: number
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
  ) => {
    const body: Record<string, unknown> = { message, session_id: sessionId, provider, model, mode }
    if (executionOptions?.thinking_enabled) {
      body.thinking_enabled = true
      body.thinking_depth = executionOptions.thinking_depth ?? 0
    }
    if (typeof executionOptions?.max_tool_call_rounds === 'number') {
      body.max_tool_call_rounds = executionOptions.max_tool_call_rounds
    }
    if (attachments && attachments.length > 0) {
      body.attachments = attachments
    }
    return api.post('/chat', body, { signal: requestOptions?.signal })
  },
  sendMessageStream: async (
    message: string,
    sessionId: string = 'default',
    provider?: string,
    model?: string,
    onEvent?: (event: Record<string, any>) => void,
    onError?: (error: any) => void,
    requestOptions?: { signal?: AbortSignal },
    executionOptions?: ChatExecutionOptions,
    attachments?: ChatAttachmentPayload[]
  ) => {
    const MAX_RETRIES = 3
    const RETRY_DELAYS = [1000, 2000, 4000]
    let lastError: Error | null = null
    let hasReceivedData = false

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      let isErrorLogged = false
      const url = '/api/chat'
      const requestId = generateRequestId()
      setCurrentRequestId(requestId)

      if (attempt > 0) {
        const delayMs = RETRY_DELAYS[attempt - 1]
        appLogger.warning({
          event: 'api_retry',
          module: 'api',
          action: 'POST',
          status: 'retry',
          request_id: requestId,
          message: `retrying stream request (attempt ${attempt + 1}/${MAX_RETRIES + 1})`,
          extra: { url, delay_ms: delayMs },
        })
        await new Promise(resolve => setTimeout(resolve, delayMs))
      }

      try {
        const csrfToken = await ensureCsrfToken()
        const headers: Record<string, string> = {
          'Accept': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Content-Type': 'application/json',
          'X-Request-Id': requestId,
          'X-CSRF-Token': csrfToken,
        }

        const streamBody: Record<string, unknown> = {
          message,
          session_id: sessionId,
          provider,
          model,
          mode: 'stream',
        }
        if (executionOptions?.thinking_enabled) {
          streamBody.thinking_enabled = true
          streamBody.thinking_depth = executionOptions.thinking_depth ?? 0
        }
        if (typeof executionOptions?.max_tool_call_rounds === 'number') {
          streamBody.max_tool_call_rounds = executionOptions.max_tool_call_rounds
        }
        if (attachments && attachments.length > 0) {
          streamBody.attachments = attachments
        }

        const response = await fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          headers,
          signal: requestOptions?.signal,
          body: JSON.stringify(streamBody)
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

            let currentEventType = ''
            for (const line of lines) {
              const normalizedLine = line.replace(/\r$/, '')
              if (normalizedLine.trim() === '') {
                currentEventType = ''
                continue
              }
              if (normalizedLine.startsWith('event: ')) {
                currentEventType = normalizedLine.slice(7).trim()
                continue
              }
              if (normalizedLine.startsWith('data: ')) {
                const dataStr = normalizedLine.slice(6)
                if (dataStr === '[DONE]') {
                  break
                }
                try {
                  const data = JSON.parse(dataStr)
                  hasReceivedData = true
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
            const normalizedLine = line.replace(/\r$/, '')
            if (normalizedLine.startsWith('event: ')) {
              remainingEventType = normalizedLine.slice(7).trim()
              continue
            }
            if (normalizedLine.startsWith('data: ')) {
              const dataStr = normalizedLine.slice(6)
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

        return
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') {
          throw e
        }
        lastError = e instanceof Error ? e : new Error(String(e))
        if (hasReceivedData) {
          if (!isErrorLogged) {
            appLogger.error({
              event: 'api_response',
              module: 'api',
              action: 'POST',
              status: 'failure',
              request_id: requestId,
              message: 'stream connection lost after partial data received',
              extra: { url, error: lastError.message },
            })
          }
          onError?.(lastError)
          throw lastError
        }
        if (!isErrorLogged) {
          appLogger.warning({
            event: 'api_retry',
            module: 'api',
            action: 'POST',
            status: 'retry',
            request_id: requestId,
            message: `stream attempt ${attempt + 1} failed, scheduling retry`,
            extra: { url, error: lastError.message },
          })
        }
      }
    }

    appLogger.error({
      event: 'api_response',
      module: 'api',
      action: 'POST',
      status: 'failure',
      request_id: '',
      message: 'stream request failed after all retries',
      extra: { error: lastError?.message },
    })
    onError?.(lastError)
    throw lastError || new Error('Stream request failed after max retries')
  },
  getHistory: (sessionId: string) =>
    api.get(`/chat/history/${sessionId}`),
  confirmOperation: (confirmed: boolean, step: any) =>
    api.post('/chat/confirm', { confirmed, step }),
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/chat/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}

export const skillsAPI = {
  getAll: () => api.get('/skills'),
  getOne: (id: string) => api.get(`/skills/${id}`),
  install: (skill: any) => api.post('/skills', skill),
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
  install: (plugin: any) => api.post('/plugins', plugin),
  execute: (id: string, method: string, params: Record<string, unknown> = {}) =>
    api.post(`/plugins/${id}/execute`, { method, params }),
  update: (id: string, payload: any) => api.put(`/plugins/${id}`, payload),
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
  create: (prompt: any) => api.post('/prompts', prompt),
  update: (id: string, prompt: any) => api.put(`/prompts/${id}`, prompt),
  delete: (id: string) => api.delete(`/prompts/${id}`),
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
  is_daily: boolean
  cron_expression: string | null
  weekdays: string | null
  daily_time: string | null
  task_type: string
  plugin_name: string | null
  command_name: string | null
  command_params: Record<string, unknown>
  next_execution_at: string | null
  last_error_message: string | null
  task_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  completed_at: string | null
  cancelled_at: string | null
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
  prompt?: string
  scheduled_at: string
  provider?: string | null
  model?: string | null
  is_daily?: boolean
  cron_expression?: string | null
  weekdays?: string | null
  daily_time?: string | null
  task_type?: string
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
  is_daily?: boolean
  cron_expression?: string | null
  weekdays?: string | null
  daily_time?: string | null
  task_type?: string
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

export interface ModelCapabilities {
  provider: string
  model: string
  supports_vision: boolean
  is_multimodal: boolean
  supports_temperature: boolean
  supports_top_k: boolean
  model_spec: Record<string, unknown>
}

export const modelAPI = {
  getCapabilities: (provider: string, model: string) =>
    api.get<ModelCapabilities>(`/api/models/${provider}/${model}/capabilities`),
}

export interface UserProfile {
  user_id: string
  username: string
  nickname: string | null
  avatar_url: string | null
  email: string | null
  phone: string | null
  profile: Record<string, unknown>
}

export interface LoginDeviceItem {
  id: number
  device_type: string
  ip_address: string | null
  user_agent: string | null
  logged_in_at: string
  last_active_at: string
  is_online: boolean
  is_current: boolean
}

export const userAPI = {
  getProfile: () => api.get<UserProfile>('/user/profile'),
  updateProfile: (data: { nickname?: string; email?: string; phone?: string }) =>
    api.put<{ message: string }>('/user/profile', data),
  uploadAvatar: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<{ avatar_url: string; message: string }>('/user/avatar', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  getDevices: () => api.get<LoginDeviceItem[]>('/user/devices'),
  revokeDevice: (deviceId: number) =>
    api.post<{ message: string }>(`/user/devices/${deviceId}/revoke`),
}

export const passwordAPI = {
  change: (oldPassword: string, newPassword: string, confirmPassword: string) =>
    api.put<{ message: string }>('/auth/me/password', {
      old_password: oldPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),
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

export interface ConversationSessionItem {
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

export interface ConversationSessionListResponse {
  items: ConversationSessionItem[]
  total: number
  page: number
  page_size: number
  has_more: boolean
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
  listSessions: (params?: {
    search?: string
    sort_by?: 'title' | 'created_at' | 'updated_at' | 'last_message_at' | 'message_count'
    sort_order?: 'asc' | 'desc'
    page?: number
    page_size?: number
    include_deleted?: boolean
  }) => api.get<ConversationSessionListResponse>('/conversations', { params }),
  createSession: (payload?: { title?: string; session_id?: string }) =>
    api.post<ConversationSessionItem>('/conversations', payload || {}),
  renameSession: (sessionId: string, title: string) =>
    api.patch<ConversationSessionItem>(`/conversations/${sessionId}`, { title }),
  deleteSession: (sessionId: string, retentionDays: number = 30) =>
    api.delete<ConversationSessionItem>(`/conversations/${sessionId}`, { params: { retention_days: retentionDays } }),
  restoreSession: (sessionId: string) =>
    api.post<ConversationSessionItem>(`/conversations/${sessionId}/restore`),
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
}

export interface WeixinParamsUpdate {
  bot_type?: string
  channel_version?: string
  base_url?: string
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
}

export interface WeixinAutoReplyRule {
  id: number
  user_id: string
  rule_name: string
  match_type: 'keyword' | 'regex'
  match_pattern: string
  reply_content: string
  is_active: boolean
  priority: number
  created_at: string
  updated_at: string
}

export interface WeixinAutoReplyRuleCreate {
  rule_name: string
  match_type: 'keyword' | 'regex'
  match_pattern: string
  reply_content: string
  is_active?: boolean
  priority?: number
}

export interface WeixinAutoReplyRuleUpdate {
  rule_name?: string
  match_type?: 'keyword' | 'regex'
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
  createRule: (data: WeixinAutoReplyRuleCreate) => api.post<WeixinAutoReplyRule>('/weixin/auto-reply/rules', data),
  updateRule: (id: number, data: WeixinAutoReplyRuleUpdate) => api.put<WeixinAutoReplyRule>(`/weixin/auto-reply/rules/${id}`, data),
  deleteRule: (id: number) => api.delete(`/weixin/auto-reply/rules/${id}`),
}

// ---- 系统诊断API类型 ----

export interface SysDiagnosticsCheck {
  name: string
  label: string
  ok: boolean
  detail: Record<string, unknown> | null
}

export interface SysDiagnosticsResponse {
  timestamp: number
  overall: string
  passed: number
  total: number
  checks: SysDiagnosticsCheck[]
}

export const systemAPI = {
  diagnostics: () => api.get<SysDiagnosticsResponse>("/system/diagnostics"),
  ping: () => api.get<{ pong: boolean; timestamp: number }>("/system/ping"),
}

// ---- 测试场景API类型 ----

export interface ScenarioDef {
  name: string
  label: string
  category: string
  description: string
}

export interface ScenarioResult {
  name: string
  label: string
  category: string
  status: 'idle' | 'ok' | 'fail'
  duration_ms: number
  message: string
  detail: Record<string, unknown> | null
}

export interface ScenarioRunResponse {
  results: ScenarioResult[]
  passed: number
  failed: number
  total: number
  duration_ms: number
}

export const testRunnerAPI = {
  listScenarios: () => api.get<{ total: number; scenarios: ScenarioDef[] }>('/test-scenarios'),
  runScenario: (name: string) => api.post<ScenarioRunResponse>('/test-scenarios/run', { name }),
  runAllScenarios: () => api.post<ScenarioRunResponse>('/test-scenarios/run-all'),
}

export { api as sharedApi }
export default api
