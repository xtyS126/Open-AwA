export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning_content?: string
  timestamp: Date
  toolEvents?: ToolEventMeta[]
  segments?: AssistantMessageSegment[]
}

export type TaskStatus = 'pending' | 'running' | 'completed' | 'error'

export interface SubagentExecutionState {
  agentId: string
  agentType?: string
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
