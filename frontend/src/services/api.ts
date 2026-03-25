import axios from 'axios'

const API_BASE_URL = '/api'

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export const authAPI = {
  login: (username: string, password: string) => {
    const formData = new URLSearchParams()
    formData.append('username', username)
    formData.append('password', password)
    return api.post('/auth/login', formData, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    })
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

export const behaviorAPI = {
  getStats: (days: number = 7) =>
    api.get(`/behaviors/stats?days=${days}`),
  getLogs: (skip: number = 0, limit: number = 50) =>
    api.get(`/behaviors/logs?skip=${skip}&limit=${limit}`),
  logBehavior: (actionType: string, details: string) =>
    api.post('/behaviors/log', { action_type: actionType, details }),
}

export default api
