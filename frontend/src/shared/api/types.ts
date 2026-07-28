/**
 * API 共享类型定义。
 * 从原 api.ts 提取，供各域 API 模块引用。
 *
 * 部分类型已从 OpenAPI 自动生成的 schema.d.ts 推断，覆盖 billing/plugins/memory/skills 相关接口；
 * 其余仍为手工镜像类型，待后续逐步迁移。
 */
import type { components } from './schema'

/** 从 OpenAPI schema 推断的组件类型别名，便于在下方引用 */
type Schemas = components['schemas']

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
  /** 后端注入的事件序列号，用于断连重连时定位 from_seq */
  _seq?: number
  [key: string]: unknown
}

// ---- 技能 API 响应类型 ----
// 从 OpenAPI schema.d.ts 推断；不带交叉索引签名，避免与历史调用方结构兼容性检查退化属性类型
export type SkillItem = Schemas['SkillResponse']

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
// 从 OpenAPI schema.d.ts 推断；不带交叉索引签名，避免与 Plugin 接口结构兼容性检查时退化属性类型
export type PluginItem = Schemas['PluginResponse']

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
// 从 OpenAPI schema.d.ts 推断；不带交叉索引签名，避免结构兼容性检查退化属性类型
export type ShortTermMemoryItem = Schemas['ShortTermMemoryResponse']

// 从 OpenAPI schema.d.ts 推断；不带交叉索引签名，避免结构兼容性检查退化属性类型
export type LongTermMemoryItem = Schemas['LongTermMemoryResponse']

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

/** 聊天任务摘要（列表项） */
export interface ChatTaskSummary {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  session_id: string
  created_at: number
  finished_at: number | null
  event_count: number
}

/** 聊天任务详细状态 */
export interface ChatTaskStatus {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  event_count: number
  next_seq: number
  created_at: number
  finished_at: number | null
  error: { code?: string; message?: string } | null
  session_id: string
  user_id: string
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

// ---- 问题反馈 API 类型 ----
/** 问题反馈类型：bug 报告 / 功能建议 / 使用疑问 / 其他 */
export type IssueFeedbackType = 'bug' | 'suggestion' | 'question' | 'other'

/** 问题反馈提交请求体 */
export interface IssueFeedbackPayload {
  issue_type: IssueFeedbackType
  title: string
  content: string
  page_url: string
}

/** 问题反馈提交响应 */
export interface IssueFeedbackSubmitResponse {
  ok: boolean
  file_id: string
}
