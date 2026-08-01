/**
 * 记忆 API 模块。封装短期/长期记忆查询与搜索端点。自 api.ts 拆分而来。
 */
import { api } from './client'
import type { ShortTermMemoryItem, LongTermMemoryItem, ShortTermMemoryListResponse, LongTermMemoryListResponse, MemorySearchResponse } from './types'

export const memoryAPI = {
  getShortTerm: (sessionId: string) =>
    api.get<ShortTermMemoryListResponse>(`/memory/short-term/${sessionId}`),
  addShortTerm: (sessionId: string, role: string, content: string) =>
    api.post<ShortTermMemoryItem>('/memory/short-term', { session_id: sessionId, role, content }),
  deleteShortTerm: (id: number) =>
    api.delete<{ ok: boolean; message?: string }>(`/memory/short-term/${id}`),
  getLongTerm: () => api.get<LongTermMemoryListResponse>('/memory/long-term'),
  addLongTerm: (content: string, importance: number = 0.5) =>
    api.post<LongTermMemoryItem>('/memory/long-term', { content, importance }),
  deleteLongTerm: (id: number) =>
    api.delete<{ ok: boolean; message?: string }>(`/memory/long-term/${id}`),
  search: (query: string) => api.get<MemorySearchResponse>('/memory/search', { params: { query } }),
  // Spec memory-quality-and-short-term-recovery Task 13：按 session 分组返回当前用户的全部短期记忆
  // 支持 limit / session_id / query 查询参数
  listShortTerm: (params: { limit?: number; session_id?: string; query?: string } = {}) =>
    api.get<ShortTermMemoryListResponse>('/memory/short-term', { params }),
  // Spec memory-quality-and-short-term-recovery Task 14：返回当前用户最近 N 条短期记忆
  // 用于新对话上下文恢复
  getRecentShortTerm: (limit: number = 20) =>
    api.get<ShortTermMemoryListResponse>('/memory/short-term/recent', { params: { limit } }),
}
