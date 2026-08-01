/**
 * 运维 API 模块。封装行为日志查询、系统信息、测试运行端点。自 api.ts 拆分而来。
 */
import { api } from './client'

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
