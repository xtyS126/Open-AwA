/**
 * 数据看板 API 封装。
 * 提供数据统计概览、对话记录、工具调用日志和数据导出接口。
 */
import api from '@/shared/api/api'

const BASE = '/data'

/** 数据统计概览 */
export interface DataStats {
  conversation_count: number
  tool_call_count: number
  trace_count: number
  feedback_count: number
  avg_response_time_ms: number
  role_usage: Array<{ role_id: string; count: number }>
}

/** 分页响应 */
export interface PaginatedData<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

/** 对话记录 */
export interface ConversationDataItem {
  id: number
  conversation_id: string
  role_id: string
  user_message: string
  assistant_message: string
  tools_used: string[]
  model_used: string
  token_count: Record<string, unknown>
  response_time_ms: number
  created_at: string | null
}

/** 工具调用记录 */
export interface ToolCallDataItem {
  id: number
  conversation_id: string
  role_id: string
  tool_name: string
  tool_params: Record<string, unknown>
  result_summary: string
  success: boolean
  duration_ms: number
  created_at: string | null
}

/** 获取数据统计概览 */
export async function getDataStats(): Promise<DataStats> {
  const { data } = await api.get(`${BASE}/stats`)
  return data
}

/** 获取对话记录 */
export async function getConversations(params?: {
  role_id?: string
  start_date?: string
  end_date?: string
  page?: number
  page_size?: number
}): Promise<PaginatedData<ConversationDataItem>> {
  const { data } = await api.get(`${BASE}/conversations`, { params })
  return data
}

/** 获取工具调用日志 */
export async function getToolCalls(params?: {
  role_id?: string
  page?: number
  page_size?: number
}): Promise<PaginatedData<ToolCallDataItem>> {
  const { data } = await api.get(`${BASE}/tool-calls`, { params })
  return data
}

/** 导出数据 */
export async function exportData(params: {
  format?: string
  data_type?: string
  role_id?: string
  start_date?: string
  end_date?: string
}): Promise<unknown> {
  const { data } = await api.post(`${BASE}/export`, null, { params })
  return data
}
