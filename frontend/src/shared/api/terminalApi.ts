/**
 * 终端会话与命令执行 API 模块。
 * 提供终端会话的创建、命令执行、关闭和列表查询接口。
 */
import api from '@/shared/api/api'

const BASE = '/terminal'

/** 终端会话信息 */
export interface TerminalSession {
  session_id: string
  cwd: string
  active: boolean
}

/** 命令执行结果 */
export interface CommandResult {
  ok: boolean
  exit_code?: number
  stdout: string
  stderr: string
  error?: string
}

/** 创建终端会话 */
export async function createSession(cwd?: string): Promise<{ ok: boolean; session_id?: string; cwd?: string; error?: string }> {
  const { data } = await api.post(BASE + '/sessions', null, { params: { cwd } })
  return data
}

/** 执行命令 */
export async function executeCommand(sessionId: string, command: string, timeout?: number): Promise<CommandResult> {
  const { data } = await api.post(`${BASE}/sessions/${sessionId}/execute`, { command, timeout })
  return data
}

/** 关闭会话 */
export async function closeSession(sessionId: string): Promise<void> {
  await api.delete(`${BASE}/sessions/${sessionId}`)
}

/** 列出活跃会话 */
export async function listSessions(): Promise<{ ok: boolean; sessions: TerminalSession[] }> {
  const { data } = await api.get(BASE + '/sessions')
  return data
}
