import axios from 'axios'
import Cookies from 'js-cookie'
import { appLogger, generateRequestId, setCurrentRequestId } from '@/shared/utils/logger'

const API_BASE_URL = '/api'

const CSRF_EXEMPT_PATHS = new Set(['/auth/login', '/auth/register'])
const CSRF_BOOTSTRAP_PATH = `${API_BASE_URL}/auth/me`

export const getCsrfToken = (): string => Cookies.get('csrf_token') || ''

let csrfBootstrapPromise: Promise<string> | null = null

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
  const csrfToken = getCsrfToken()
  if (csrfToken) {
    return csrfToken
  }

  appLogger.warning({
    event: 'csrf_token_missing',
    module: 'api',
    action: 'BOOTSTRAP',
    status: 'warning',
    message: 'csrf token missing before mutating request, trying bootstrap request',
    extra: {
      bootstrap_path: CSRF_BOOTSTRAP_PATH,
    },
  })

  if (!csrfBootstrapPromise) {
    csrfBootstrapPromise = (async () => {
      try {
        await fetch(CSRF_BOOTSTRAP_PATH, {
          method: 'GET',
          credentials: 'same-origin',
        })
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

      const refreshedToken = getCsrfToken()
      if (!refreshedToken) {
        throw new Error('CSRF token missing after bootstrap request')
      }
      return refreshedToken
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
  (error) => {
    const responseRequestId = String(error?.response?.headers?.['x-request-id'] || '')
    if (responseRequestId) {
      setCurrentRequestId(responseRequestId)
    }
    
    const isExpectedAuthError = (
      (error?.config?.url === '/auth/me' && error?.response?.status === 401) ||
      (error?.config?.url === '/auth/register' && error?.response?.status === 400)
    );

    if (!isExpectedAuthError) {
      appLogger.error({
        event: 'api_response',
        module: 'api',
        action: error?.config?.method?.toUpperCase() || 'GET',
        status: 'failure',
        request_id: responseRequestId,
        message: 'api request failed',
        extra: {
          url: error?.config?.url,
          status_code: error?.response?.status,
          error: error?.message,
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

export const chatAPI = {
  sendMessage: (
    message: string,
    sessionId: string = 'default',
    provider?: string,
    model?: string,
    mode: 'stream' | 'direct' = 'direct',
    requestOptions?: { signal?: AbortSignal }
  ) =>
    api.post('/chat', { message, session_id: sessionId, provider, model, mode }, { signal: requestOptions?.signal }),
  sendMessageStream: async (
    message: string,
    sessionId: string = 'default',
    provider?: string,
    model?: string,
    onChunk?: (content: string, reasoning: string) => void,
    onError?: (error: any) => void,
    requestOptions?: { signal?: AbortSignal }
  ) => {
    let isErrorLogged = false
    const url = '/api/chat'
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
        body: JSON.stringify({
          message,
          session_id: sessionId,
          provider,
          model,
          mode: 'stream'
        })
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
                  // reasoning 事件仅携带推理内容
                  onChunk?.('', data.content || '')
                } else if (data.type === 'chunk') {
                  onChunk?.(data.content || '', data.reasoning_content || '')
                } else if (data.type === 'error') {
                  onError?.(new Error(data.error?.message || 'Stream error'))
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
                  onChunk?.('', data.content || '')
                } else if (data.type === 'chunk') {
                  onChunk?.(data.content || '', data.reasoning_content || '')
                } else if (data.type === 'error') {
                  onError?.(new Error(data.error?.message || 'Stream error'))
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
  prompt: string
  scheduled_at: string
  provider?: string | null
  model?: string | null
}

export interface ScheduledTaskUpdatePayload {
  title?: string
  prompt?: string
  scheduled_at?: string
  provider?: string | null
  model?: string | null
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
}

export { api as sharedApi }
export default api
