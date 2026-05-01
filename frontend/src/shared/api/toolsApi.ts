/**
 * Agent工具API模块 - 提供文件操作、终端执行、网页搜索等工具的前端接口。
 */

import axios from 'axios'

const api = axios.create({
  baseURL: '/api/tools',
  timeout: 30000,
  withCredentials: true
})

/* 请求拦截器: CSRF token */
api.interceptors.request.use(config => {
  const csrfToken = document.cookie
    .split('; ')
    .find(row => row.startsWith('csrf_token='))
    ?.split('=')[1]
  if (csrfToken) {
    config.headers['X-CSRF-Token'] = csrfToken
  }
  return config
})

/* 类型定义 */
export interface ToolInfo {
  name: string
  display_name: string
  description: string
  version: string
  status: string
  tools: ToolDefinition[]
}

export interface ToolDefinition {
  name: string
  description: string
  parameters: {
    type: string
    properties: Record<string, { type: string; description: string }>
    required?: string[]
  }
}

export interface ToolResponse {
  success: boolean
  data?: Record<string, unknown>
  error?: string
}

/* 工具列表 */
export const toolsAPI = {
  /* 获取所有可用工具 */
  listTools: () => api.get<{ tools: Record<string, ToolInfo>; count: number }>('/list'),

  /* 文件操作 */
  fileRead: (path: string) => api.post<ToolResponse>('/file/read', { path }),
  fileWrite: (path: string, content: string) => api.post<ToolResponse>('/file/write', { path, content }),
  fileList: (path: string, pattern?: string) => api.post<ToolResponse>('/file/list', { path, pattern: pattern || '*' }),
  fileDelete: (path: string) => api.post<ToolResponse>('/file/delete', { path }),
  fileExists: (path: string) => api.post<ToolResponse>('/file/exists', { path }),

  /* 终端操作 */
  terminalRun: (command: string, working_dir?: string, timeout?: number) =>
    api.post<ToolResponse>('/terminal/run', { command, working_dir, timeout: timeout || 30 }),
  terminalStatus: () => api.get<ToolResponse>('/terminal/status'),

  /* 网页搜索（联网） */
  webSearch: (query: string, max_results?: number) =>
    api.post<ToolResponse>('/search/web', { query, max_results: max_results || 10 }),
  fetchUrl: (url: string, max_length?: number) =>
    api.post<ToolResponse>('/search/fetch', { url, max_length: max_length || 10000 }),

  /* 本地搜索（离线） */
  localSearch: (query: string, max_results?: number, mode?: string) =>
    api.post<ToolResponse>('/search/local', {
      query,
      max_results: max_results || 20,
      mode: mode || 'tfidf',
    }),
  indexDocument: (id: string, title: string, content: string, url?: string) =>
    api.post<ToolResponse>('/search/index', { id, title, url: url || '', content }),
  indexDirectory: (directory: string, pattern?: string) =>
    api.post<ToolResponse>('/search/index-directory', {
      directory,
      pattern: pattern || '*.html,*.htm,*.txt,*.md',
    }),
  removeDocument: (id: string) =>
    api.post<ToolResponse>('/search/remove', { id }),
  searchStats: () =>
    api.get<ToolResponse>('/search/stats'),
}

/* 子Agent API */
const subagentApi = axios.create({
  baseURL: '/api/subagents',
  timeout: 120000,
  withCredentials: true
})

subagentApi.interceptors.request.use(config => {
  const csrfToken = document.cookie
    .split('; ')
    .find(row => row.startsWith('csrf_token='))
    ?.split('=')[1]
  if (csrfToken) {
    config.headers['X-CSRF-Token'] = csrfToken
  }
  return config
})

export interface SubAgentInfo {
  name: string
  description: string
  capabilities: string[]
  registered_at: number
}

export interface GraphInfo {
  name: string
  description: string
  nodes: { name: string; description: string; timeout: number; retry_count: number }[]
  edges: { source: string; target: string; conditional: boolean }[]
  entry_point: string
  finish_points: string[]
}

export interface GraphExecutionResult {
  success: boolean
  results: Record<string, unknown>
  messages: { role: string; content: string }[]
  errors: Record<string, string>
  metadata: Record<string, unknown>
  execution_log?: { node: string; status: string; duration_ms?: number; error?: string }[]
}

export const subagentAPI = {
  listAgents: () => subagentApi.get<{ agents: SubAgentInfo[]; count: number }>('/agents'),
  listGraphs: () => subagentApi.get<{ graphs: GraphInfo[]; count: number }>('/graphs'),
  getGraph: (name: string) => subagentApi.get<GraphInfo>(`/graphs/${name}`),
  runGraph: (graph_name: string, context?: Record<string, unknown>, messages?: { role: string; content: string }[]) =>
    subagentApi.post<GraphExecutionResult>('/run/graph', { graph_name, context: context || {}, messages: messages || [] }),
  runSequential: (agent_names: string[], context?: Record<string, unknown>) =>
    subagentApi.post<GraphExecutionResult>('/run/sequential', { agent_names, context: context || {} }),
  runParallel: (agent_names: string[], context?: Record<string, unknown>, timeout?: number) =>
    subagentApi.post<GraphExecutionResult>('/run/parallel', { agent_names, context: context || {}, timeout: timeout || 120 }),
}
