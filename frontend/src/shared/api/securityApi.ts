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
}
