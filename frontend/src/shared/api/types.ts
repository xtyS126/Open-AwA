/**
 * API 共享类型定义。
 * 从原 api.ts 提取，供各域 API 模块引用。
 */

export type ApiPayload = Record<string, unknown>
export type ApiObject = Record<string, unknown>

export type ConversationSortKey = 'title' | 'created_at' | 'updated_at' | 'last_message_at' | 'message_count'
export type ConversationSortOrder = 'asc' | 'desc'
export type WeixinAutoReplyMatchType = 'keyword' | 'regex'
export type ChatAttachmentType = 'image' | 'audio' | 'video'
export type ScheduledTaskType = 'ai_prompt' | 'plugin_command'
export type WeixinQrState = 'pending' | 'half_success' | 'success' | 'failed'
export type WeixinQrStatus = 'idle' | 'waiting' | 'scanned' | 'scaned_but_redirect' | 'expired' | 'confirmed' | 'refreshing'

export interface ChatStreamTeamPayload {
  team_id?: string
  name?: string
  ok?: boolean
  state?: string
  [key: string]: unknown
}

export interface ChatStreamEvent {
  type?: string
  content?: unknown
  reasoning_content?: unknown
  message?: unknown
  result?: ApiObject | null
  task?: ApiObject | null
  tool?: ApiObject | null
  usage?: ApiObject | null
  team?: ChatStreamTeamPayload | null
  task_id?: unknown
  agent_id?: unknown
  agent_type?: unknown
  description?: unknown
  run_mode?: unknown
  summary?: unknown
  state?: unknown
  [key: string]: unknown
}
