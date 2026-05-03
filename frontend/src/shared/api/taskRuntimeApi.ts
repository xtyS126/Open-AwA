/**
 * 任务运行时 API 模块——提供代理会话查询、停止与 transcript 读取接口。
 */

import axios from 'axios'

const api = axios.create({
  baseURL: '/api/task-runtime',
  timeout: 30000,
  withCredentials: true,
})

/* 请求拦截器: CSRF token */
api.interceptors.request.use((config) => {
  const csrfToken = document.cookie
    .split('; ')
    .find((row) => row.startsWith('csrf_token='))
    ?.split('=')[1]
  if (csrfToken) {
    config.headers['X-CSRF-Token'] = csrfToken
  }
  return config
})

/* 类型定义 */
export interface AgentSessionInfo {
  agent_id: string
  agent_type: string
  state: string
  run_mode: string
  summary?: string
  last_error?: string
  created_at?: string
  started_at?: string
  ended_at?: string
}

export interface AgentDetail {
  agent_id: string
  agent_type: string
  parent_session_id?: string
  root_chat_session_id?: string
  state: string
  run_mode: string
  isolation_mode: string
  transcript_path?: string
  summary?: string
  last_error?: string
  created_at?: string
  started_at?: string
  ended_at?: string
}

export interface TaskItemInfo {
  task_id: string
  list_id?: string
  subject: string
  status: string
  owner_agent_id?: string
}

/* API 方法 */
export async function listAgents(params?: {
  state?: string
  agent_type?: string
}): Promise<{ agents: AgentSessionInfo[]; total: number }> {
  const { data } = await api.get('/agents', { params })
  return data
}

export async function getAgent(agentId: string): Promise<{ agent: AgentDetail }> {
  const { data } = await api.get(`/agents/${agentId}`)
  return data
}

export async function stopAgent(agentId: string): Promise<{ ok: boolean; agent_id: string; status: string }> {
  const { data } = await api.post(`/agents/${agentId}/stop`)
  return data
}

export async function getTranscript(
  agentId: string
): Promise<{ agent_id: string; transcript: unknown[]; entry_count: number }> {
  const { data } = await api.get(`/agents/${agentId}/transcript`)
  return data
}

export async function listAgentTypes(): Promise<{ agent_types: { name: string; description: string }[] }> {
  const { data } = await api.get('/agent-types')
  return data
}

export async function listTasks(params?: {
  list_id?: string
  status?: string
}): Promise<{ tasks: TaskItemInfo[]; total: number }> {
  const { data } = await api.get('/tasks', { params })
  return data
}

export interface TaskItemDetail {
  task_id: string
  list_id?: string
  subject: string
  description?: string
  status: string
  dependencies?: string[]
  owner_agent_id?: string
  result_summary?: string
  created_at?: string
  updated_at?: string
  completed_at?: string
}

export async function getTask(taskId: string): Promise<{ task: TaskItemInfo }> {
  const { data } = await api.get(`/tasks/${taskId}`)
  return data
}

export async function claimTask(
  taskId: string,
  agentId: string
): Promise<{ ok: boolean; task_id: string; status: string }> {
  const { data } = await api.post(`/tasks/${taskId}/claim`, null, { params: { agent_id: agentId } })
  return data
}

export async function stopTask(taskId: string): Promise<{ ok: boolean; task_id: string; status: string }> {
  const { data } = await api.post(`/tasks/${taskId}/stop`)
  return data
}

/* ── 团队管理 API（Phase 4）──────────────────────────────────── */

export interface TeamMember {
  agent_id: string
  name: string
  role: string
  state: string
  joined_at?: string
}

export interface TeamInfo {
  team_id: string
  name: string
  lead_agent_id?: string
  state: string
  task_list_id?: string
  members: TeamMember[]
  created_at?: string
  updated_at?: string
}

export interface TeamDetail extends TeamInfo {
  tasks: {
    task_id: string
    subject: string
    status: string
    owner_agent_id?: string
  }[]
}

export interface MailboxMessage {
  message_id: string
  from_agent_id: string
  to_agent_id: string
  team_id?: string
  payload: { message: string }
  delivered: boolean
  read_at?: string
  created_at?: string
}

export async function listTeams(params?: {
  state?: string
}): Promise<{ teams: TeamInfo[]; total: number }> {
  const { data } = await api.get('/teams', { params })
  return data
}

export async function getTeam(teamId: string): Promise<{ team: TeamDetail }> {
  const { data } = await api.get(`/teams/${teamId}`)
  return data
}

export async function createTeam(params: {
  lead_agent_id: string
  name?: string
  task_list_id?: string
}): Promise<{ ok: boolean; team_id: string; name: string; lead_agent_id: string; state: string; members: TeamMember[] }> {
  const { data } = await api.post('/teams', null, { params })
  return data
}

export async function deleteTeam(teamId: string): Promise<{ ok: boolean; team_id: string; status: string }> {
  const { data } = await api.delete(`/teams/${teamId}`)
  return data
}

export async function addTeammate(
  teamId: string,
  agentId: string,
  name?: string
): Promise<{ ok: boolean; team_id: string; agent_id: string; name: string }> {
  const { data } = await api.post(`/teams/${teamId}/members`, null, {
    params: { agent_id: agentId, name: name || '' },
  })
  return data
}

export async function removeTeammate(
  teamId: string,
  agentId: string
): Promise<{ ok: boolean; team_id: string; agent_id: string; status: string }> {
  const { data } = await api.delete(`/teams/${teamId}/members/${agentId}`)
  return data
}

export async function updateTeammateState(
  teamId: string,
  agentId: string,
  newState: string
): Promise<{ ok: boolean; team_id: string; agent_id: string; state: string }> {
  const { data } = await api.patch(`/teams/${teamId}/members/${agentId}/state`, null, {
    params: { new_state: newState },
  })
  return data
}

export async function getMailbox(
  agentId: string,
  unreadOnly?: boolean
): Promise<{ agent_id: string; messages: MailboxMessage[]; total: number }> {
  const { data } = await api.get(`/mailbox/${agentId}`, { params: { unread_only: unreadOnly || false } })
  return data
}

export async function readMessage(
  messageId: string
): Promise<{ ok: boolean; message_id: string; delivered: boolean }> {
  const { data } = await api.post(`/mailbox/${messageId}/read`)
  return data
}

export async function sendTeammateMessage(params: {
  from_agent_id: string
  to_agent_id: string
  message: string
  team_id?: string
}): Promise<{
  ok: boolean
  message_id: string
  from_agent_id: string
  to_agent_id: string
  delivered: boolean
}> {
  const { data } = await api.post('/messages', null, { params })
  return data
}
