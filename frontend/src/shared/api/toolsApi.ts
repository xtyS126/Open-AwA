/**
 * Agent工具API模块 - 提供文件操作、终端执行、网页搜索等工具的前端接口。
 */

import { sharedApi } from '@/shared/api/api'

const TOOLS_API_BASE_URL = '/tools'
const SUBAGENT_API_BASE_URL = '/subagents'

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
  listTools: () => sharedApi.get<{ tools: Record<string, ToolInfo>; count: number }>(`${TOOLS_API_BASE_URL}/list`),

  /* 文件操作 */
  fileRead: (path: string) => sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/file/read`, { path }),
  fileWrite: (path: string, content: string) => sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/file/write`, { path, content }),
  fileList: (path: string, pattern?: string) =>
    sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/file/list`, { path, pattern: pattern || '*' }),
  fileDelete: (path: string) => sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/file/delete`, { path }),
  fileExists: (path: string) => sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/file/exists`, { path }),

  /* 终端操作 */
  terminalRun: (command: string, working_dir?: string, timeout?: number) =>
    sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/terminal/run`, { command, working_dir, timeout: timeout || 30 }),
  terminalStatus: () => sharedApi.get<ToolResponse>(`${TOOLS_API_BASE_URL}/terminal/status`),

  /* 网页搜索（联网） */
  webSearch: (query: string, max_results?: number) =>
    sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/search/web`, { query, max_results: max_results || 10 }),
  fetchUrl: (url: string, max_length?: number) =>
    sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/search/fetch`, { url, max_length: max_length || 10000 }),

  /* 本地搜索（离线） */
  localSearch: (query: string, max_results?: number, mode?: string) =>
    sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/search/local`, {
      query,
      max_results: max_results || 20,
      mode: mode || 'tfidf',
    }),
  indexDocument: (id: string, title: string, content: string, url?: string) =>
    sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/search/index`, { id, title, url: url || '', content }),
  indexDirectory: (directory: string, pattern?: string) =>
    sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/search/index-directory`, {
      directory,
      pattern: pattern || '*.html,*.htm,*.txt,*.md',
    }),
  removeDocument: (id: string) =>
    sharedApi.post<ToolResponse>(`${TOOLS_API_BASE_URL}/search/remove`, { id }),
  searchStats: () =>
    sharedApi.get<ToolResponse>(`${TOOLS_API_BASE_URL}/search/stats`),
}

/* 子Agent API */
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
  listAgents: () => sharedApi.get<{ agents: SubAgentInfo[]; count: number }>(`${SUBAGENT_API_BASE_URL}/agents`),
  listGraphs: () => sharedApi.get<{ graphs: GraphInfo[]; count: number }>(`${SUBAGENT_API_BASE_URL}/graphs`),
  getGraph: (name: string) => sharedApi.get<GraphInfo>(`${SUBAGENT_API_BASE_URL}/graphs/${name}`),
  runGraph: (graph_name: string, context?: Record<string, unknown>, messages?: { role: string; content: string }[]) =>
    sharedApi.post<GraphExecutionResult>(`${SUBAGENT_API_BASE_URL}/run/graph`, {
      graph_name,
      context: context || {},
      messages: messages || [],
    }),
  runSequential: (agent_names: string[], context?: Record<string, unknown>) =>
    sharedApi.post<GraphExecutionResult>(`${SUBAGENT_API_BASE_URL}/run/sequential`, {
      agent_names,
      context: context || {},
    }),
  runParallel: (agent_names: string[], context?: Record<string, unknown>, timeout?: number) =>
    sharedApi.post<GraphExecutionResult>(`${SUBAGENT_API_BASE_URL}/run/parallel`, {
      agent_names,
      context: context || {},
      timeout: timeout || 120,
    }),
}
