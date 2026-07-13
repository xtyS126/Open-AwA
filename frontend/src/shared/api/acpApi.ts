/**
 * ACP（Agent Client Protocol）API 模块。
 * 封装与后端 ACP 端点的交互，用于通过 stdio JSON-RPC 调用
 * Claude Code、Codex、OpenClaw、OpenCode 等 vibe coding 应用。
 *
 * 注意：SSE 流式 prompt 端点（POST /acp/sessions/{id}/prompt）不在此封装，
 * 由组件直接用 fetch 订阅，参考 chatAPI.sendMessageStream 的实现模式。
 */
import api from '@/shared/api/api'

const BASE = '/acp'

/** ACP Agent 描述 */
export interface AcpAgent {
  /** Agent 唯一标识 */
  id: string
  /** 显示名称 */
  name: string
  /** 启动命令 */
  command: string
  /** 是否在数据库中启用 */
  enabled: boolean
  /** 是否在本机可用（已安装且可执行） */
  available: boolean
}

/** ACP 会话信息 */
export interface AcpSession {
  /** 会话 ID */
  session_id: string
  /** 关联的 Agent 名称 */
  agent: string
  /** 工作目录 */
  cwd: string
  /** 创建时间（ISO 字符串） */
  created_at: string
}

/** 创建会话响应 */
export interface AcpCreateSessionResponse {
  session_id: string
  cwd: string
  config_options: unknown[]
}

/** OpenCode 在项目中的状态 */
export interface OpenCodeStatus {
  cwd: string
  package_json_exists: boolean
  project_installed: boolean
  available: boolean
  command: string
}

/** OpenCode 项目安装结果 */
export interface OpenCodeInstallResult extends OpenCodeStatus {
  installed: boolean
  audit_passed: boolean | null
  output: string
}

/** 列出 Agent 响应 */
export interface AcpListAgentsResponse {
  agents: AcpAgent[]
  count: number
}

/** 列出会话响应 */
export interface AcpListSessionsResponse {
  sessions: AcpSession[]
  count: number
}

/** 权限选项 */
export interface AcpPermissionOption {
  /** 选项 ID */
  id: string
  /** 显示标签 */
  label: string
  /** 选项类型 */
  kind: string
  /** 提示信息（可选） */
  hint?: string
}

/** 挂起的权限请求 —— ACP 流中由 agent 暂停并请求用户决策时携带的上下文 */
export interface SuspendedPermission {
  /** Agent 名称（可选） */
  agent?: string
  /** 工具名称（可选） */
  tool_name?: string
  /** 工具类型（可选） */
  tool_kind?: string
  /** 操作目标（可选） */
  target?: string
  /** 动作描述（可选） */
  action?: string
  /** 摘要说明（可选） */
  summary?: string
  /** 命令文本（可选） */
  command?: string
  /** 涉及的文件路径列表（可选） */
  paths?: string[]
  /** 可选项列表（可选） */
  options?: AcpPermissionOption[]
  /** 是否要求用户显式确认（可选） */
  requires_user_confirmation?: boolean
}

/** 列出可用 Agent */
export async function listAgents(): Promise<AcpListAgentsResponse> {
  const { data } = await api.get<AcpListAgentsResponse>(`${BASE}/agents`)
  return data
}

/** 创建新的 ACP 会话 */
export async function createSession(agent: string, cwd?: string): Promise<AcpCreateSessionResponse> {
  const { data } = await api.post<AcpCreateSessionResponse>(`${BASE}/sessions`, { agent, cwd })
  return data
}

/** 查询指定工作目录的 OpenCode 状态 */
export async function getOpenCodeStatus(cwd?: string): Promise<OpenCodeStatus> {
  const { data } = await api.get<OpenCodeStatus>(`${BASE}/opencode/status`, { params: { cwd } })
  return data
}

/** 经用户确认后，在指定 Node.js 项目中安装 OpenCode */
export async function installOpenCode(cwd?: string): Promise<OpenCodeInstallResult> {
  const { data } = await api.post<OpenCodeInstallResult>(`${BASE}/opencode/install`, {
    cwd,
    confirm_install: true,
  })
  return data
}

/** 列出当前用户的 ACP 会话 */
export async function listSessions(): Promise<AcpListSessionsResponse> {
  const { data } = await api.get<AcpListSessionsResponse>(`${BASE}/sessions`)
  return data
}

/** 响应挂起的权限请求 */
export async function respondPermission(
  sessionId: string,
  optionId: string
): Promise<{ status: string }> {
  const { data } = await api.post<{ status: string }>(
    `${BASE}/sessions/${sessionId}/permission`,
    { option_id: optionId }
  )
  return data
}

/** 取消正在执行的回合 */
export async function cancelTurn(sessionId: string): Promise<{ cancelled: boolean }> {
  const { data } = await api.post<{ cancelled: boolean }>(`${BASE}/sessions/${sessionId}/cancel`)
  return data
}

/** 关闭会话 */
export async function closeSession(sessionId: string): Promise<{ closed: boolean }> {
  const { data } = await api.delete<{ closed: boolean }>(`${BASE}/sessions/${sessionId}`)
  return data
}
