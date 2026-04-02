import axios from 'axios'

const API_BASE_URL = '/api'

const getStoredToken = () => localStorage.getItem('token')

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const token = getStoredToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

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

export const chatAPI = {
  sendMessage: (
    message: string,
    sessionId: string = 'default',
    provider?: string,
    model?: string
  ) =>
    api.post('/chat', { message, session_id: sessionId, provider, model }),
  getHistory: (sessionId: string) =>
    api.get(`/chat/history/${sessionId}`),
  confirmOperation: (confirmed: boolean, step: any) =>
    api.post('/chat/confirm', { confirmed, step }),
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

export const pluginsAPI = {
  getAll: () => api.get('/plugins'),
  getOne: (id: string) => api.get(`/plugins/${id}`),
  install: (plugin: any) => api.post('/plugins', plugin),
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

export type WeixinQrStatus = 'idle' | 'wait' | 'scaned' | 'scaned_but_redirect' | 'expired' | 'confirmed'

export interface WeixinQrStartResponse {
  message: string
  session_key: string
  status: Exclude<WeixinQrStatus, 'idle' | 'scaned_but_redirect' | 'expired' | 'confirmed'> | 'wait'
  qrcode?: string
  qrcode_url?: string
}

export interface WeixinQrWaitRequest {
  session_key: string
  timeout_seconds?: number
  qrcode?: string
  base_url?: string
}

export interface WeixinQrWaitResponse {
  connected: boolean
  session_key: string
  status: Exclude<WeixinQrStatus, 'idle'>
  message: string
  qrcode_url?: string
  auth_id?: string
  ticket?: string
  hint?: string
  account_id?: string
  token?: string
  base_url?: string
  redirect_host?: string
  user_id?: string
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

export const weixinAPI = {
  getConfig: () => api.get<WeixinConfig>('/skills/weixin/config'),
  saveConfig: (config: WeixinConfig) => api.post('/skills/weixin/config', config),
  healthCheck: (config: WeixinConfig) => api.post<WeixinHealthCheckResult>('/skills/weixin/health-check', config),
  startQrLogin: (payload: WeixinQrStartRequest = {}) => api.post<WeixinQrStartResponse>('/skills/weixin/qr/start', payload),
  waitQrLogin: (payload: WeixinQrWaitRequest) => api.post<WeixinQrWaitResponse>('/skills/weixin/qr/wait', payload),
  exitQrLogin: (payload: WeixinQrExitRequest) => api.post<WeixinQrExitResponse>('/skills/weixin/qr/exit', payload),
}

export default api
