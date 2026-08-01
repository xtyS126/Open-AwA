/**
 * 行为统计 API 模块。封装行为日志与统计端点。自 api.ts 拆分而来。
 */
import { api } from './client'
import type { BehaviorStatsResponse, BehaviorLogsResponse } from './types'

export const behaviorAPI = {
  getStats: (days: number = 7) =>
    api.get<BehaviorStatsResponse>(`/behaviors/stats?days=${days}`),
  getLogs: (skip: number = 0, limit: number = 50) =>
    api.get<BehaviorLogsResponse>(`/behaviors/logs?skip=${skip}&limit=${limit}`),
  logBehavior: (actionType: string, details: string) =>
    api.post<{ ok: boolean; message?: string }>('/behaviors/log', { action_type: actionType, details }),
}
