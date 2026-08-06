/**
 * 行为统计 API 模块。封装行为日志与统计端点。自 api.ts 拆分而来。
 */
import { api } from './client'
import type { BehaviorStatsResponse, BehaviorLogsResponse } from './types'

/**
 * 获取浏览器时区相对 UTC 的分钟偏移（UTC+8 返回 480）。
 * 与后端 /behaviors/stats 的 tz_offset 参数约定一致，用于按本地时区聚合按天图表。
 * 服务端渲染（无 window）时返回 0，保持 UTC 默认行为。
 */
function getBrowserTzOffset(): number {
  if (typeof window === 'undefined' || typeof Date.prototype.getTimezoneOffset !== 'function') {
    return 0
  }
  // JS getTimezoneOffset 返回 UTC - local（UTC+8 返回 -480），取负得到 local - UTC
  return -new Date().getTimezoneOffset()
}

export const behaviorAPI = {
  getStats: (days: number = 7) =>
    api.get<BehaviorStatsResponse>(
      `/behaviors/stats?days=${days}&tz_offset=${getBrowserTzOffset()}`,
    ),
  getLogs: (skip: number = 0, limit: number = 50) =>
    api.get<BehaviorLogsResponse>(`/behaviors/logs?skip=${skip}&limit=${limit}`),
  logBehavior: (actionType: string, details: string) =>
    api.post<{ ok: boolean; message?: string }>('/behaviors/log', { action_type: actionType, details }),
}
