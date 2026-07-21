/**
 * 已保存权限管理组件。
 * 查看和管理持久化的权限规则（"始终允许"的决策记录）。
 */
import { useState, useEffect, useCallback } from 'react'
import { securityAPI, SavedPermission } from '@/shared/api/securityApi'
import { appLogger } from '@/shared/utils/logger'
import styles from './PermissionSettings.module.css'

/** 获取操作友好显示名称 */
function getActionLabel(action: string): string {
  const actionMap: Record<string, string> = {
    'read': '读取文件',
    'write': '写入文件',
    'edit': '编辑文件',
    'execute': '执行命令',
    'bash': '执行 Shell',
    'delete': '删除文件',
    'web_search': '网页搜索',
    'web_fetch': '获取网页',
    'notify': '发送通知',
    'glob': '搜索文件',
    'grep': '搜索内容',
  }
  return actionMap[action] || action
}

function PermissionSettings() {
  const [permissions, setPermissions] = useState<SavedPermission[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  // 加载已保存权限列表
  const loadPermissions = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const response = await securityAPI.getSavedPermissions()
      setPermissions(response?.data?.permissions || [])
    } catch {
      setLoadError('加载已保存权限失败，请检查网络连接后重试')
      appLogger.error({
        event: 'saved_permissions_load_failed',
        message: '加载已保存权限失败',
        module: 'permission',
      })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadPermissions()
  }, [loadPermissions])

  // 删除单条权限
  const handleDelete = async (id: string) => {
    setDeletingId(id)
    try {
      await securityAPI.deleteSavedPermission(id)
      setPermissions((prev) => prev.filter((p) => p.id !== id))
      setMessage('权限规则已删除')
    } catch (err) {
      appLogger.error({
        event: 'saved_permission_delete_failed',
        message: '删除已保存权限失败',
        module: 'permission',
        extra: { error: err instanceof Error ? err.message : String(err), id },
      })
      setMessage('删除失败，请重试')
    } finally {
      setDeletingId(null)
    }
  }

  // 删除所有权限
  const handleDeleteAll = async () => {
    if (!confirm('确认删除所有已保存的权限规则吗？此操作不可撤销。')) return
    setLoading(true)
    try {
      await securityAPI.deleteAllSavedPermissions()
      setPermissions([])
      setMessage('所有权限规则已清除')
    } catch (err) {
      appLogger.error({
        event: 'saved_permissions_delete_all_failed',
        message: '清除所有已保存权限失败',
        module: 'permission',
        extra: { error: err instanceof Error ? err.message : String(err) },
      })
      setMessage('清除失败，请重试')
    } finally {
      setLoading(false)
    }
  }

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
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h3 className={styles.title}>已保存权限</h3>
          <p className={styles.desc}>
            管理通过"始终允许"持久化的权限规则。这些规则在每次会话中自动生效，
            无需再次确认。
          </p>
        </div>
        <button
          className={`btn ${styles.dangerBtn}`}
          onClick={handleDeleteAll}
          disabled={loading || permissions.length === 0}
        >
          清除全部
        </button>
      </div>

      {message && (
        <div className={styles.message}>{message}</div>
      )}

      {loadError && (
        <div className={styles.message} style={{ color: 'var(--color-error-strong, #dc2626)' }}>
          {loadError}
          <button
            className={`btn ${styles.deleteBtn}`}
            style={{ marginLeft: '8px' }}
            onClick={loadPermissions}
          >
            重试
          </button>
        </div>
      )}
      {loading && <div className={styles.loading}>加载中...</div>}
      {!loading && !loadError && permissions.length === 0 && (
        <div className={styles.empty}>
          <p>暂无已保存的权限规则</p>
          <p className={styles.hint}>
            当你在权限请求弹窗中选择"始终允许"后，该权限规则会出现在这里。
          </p>
        </div>
      )}
      {!loading && (!loadError || permissions.length > 0) && (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>权限操作</th>
                <th>资源</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {permissions.map((permission) => (
                <tr key={permission.id}>
                  <td>
                    <span className={styles.actionBadge}>
                      {getActionLabel(permission.action)}
                    </span>
                    <span className={styles.actionName}>({permission.action})</span>
                  </td>
                  <td className={styles.resourceCell}>{permission.resource}</td>
                  <td>{formatTime(permission.created_at)}</td>
                  <td>
                    <button
                      className={`btn ${styles.deleteBtn}`}
                      onClick={() => handleDelete(permission.id)}
                      disabled={deletingId === permission.id}
                    >
                      {deletingId === permission.id ? '...' : '删除'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default PermissionSettings
