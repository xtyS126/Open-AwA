/**
 * 安全审计设置组件，提供审计日志查看、RBAC 角色管理与统计展示。
 */
import { useState, useEffect, useCallback } from 'react'
import {
  securityAPI,
  RoleInfo,
  AuditLogItem,
  AuditStats,
  AuditLogQueryParams,
} from '@/shared/api/securityApi'
import { appLogger } from '@/shared/utils/logger'
import styles from './SecuritySettings.module.css'

function SecuritySettings() {
  // 审计日志相关状态
  const [logs, setLogs] = useState<AuditLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [loadingLogs, setLoadingLogs] = useState(false)

  // 筛选器状态
  const [filterUserId, setFilterUserId] = useState('')
  const [filterAction, setFilterAction] = useState('')
  const [filterResult, setFilterResult] = useState('')
  const [filterStartTime, setFilterStartTime] = useState('')
  const [filterEndTime, setFilterEndTime] = useState('')

  // 统计信息
  const [stats, setStats] = useState<AuditStats | null>(null)
  const [loadingStats, setLoadingStats] = useState(false)

  // RBAC 角色管理
  const [roles, setRoles] = useState<RoleInfo[]>([])
  const [loadingRoles, setLoadingRoles] = useState(false)

  // 用户角色分配
  const [assignUserId, setAssignUserId] = useState('')
  const [assignRole, setAssignRole] = useState('')
  const [assigning, setAssigning] = useState(false)
  const [assignMessage, setAssignMessage] = useState('')

  // 导出中
  const [exporting, setExporting] = useState(false)

  // 加载审计日志
  const loadAuditLogs = useCallback(async () => {
    setLoadingLogs(true)
    try {
      const params: AuditLogQueryParams = {
        page,
        page_size: pageSize,
      }
      if (filterUserId) params.user_id = filterUserId
      if (filterAction) params.action = filterAction
      if (filterResult) params.result = filterResult
      if (filterStartTime) params.start_time = filterStartTime
      if (filterEndTime) params.end_time = filterEndTime

      const response = await securityAPI.getAuditLogs(params)
      setLogs(response.data.logs)
      setTotal(response.data.total)
    } catch (error) {
      appLogger.error({
        event: 'audit_logs_load_failed',
        message: 'Failed to load audit logs',
        module: 'security',
      })
    } finally {
      setLoadingLogs(false)
    }
  }, [page, pageSize, filterUserId, filterAction, filterResult, filterStartTime, filterEndTime])

  // 加载统计信息
  const loadStats = useCallback(async () => {
    setLoadingStats(true)
    try {
      const response = await securityAPI.getAuditStats()
      setStats(response.data)
    } catch (error) {
      appLogger.error({
        event: 'audit_stats_load_failed',
        message: 'Failed to load audit stats',
        module: 'security',
      })
    } finally {
      setLoadingStats(false)
    }
  }, [])

  // 加载角色列表
  const loadRoles = useCallback(async () => {
    setLoadingRoles(true)
    try {
      const response = await securityAPI.getRoles()
      setRoles(response.data)
    } catch (error) {
      appLogger.error({
        event: 'roles_load_failed',
        message: 'Failed to load roles',
        module: 'security',
      })
    } finally {
      setLoadingRoles(false)
    }
  }, [])

  useEffect(() => {
    loadAuditLogs()
    loadStats()
    loadRoles()
  }, [loadAuditLogs, loadStats, loadRoles])

  // 搜索/筛选
  const handleSearch = () => {
    setPage(1)
    loadAuditLogs()
  }

  // 重置筛选
  const handleReset = () => {
    setFilterUserId('')
    setFilterAction('')
    setFilterResult('')
    setFilterStartTime('')
    setFilterEndTime('')
    setPage(1)
  }

  // 导出日志
  const handleExport = async () => {
    setExporting(true)
    try {
      const params: AuditLogQueryParams = {}
      if (filterUserId) params.user_id = filterUserId
      if (filterAction) params.action = filterAction
      if (filterStartTime) params.start_time = filterStartTime
      if (filterEndTime) params.end_time = filterEndTime

      const response = await securityAPI.exportAuditLogs(params)
      const blob = new Blob([response.data], { type: 'application/x-jsonlines' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'audit_logs.jsonl'
      a.click()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      appLogger.error({
        event: 'audit_export_failed',
        message: 'Failed to export audit logs',
        module: 'security',
      })
    } finally {
      setExporting(false)
    }
  }

  // 分配用户角色
  const handleAssignRole = async () => {
    if (!assignUserId || !assignRole) {
      setAssignMessage('请填写用户 ID 并选择角色')
      return
    }
    setAssigning(true)
    setAssignMessage('')
    try {
      await securityAPI.setUserRole(assignUserId, assignRole)
      setAssignMessage('角色分配成功')
      setAssignUserId('')
      setAssignRole('')
    } catch (error) {
      setAssignMessage('角色分配失败，请检查权限')
    } finally {
      setAssigning(false)
    }
  }

  const totalPages = Math.ceil(total / pageSize)

  // 格式化时间
  const formatTime = (time: string | null) => {
    if (!time) return '-'
    try {
      return new Date(time).toLocaleString('zh-CN')
    } catch {
      return time
    }
  }

  return (
    <div className={styles['security-settings']}>
      {/* 统计卡片 */}
      <div>
        <h3 className={styles['section-title']}>审计概览</h3>
        {loadingStats ? (
          <div className={styles['loading-message']}>加载统计中...</div>
        ) : stats ? (
          <div className={styles['stats-cards']}>
            <div className={styles['stat-card']}>
              <h4>总操作数</h4>
              <div className={styles['stat-value']}>{stats.total}</div>
            </div>
            <div className={styles['stat-card']}>
              <h4>成功率</h4>
              <div className={styles['stat-value']}>{stats.success_rate}%</div>
            </div>
            <div className={styles['stat-card']}>
              <h4>成功操作</h4>
              <div className={styles['stat-value']}>{stats.success_count}</div>
            </div>
            <div className={styles['stat-card']}>
              <h4>最活跃用户</h4>
              <div className={styles['stat-value']}>
                {stats.top_users.length > 0 ? stats.top_users[0].user_id : '-'}
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {/* RBAC 角色管理 */}
      <div>
        <h3 className={styles['section-title']}>角色管理</h3>
        {loadingRoles ? (
          <div className={styles['loading-message']}>加载角色中...</div>
        ) : (
          <div className={styles['role-list']}>
            {roles.map((role) => (
              <div key={role.name} className={styles['role-card']}>
                <div className={styles['role-card-header']}>
                  <h4>{role.display_name || role.name}</h4>
                  <span>{role.name}</span>
                </div>
                <div className={styles['permission-tags']}>
                  {role.permissions.map((perm) => (
                    <span key={perm} className={styles['permission-tag']}>
                      {perm}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 用户角色分配 */}
        <h4 className={styles['sub-title']} style={{ marginTop: '16px' }}>
          用户角色分配
        </h4>
        <div className={styles['role-assign-form']}>
          <div className={styles['filter-group']}>
            <label>用户 ID</label>
            <input
              type="text"
              value={assignUserId}
              onChange={(e) => setAssignUserId(e.target.value)}
              placeholder="输入用户 ID"
            />
          </div>
          <div className={styles['filter-group']}>
            <label>选择角色</label>
            <select
              value={assignRole}
              onChange={(e) => setAssignRole(e.target.value)}
            >
              <option value="">请选择</option>
              {roles.map((role) => (
                <option key={role.name} value={role.name}>
                  {role.display_name || role.name}
                </option>
              ))}
            </select>
          </div>
          <button
            className="btn btn-primary"
            onClick={handleAssignRole}
            disabled={assigning}
          >
            {assigning ? '分配中...' : '分配角色'}
          </button>
        </div>
        {assignMessage && (
          <div style={{ marginTop: '8px', fontSize: '13px', color: 'var(--color-text-secondary)' }}>
            {assignMessage}
          </div>
        )}
      </div>

      {/* 审计日志 */}
      <div>
        <h3 className={styles['section-title']}>审计日志</h3>

        {/* 筛选器 */}
        <div className={styles['filters']}>
          <div className={styles['filter-group']}>
            <label>用户 ID</label>
            <input
              type="text"
              value={filterUserId}
              onChange={(e) => setFilterUserId(e.target.value)}
              placeholder="筛选用户"
            />
          </div>
          <div className={styles['filter-group']}>
            <label>操作类型</label>
            <input
              type="text"
              value={filterAction}
              onChange={(e) => setFilterAction(e.target.value)}
              placeholder="如 auth:login"
            />
          </div>
          <div className={styles['filter-group']}>
            <label>结果</label>
            <select
              value={filterResult}
              onChange={(e) => setFilterResult(e.target.value)}
            >
              <option value="">全部</option>
              <option value="success">成功</option>
              <option value="failure">失败</option>
            </select>
          </div>
          <div className={styles['filter-group']}>
            <label>开始时间</label>
            <input
              type="datetime-local"
              value={filterStartTime}
              onChange={(e) => setFilterStartTime(e.target.value)}
            />
          </div>
          <div className={styles['filter-group']}>
            <label>结束时间</label>
            <input
              type="datetime-local"
              value={filterEndTime}
              onChange={(e) => setFilterEndTime(e.target.value)}
            />
          </div>
          <div className={styles['filter-actions']}>
            <button className="btn btn-primary" onClick={handleSearch}>
              查询
            </button>
            <button className="btn" onClick={handleReset}>
              重置
            </button>
            <button
              className="btn"
              onClick={handleExport}
              disabled={exporting}
            >
              {exporting ? '导出中...' : '导出'}
            </button>
          </div>
        </div>

        {/* 日志表格 */}
        {loadingLogs ? (
          <div className={styles['loading-message']}>加载日志中...</div>
        ) : logs.length === 0 ? (
          <div className={styles['empty-message']}>暂无审计日志</div>
        ) : (
          <>
            <div className={styles['audit-table-container']}>
              <table className={styles['audit-table']}>
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>用户</th>
                    <th>操作</th>
                    <th>资源</th>
                    <th>结果</th>
                    <th>IP</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => (
                    <tr key={log.id}>
                      <td>{formatTime(log.created_at)}</td>
                      <td>{log.user_id || '-'}</td>
                      <td>{log.action}</td>
                      <td>{log.resource || '-'}</td>
                      <td>
                        <span
                          className={`${styles['result-badge']} ${
                            log.result === 'success'
                              ? styles['result-success']
                              : styles['result-failure']
                          }`}
                        >
                          {log.result === 'success' ? '成功' : '失败'}
                        </span>
                      </td>
                      <td>{log.ip_address || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* 分页 */}
            <div className={styles['pagination']}>
              <span className={styles['pagination-info']}>
                共 {total} 条，第 {page}/{totalPages} 页
              </span>
              <div className={styles['pagination-buttons']}>
                <button
                  className="btn"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  上一页
                </button>
                <button
                  className="btn"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default SecuritySettings
