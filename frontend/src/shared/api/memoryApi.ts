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
  // Spec memory-experience-redesign：混合检索（携带关键词/向量权重，接前端权重滑块）
  vectorSearch: (params: { query: string; limit?: number; include_archived?: boolean; keyword_weight?: number; vector_weight?: number }) =>
    api.post<MemorySearchResponse>('/memory/vector-search', params),
  // Spec memory-experience-redesign：记忆质量批量报告（低置信度/待验证/可归档）
  getQuality: (limit: number = 20) =>
    api.get<unknown>('/memory/quality', { params: { limit } }),
  // Spec memory-experience-redesign：记忆统计（含分层统计，替换硬编码卡片）
  getStats: () => api.get<unknown>('/memory/stats'),
  // Spec memory-experience-redesign：记忆衰减配置查询与更新（接前端开关）
  getDecayConfig: () => api.get<{ success: boolean; data: Record<string, { layer: string; decay_function: string; half_life_days: number; threshold: number; enabled: boolean }> }>('/memory/decay-config'),
  updateDecayConfig: (config: { layer: string; decay_function?: string; half_life_days?: number; threshold?: number; enabled?: boolean }) =>
    api.put<{ success: boolean; data: unknown; message?: string }>('/memory/decay-config', config),
  // Spec memory-experience-redesign：用户验证闭环（准确/不准确）
  validateLongTerm: (id: number) =>
    api.post<{ ok: boolean; message?: string; memory_id: number; state: string }>(`/memory/long-term/${id}/validate`),
  deprecateLongTerm: (id: number) =>
    api.post<{ ok: boolean; message?: string; memory_id: number; state: string }>(`/memory/long-term/${id}/deprecate`),
  // Spec memory-experience-redesign：手动触发记忆巩固
  runConsolidation: () => api.post<{ triggered: boolean; success: boolean; processed?: number; extracted?: number; consolidated?: number; archived?: number; error?: string }>('/memory/consolidation/run'),
}
