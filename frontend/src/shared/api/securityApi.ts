/**
 * 安全模块 API，提供 RBAC 角色管理与审计日志查询接口。
 */
import api from '@/shared/api/api'

// -------- 类型定义 --------

export interface RoleInfo {
  name: string
  display_name: string | null
  permissions: string[]
}

export interface UserRoleInfo {
  user_id: string
  role_name: string
  assigned_at: string | null
}

export interface PermissionCheckResult {
  allowed: boolean
  role: string
  permission: string
}

export interface AuditLogItem {
  id: number
  user_id: string | null
  action: string
  resource: string | null
  result: string | null
  details: string | null
  ip_address: string | null
  created_at: string | null
}

export interface AuditLogListResult {
  logs: AuditLogItem[]
  total: number
  page: number
  page_size: number
}

export interface AuditLogQueryParams {
  page?: number
  page_size?: number
  user_id?: string
  action?: string
  result?: string
  start_time?: string
  end_time?: string
}

export interface AuditStats {
  total: number
  success_count: number
  success_rate: number
  action_stats: { action: string; count: number }[]
  top_users: { user_id: string; count: number }[]
}

/** 权限请求 */
export interface PermissionRequest {
  id: string
  session_id: string
  action: string
  resources: string[]
  /** 需要持久化保存的权限规则名称列表（对应后端 saved_rules 字段） */
  save?: string[]
  metadata?: Record<string, unknown>
  agent?: string
}

/** 权限回复 */
export interface PermissionReply {
  request_id: string
  reply: 'once' | 'always' | 'reject'
  message?: string
}

/** 已保存的持久化权限 */
export interface SavedPermission {
  id: string
  action: string
  resource: string
  project_id: string
  created_at: string | null
}

/** 已保存权限列表 */
export interface SavedPermissionsList {
  permissions: SavedPermission[]
  total: number
}

/** SSE 一次性 ticket 响应 */
export interface SseTicketResult {
  ticket: string
  expires_in: number
}

// -------- SSE ticket 内存缓存 --------
//
// VibeCodingPage 与 usePermissionRequest 各自申请 ticket 会触发重复 POST，
// 模块级缓存让多个调用方在 TTL 窗口内复用同一张 ticket，将请求数从 N 降到 1。
// TTL 略小于服务端 60 秒有效期，避免边界过期导致 SSE 连接被拒。

let _cachedTicket: { value: string; expiresAt: number } | null = null
const TICKET_CACHE_TTL_MS = 55 * 1000

/** 清空 SSE ticket 缓存。401 失败或显式失效时调用，下次 requestSseTicket 会重新申请。 */
export function clearSseTicketCache(): void {
  _cachedTicket = null
}

// -------- 接口方法 --------

export const securityAPI = {
  /** 获取所有角色列表 */
  getRoles() {
    return api.get<RoleInfo[]>('/security/roles')
  },

  /** 获取指定用户的角色信息 */
  getUserRole(userId: string) {
    return api.get<UserRoleInfo>(`/security/users/${userId}/role`)
  },

  /** 设置用户角色 */
  setUserRole(userId: string, roleName: string) {
    return api.put<UserRoleInfo>(`/security/users/${userId}/role`, {
      role_name: roleName,
    })
  },

  /** 检查权限 */
  checkPermission(userId: string, permission: string) {
    return api.post<PermissionCheckResult>('/security/check-permission', {
      user_id: userId,
      permission,
    })
  },

  /** 获取审计日志列表 */
  getAuditLogs(params: AuditLogQueryParams = {}) {
    return api.get<AuditLogListResult>('/security/audit-logs', { params })
  },

  /** 导出审计日志（JSONL 格式） */
  exportAuditLogs(params: AuditLogQueryParams = {}) {
    return api.get('/security/audit-logs/export', {
      params,
      responseType: 'blob',
    })
  },

  /** 获取审计统计信息 */
  getAuditStats() {
    return api.get<AuditStats>('/security/audit-logs/stats')
  },

  /** 回复权限请求（TODO: 待权限请求轮询/WebSocket 集成后启用） */
  replyToPermission(reply: PermissionReply) {
    return api.post<{ ok: boolean }>('/security/permissions/reply', reply)
  },

  /**
   * 申请一次性 SSE ticket。
   *
   * 用于替代 URL query 传递 API Key：前端通过标准 Authorization Header
   * 调用此端点换取短时 ticket，再以 ?ticket=<ticket> 连接 SSE 端点，
   * 避免 API Key 泄露到 access log / Referer / 浏览器历史。
   *
   * 命中内存缓存时直接返回 ticket 字符串，避免多个调用方重复 POST。
   * 调用方遇到 401 应调用 clearSseTicketCache() 后重试。
   */
  async requestSseTicket(signal?: AbortSignal): Promise<string> {
    // 命中缓存：TTL 内直接复用，减少重复网络请求
    if (_cachedTicket && Date.now() < _cachedTicket.expiresAt) {
      return _cachedTicket.value
    }
    const response = await api.post<SseTicketResult>(
      '/security/permissions/sse-ticket',
      undefined,
      { signal },
    )
    const ticket = response.data.ticket
    _cachedTicket = {
      value: ticket,
      expiresAt: Date.now() + TICKET_CACHE_TTL_MS,
    }
    return ticket
  },

  /** 获取已保存的权限列表 */
  getSavedPermissions() {
    return api.get<SavedPermissionsList>('/security/permissions/saved')
  },

  /** 删除单条已保存权限 */
  deleteSavedPermission(id: string) {
    return api.delete(`/security/permissions/saved/${encodeURIComponent(id)}`)
  },

  /** 删除所有已保存权限 */
  deleteAllSavedPermissions() {
    return api.delete('/security/permissions/saved')
  },
}
