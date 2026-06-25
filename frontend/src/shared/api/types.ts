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

// ---- 技能 API 响应类型 ----
export interface SkillItem {
  id: string
  name: string
  version?: string | null
  description?: string | null
  config?: Record<string, unknown> | null
  enabled: boolean
  installed_at?: string
  [key: string]: unknown
}

// GET /skills 返回裸数组
export type SkillsListResponse = SkillItem[]

// POST /skills/parse-upload 响应（前端 SkillModal 期望顶层字段）
export interface SkillParseUploadResponse {
  name?: string
  description?: string
  instructions?: string
  [key: string]: unknown
}

// ---- 插件 API 响应类型 ----
export interface PluginItem {
  id: string
  name: string
  version?: string | null
  enabled: boolean
  installed_at?: string
  runtime_loaded?: boolean | null
  runtime_state?: string | null
  category?: string | null
  author?: string | null
  source?: string | null
  [key: string]: unknown
}

// GET /plugins 返回裸数组
export type PluginsListResponse = PluginItem[]

// GET /plugins/discover 返回裸数组（字段与 PluginItem 不同）
export interface DiscoveredPluginItem {
  name: string
  version: string
  description: string
  path: string
  loaded: boolean
  state: string
  requested_permissions: string[]
  [key: string]: unknown
}

// GET /plugins/discover 返回裸数组
export type PluginsDiscoverResponse = DiscoveredPluginItem[]

export interface PluginInstallResponse {
  ok?: boolean
  message?: string
  plugin_id?: string
  skill?: SkillItem
  error?: string
  [key: string]: unknown
}

// ---- 记忆 API 响应类型 ----
export interface ShortTermMemoryItem {
  id: number
  session_id: string
  role: string
  content: string
  timestamp: string
  [key: string]: unknown
}

export interface LongTermMemoryItem {
  id: number
  content: string
  importance: number
  created_at?: string
  access_count?: number
  last_access?: string
  confidence?: number
  quality_score?: number
  archive_status?: string
  memory_metadata?: Record<string, unknown>
  [key: string]: unknown
}

// GET /memory/short-term/{sessionId} 返回裸数组
export type ShortTermMemoryListResponse = ShortTermMemoryItem[]
// GET /memory/long-term 返回裸数组
export type LongTermMemoryListResponse = LongTermMemoryItem[]
// GET /memory/search 返回裸数组
export type MemorySearchResponse = LongTermMemoryItem[]

// ---- 提示词 API 响应类型 ----
export interface PromptItem {
  id: string
  name: string
  content: string
  variables?: string | null
  is_active: boolean
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

// GET /prompts 返回裸数组
export type PromptsListResponse = PromptItem[]

// ---- 行为 API 响应类型 ----
export interface BehaviorStatsResponse {
  total_interactions: number
  total_tools_used: number
  total_errors?: number
  top_tools?: Array<{ tool: string; count: number }>
  top_intents?: Array<{ intent: string; count: number }>
  average_response_time: number
  chart_data?: Array<{ day: string; interactions: number }>
  [key: string]: unknown
}

export interface BehaviorLogItem {
  id: number
  action_type: string
  details: string
  created_at?: string
  [key: string]: unknown
}

// GET /behaviors/logs 返回裸数组
export type BehaviorLogsResponse = BehaviorLogItem[]

// ---- 聊天 API 响应类型 ----
// GET /chat/history/{sessionId} 返回裸数组
export type ChatHistoryResponse = Array<{
  id?: number | string
  role: string
  content: string
  timestamp?: string
  reasoning_content?: string | null
  toolEvents?: unknown
  [key: string]: unknown
}>

export interface ChatUploadResponse {
  filename: string
  original_name?: string
  size?: number
  type?: string
  url: string
  [key: string]: unknown
}

export interface ChatCancelResponse {
  status: string
  session_id: string
  message: string
  [key: string]: unknown
}

export interface ChatFeedbackResponse {
  status: string
  message: string
  [key: string]: unknown
}

export interface ChatUndoOperationResponse {
  ok?: boolean
  message?: string
  restored?: boolean
  [key: string]: unknown
}
