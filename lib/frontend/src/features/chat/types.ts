export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning_content?: string
  timestamp: Date
  toolEvents?: ToolEventMeta[]
  segments?: AssistantMessageSegment[]
  /** 标记该消息为错误消息，用于视觉区分 */
  isError?: boolean
}

export type TaskStatus = 'pending' | 'running' | 'completed' | 'error'

export interface SubagentExecutionState {
  agentId: string
  agentType?: string
  runMode?: 'foreground' | 'background'
  logs: string
  archivedLogs?: string
  summary?: string
  errorText?: string
  lastOutputAt?: number
  createdAt?: number
  completedAt?: number
  exitCode?: number
  truncated?: boolean
  timedOut?: boolean
  visible?: boolean
}

export interface TaskStepMeta {
  step: number
  action: string
  purpose?: string
  status: TaskStatus
  summary?: string
}

export interface ToolEventMeta {
  id: string
  kind: string
  name: string
  status: TaskStatus
  detail?: string
  input?: Record<string, unknown>
  output?: unknown
  sequence?: number
  startedAt?: number
  completedAt?: number
  subagent?: SubagentExecutionState
}

export interface SubagentAggregationMeta {
  text: string
  total: number
  successCount: number
  errorCount: number
  completedAt: number
}

export interface UsageMeta {
  call_id?: string
  provider?: string
  model?: string
  input_tokens?: number
  output_tokens?: number
  total_cost?: number
  currency?: string
  duration_ms?: number
  estimated?: boolean
}

export interface AssistantThoughtSegment {
  id: string
  kind: 'thought'
  reasoningContent: string
  toolEvents: ToolEventMeta[]
  steps: TaskStepMeta[]
  usage?: UsageMeta
  intent?: string
  status: 'running' | 'completed'
}

export interface AssistantReplySegment {
  id: string
  kind: 'reply'
  content: string
}

export type AssistantMessageSegment = AssistantThoughtSegment | AssistantReplySegment

export interface AssistantExecutionMeta {
  intent?: string
  requiresConfirmation?: boolean
  steps: TaskStepMeta[]
  toolEvents: ToolEventMeta[]
  usage?: UsageMeta
  totalDuration?: number
  subagentAggregation?: SubagentAggregationMeta
}

export interface ConversationSessionSummary {
  session_id: string
  user_id: string
  title: string
  summary: string
  last_message_preview: string
  last_message_role?: string | null
  message_count: number
  created_at: string
  updated_at: string
  last_message_at?: string | null
  deleted_at?: string | null
  restored_at?: string | null
  purge_after?: string | null
  conversation_metadata: Record<string, unknown>
}

/**
 * ask_user 工具下发的问题卡片载荷。
 *
 * 后端通过 SSE 事件 type="ask_user" 下发，前端 dispatchStructuredStreamEvent
 * 解析后设置到 ChatPage state，由 AskUserCard 组件渲染。
 * 同一时刻最多只有一个挂起的 ask_user 请求（后端 is_concurrency_safe=False）。
 */
export interface AskUserRequest {
  /** 请求唯一标识，提交回答时回传 */
  request_id: string
  /** 会话 ID，提交回答时用于鉴权校验 */
  session_id: string
  /** 向用户展示的问题文本 */
  question: string
  /** 预设选项列表（为空则只有自由文本输入） */
  options: string[]
  /** 是否允许多选 */
  allow_multiple: boolean
  /** 是否允许自由文本输入 */
  allow_free_text: boolean
  /** 输入框占位提示 */
  placeholder: string
  /** 超时秒数（60-600） */
  timeout: number
  /** 创建时间戳（秒） */
  created_at?: number
}
