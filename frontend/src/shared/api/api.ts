import axios from 'axios'
import { appLogger, generateRequestId, setCurrentRequestId } from '@/shared/utils/logger'

const API_BASE_URL = '/api'

const getStoredToken = () => localStorage.getItem('token')

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const requestId = generateRequestId()
  config.headers['X-Request-Id'] = requestId
  setCurrentRequestId(requestId)

  const token = getStoredToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
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
}

export interface ChatConfirmRequest {
  confirmed: boolean
  step: {
    id: string
    action: string
    params: Record<string, unknown>
  }
}

export const chatAPI = {
  sendMessage: (
    message: string,
    sessionId: string = 'default',
    provider?: string,
    model?: string,
    mode: 'stream' | 'direct' = 'direct'
  ) =>
    api.post('/chat', { message, session_id: sessionId, provider, model, mode }),
  sendMessageStream: async (
    message: string,
    sessionId: string = 'default',
    provider?: string,
    model?: string,
    onChunk?: (content: string, reasoning: string) => void,
    onError?: (error: Error) => void
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
      const token = localStorage.getItem('token')
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'X-Request-Id': requestId,
      }
      if (token) {
        headers['Authorization'] = `Bearer ${token}`
      }

      const response = await fetch(url, {
        method: 'POST',
        headers,
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

          for (const line of lines) {
            if (line.trim() === '') continue
            if (line.startsWith('data: ')) {
              const dataStr = line.slice(6)
              if (dataStr === '[DONE]') {
                break
              }
              try {
                const data = JSON.parse(dataStr)
                if (data.type === 'chunk') {
                  onChunk?.(data.content || '', data.reasoning_content || '')
                } else if (data.type === 'error') {
                  onError?.(new Error(data.error?.message || 'Stream error'))
                }
              } catch (e) {
                // Ignore parse errors for incomplete chunks
              }
            }
          }
        }
      }

      if (buffer.trim()) {
        const line = buffer.trim()
        if (line.startsWith('data: ')) {
          const dataStr = line.slice(6)
          if (dataStr !== '[DONE]') {
            try {
              const data = JSON.parse(dataStr)
              if (data.type === 'chunk') {
                onChunk?.(data.content || '', data.reasoning_content || '')
              } else if (data.type === 'error') {
                onError?.(new Error(data.error?.message || 'Stream error'))
              }
            } catch (e) {
              // Ignore
            }
          }
        }
      }
    } catch (e) {
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
  confirmOperation: (confirmed: boolean, step: ChatConfirmRequest['step']) =>
    api.post('/chat/confirm', { confirmed, step }),
}

export interface SkillRequest {
  name: string
  description?: string
  config?: Record<string, unknown>
  enabled?: boolean
}

export interface SkillResponse {
  id: string
  name: string
  description: string
  config: Record<string, unknown>
  enabled: boolean
  created_at: string
  updated_at: string
}

export const skillsAPI = {
  getAll: () => api.get<SkillResponse[]>('/skills'),
  getOne: (id: string) => api.get<SkillResponse>(`/skills/${id}`),
  install: (skill: SkillRequest) => api.post<SkillResponse>('/skills', skill),
  uninstall: (id: string) => api.delete(`/skills/${id}`),
  toggle: (id: string) => api.put<SkillResponse>(`/skills/${id}/toggle`),
  parseUpload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<SkillResponse>('/skills/parse-upload', formData, {
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

export interface PluginRequest {
  name: string
  description?: string
  version?: string
  config?: Record<string, unknown>
  enabled?: boolean
}

export interface PluginResponse {
  id: string
  name: string
  description: string
  version: string
  config: Record<string, unknown>
  enabled: boolean
  category?: string
  author?: string
  source?: string
  dependencies?: string[]
  installed_at?: string
  created_at: string
  updated_at: string
}

export const pluginsAPI = {
  getAll: () => api.get<PluginResponse[]>('/plugins'),
  getOne: (id: string) => api.get<PluginResponse>(`/plugins/${id}`),
  install: (plugin: PluginRequest) => api.post<PluginResponse>('/plugins', plugin),
  uninstall: (id: string) => api.delete(`/plugins/${id}`),
  toggle: (id: string) => api.put<PluginResponse>(`/plugins/${id}/toggle`),
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<PluginResponse>('/plugins/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },
  getPermissions: (id: string) => api.get<PluginPermissionStatus>(`/plugins/${id}/permissions`),
  authorizePermissions: (id: string, permissions: string[]) =>
    api.post<PluginPermissionUpdateResponse>(`/plugins/${id}/permissions/authorize`, { permissions }),
  revokePermissions: (id: string, permissions: string[]) =>
    api.post<PluginPermissionUpdateResponse>(`/plugins/${id}/permissions/revoke`, { permissions }),
  getLogs: (id: string, level?: string, limit = 100, offset = 0) =>
    api.get<PluginLogsResponse>(`/plugins/${id}/logs`, { params: { level, limit, offset } }),
  setLogLevel: (id: string, level: string) =>
    api.put<PluginLogLevelResponse>(`/plugins/${id}/log-level`, { level }),
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

export interface PromptRequest {
  name: string
  content: string
  is_active?: boolean
}

export interface PromptResponse {
  id: string
  name: string
  content: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export const promptsAPI = {
  getAll: () => api.get<PromptResponse[]>('/prompts'),
  getActive: () => api.get<PromptResponse>('/prompts/active'),
  getOne: (id: string) => api.get<PromptResponse>(`/prompts/${id}`),
  create: (prompt: PromptRequest) => api.post<PromptResponse>('/prompts', prompt),
  update: (id: string, prompt: PromptRequest) => api.put<PromptResponse>(`/prompts/${id}`, prompt),
  delete: (id: string) => api.delete(`/prompts/${id}`),
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

export interface WeixinSendMessageRequest {
  to_user_id: string
  text: string
  account_id?: string
  context_token?: string
}

export interface WeixinSendMessageResponse {
  success: boolean
  message_id?: string
  error?: string | null
}

export interface WeixinTaskCreateRequest {
  task_type: string
  params: Record<string, unknown>
  account_id?: string
}

export interface WeixinTaskCreateResponse {
  task_id: string
  status: string
}

export interface WeixinTaskStatusResponse {
  task_id: string
  status: string
  progress: number
  result?: Record<string, unknown> | null
  error?: string | null
}

export interface WeixinMonitorStatus {
  account_id: string
  state: string
  running: boolean
  paused: boolean
  consecutive_failures: number
  total_messages: number
  last_message_at?: number | null
  last_error?: string | null
  last_error_at?: number | null
  started_at?: number | null
  circuit_breaker_state: string
  session_paused: boolean
  session_remaining_seconds: number
}

export interface WeixinMonitorStatusResponse {
  monitors: Record<string, WeixinMonitorStatus | Record<string, never>>
}

export const weixinAPI = {
  getConfig: () => api.get<WeixinConfig>('/skills/weixin/config'),
  saveConfig: (config: WeixinConfig) => api.post('/skills/weixin/config', config),
  healthCheck: (config: WeixinConfig) => api.post<WeixinHealthCheckResult>('/skills/weixin/health-check', config),
  startQrLogin: (payload: WeixinQrStartRequest = {}) => api.post<WeixinQrStartResponse>('/skills/weixin/qr/start', payload),
  waitQrLogin: (payload: WeixinQrWaitRequest) => api.post<WeixinQrWaitResponse>('/skills/weixin/qr/wait', payload),
  exitQrLogin: (payload: WeixinQrExitRequest) => api.post<WeixinQrExitResponse>('/skills/weixin/qr/exit', payload),
  sendMessage: (payload: WeixinSendMessageRequest) =>
    api.post<WeixinSendMessageResponse>('/skills/weixin/message', payload),
  createTask: (payload: WeixinTaskCreateRequest) =>
    api.post<WeixinTaskCreateResponse>('/skills/weixin/task', payload),
  getTaskStatus: (taskId: string) =>
    api.get<WeixinTaskStatusResponse>(`/skills/weixin/task/${taskId}`),
  startMonitor: (payload: { account_id?: string } = {}) =>
    api.post<{ success: boolean; status: WeixinMonitorStatus }>('/skills/weixin/monitor/start', payload),
  stopMonitor: (payload: { account_id?: string } = {}) =>
    api.post<{ success: boolean }>('/skills/weixin/monitor/stop', payload),
  getMonitorStatus: (accountId?: string) =>
    api.get<WeixinMonitorStatusResponse>('/skills/weixin/monitor/status', {
      params: accountId ? { account_id: accountId } : {},
    }),
}

export default api
