/**
 * 终端会话与命令执行 API 模块。
 * 提供终端会话的创建、命令执行、关闭和列表查询接口。
 */
import api from '@/shared/api/api'

// 注意：sharedApi 的 baseURL 已包含 /api（后端 main.py 将 terminal 路由注册在
// /api 前缀下，实际端点 /api/terminal/...），BASE 必须从领域路径开始写 '/terminal'，
// 禁止写成 '/api/terminal'（会产生 /api/api/terminal 双前缀 404）
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

// ===== PTY 持久化终端会话 =====

/** PTY 终端会话信息 */
export interface PTYSessionInfo {
  session_id: string
  cwd: string
  active: boolean
  shell?: string
  cols?: number
  rows?: number
}

/** PTY 会话创建请求参数 */
export interface PTYCreateRequest {
  /** 子进程工作目录（不传使用后端默认） */
  cwd?: string
  /** 初始列数，默认 80 */
  cols?: number
  /** 初始行数，默认 24 */
  rows?: number
  /** 自定义 PTY 启动命令（如 ['bash']），不传使用后端平台默认 */
  command?: string[]
}

/** PTY 会话创建响应 */
export interface PTYCreateResponse {
  ok: boolean
  session_id?: string
  cwd?: string
  cols?: number
  rows?: number
  shell?: string
  error?: string
}

/** PTY 屏幕快照 */
export interface PTYSnapshot {
  ok: boolean
  grid: string[][]
  cols: number
  rows: number
}

/**
 * 创建 PTY 持久化终端会话。
 * 与普通 TerminalSession 不同，PTY 会话长期持有交互式 shell 进程，
 * 支持断线重连与屏幕恢复。
 */
export async function createPtySession(params: PTYCreateRequest = {}): Promise<PTYCreateResponse> {
  const { data } = await api.post(BASE + '/sessions/pty', {
    cwd: params.cwd,
    cols: params.cols ?? 80,
    rows: params.rows ?? 24,
    command: params.command,
  })
  return data
}

/**
 * 关闭 PTY 终端会话。
 * 同时终止底层 PTY 子进程并清理服务端状态。
 */
export async function closePtySession(sessionId: string): Promise<{ ok: boolean; error?: string }> {
  const { data } = await api.delete(`${BASE}/sessions/pty/${sessionId}`)
  return data
}

/**
 * 获取 PTY 会话的当前屏幕快照。
 * 返回 grid 二维数组与尺寸，用于断线重连时恢复显示。
 */
export async function getPtySnapshot(sessionId: string): Promise<PTYSnapshot> {
  const { data } = await api.get(`${BASE}/sessions/pty/${sessionId}/snapshot`)
  return data
}
