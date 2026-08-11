/**
 * 会话管理 API 模块。封装会话列表查询端点。自 api.ts 拆分而来。
 */
import { api } from './client'
import type { ConversationSortKey, ConversationSortOrder } from './types'

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

export interface ConversationSessionCreatePayload {
  title?: string
  session_id?: string
}

export interface AssistantConversationContext {
  session_id: string
  role_id: string | null
  workspace_id: string
  selected_memory_ids: number[]
  speaker_id: string | null
}

export type AssistantConversationContextUpdate = Omit<
  AssistantConversationContext,
  'session_id'
>

export interface ConversationSessionListParams {
  search?: string
  sort_by?: ConversationSortKey
  sort_order?: ConversationSortOrder
  page?: number
  page_size?: number
  include_deleted?: boolean
}

export interface ConversationSessionListResponse {
  items: ConversationSessionSummary[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export interface ConversationRecordItem {
  id: number
  session_id: string
  user_id: string
  node_type: string
  user_message: string
  timestamp: string | null
  provider: string | null
  model: string | null
  llm_input: unknown
  llm_output: unknown
  llm_tokens_used: number | null
  execution_duration_ms: number | null
  status: string
  error_message: string | null
  metadata: unknown
}

export interface ConversationRecordsResponse {
  records: ConversationRecordItem[]
  count: number
  limit: number
}

export interface ConversationCollectionStatusResponse {
  enabled: boolean
  stats: {
    queue_size: number
    queue_maxsize: number
    dropped_count: number
    tracked_user_count: number
  }
}

export const conversationAPI = {
  listSessions: (params?: ConversationSessionListParams, signal?: AbortSignal) =>
    api.get<ConversationSessionListResponse>('/conversations', { params, signal }),
  createSession: (payload: ConversationSessionCreatePayload = {}) =>
    api.post<ConversationSessionSummary>('/conversations', payload),
  getAssistantContext: (sessionId: string) =>
    api.get<AssistantConversationContext>(
      `/conversations/${encodeURIComponent(sessionId)}/assistant-context`,
    ),
  updateAssistantContext: (
    sessionId: string,
    context: AssistantConversationContextUpdate,
  ) =>
    api.patch<AssistantConversationContext>(
      `/conversations/${encodeURIComponent(sessionId)}/assistant-context`,
      context,
    ),
  renameSession: (sessionId: string, title: string) =>
    api.patch<ConversationSessionSummary>(`/conversations/${sessionId}`, { title }),
  deleteSession: (sessionId: string, retentionDays: number = 30) =>
    api.delete<ConversationSessionSummary>(`/conversations/${sessionId}`, {
      params: { retention_days: retentionDays },
    }),
  restoreSession: (sessionId: string) =>
    api.post<ConversationSessionSummary>(`/conversations/${sessionId}/restore`),
  batchDeleteSessions: (sessionIds: string[], retentionDays: number = 30) =>
    api.post<ConversationSessionListResponse>('/conversations/batch-delete', {
      session_ids: sessionIds,
      retention_days: retentionDays,
    }),
  getCollectionStatus: () =>
    api.get<ConversationCollectionStatusResponse>('/conversations/collection-status'),
  updateCollectionStatus: (enabled: boolean) =>
    api.put('/conversations/collection-status', null, { params: { enabled } }),
  getRecordsPreview: (limit: number = 20) =>
    api.get<ConversationRecordsResponse>('/conversations/records', { params: { limit } }),
  exportRecords: (params?: { start_time?: string; end_time?: string }) =>
    api.get('/conversations/export', { params, responseType: 'blob' }),
  cleanupRecords: (days: number = 30) =>
    api.delete('/conversations/records/cleanup', { params: { days } }),
}
