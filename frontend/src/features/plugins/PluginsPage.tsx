import { useState, useEffect, useRef } from 'react'
import { pluginsAPI, PluginPermissionStatus } from '@/shared/api/api'
import { Plugin } from '@/features/dashboard/dashboard'
import PluginDebugPanel from '@/features/plugins/PluginDebugPanel'
import styles from './PluginsPage.module.css'

function PluginsPage() {
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [permissionLoading, setPermissionLoading] = useState(false)
  const [permissionMessage, setPermissionMessage] = useState('')
  const [permissionModalOpen, setPermissionModalOpen] = useState(false)
  const [selectedPlugin, setSelectedPlugin] = useState<Plugin | null>(null)
  const [permissionStatusMap, setPermissionStatusMap] = useState<Record<string, PluginPermissionStatus>>({})
  const [debugPluginId, setDebugPluginId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    loadPlugins()
  }, [])

  const loadPlugins = async () => {
    try {
      const response = await pluginsAPI.getAll()
      setPlugins(response.data)
    } catch (error) {
      throw error
    } finally {
      setLoading(false)
    }
  }

  const refreshPluginPermissions = async (plugin: Plugin): Promise<PluginPermissionStatus | null> => {
    try {
      const response = await pluginsAPI.getPermissions(plugin.id)
      const status = response.data
      setPermissionStatusMap(prev => ({ ...prev, [plugin.id]: status }))
      return status
    } catch {
      setPermissionStatusMap(prev => ({
        ...prev,
        [plugin.id]: {
          plugin_id: plugin.id,
          plugin_name: plugin.name,
          requested_permissions: [],
          granted_permissions: [],
          missing_permissions: [],
        },
      }))
      return null
    }
  }

  const openPermissionModal = async (plugin: Plugin) => {
    setSelectedPlugin(plugin)
    setPermissionModalOpen(true)
    setPermissionMessage('')
    setPermissionLoading(true)
    await refreshPluginPermissions(plugin)
    setPermissionLoading(false)
  }

  const handleAuthorizeMissingPermissions = async () => {
    if (!selectedPlugin) return
    const status = permissionStatusMap[selectedPlugin.id]
    const missing = status?.missing_permissions || []
    if (missing.length === 0) {
      setPermissionMessage('当前无需新增授权')
      return
    }

    try {
      setPermissionLoading(true)
      await pluginsAPI.authorizePermissions(selectedPlugin.id, missing)
      setPermissionMessage('权限授权成功')
      await refreshPluginPermissions(selectedPlugin)
    } catch {
      setPermissionMessage('权限授权失败')
    } finally {
      setPermissionLoading(false)
    }
  }

  const handleRevokePermission = async (permission: string) => {
    if (!selectedPlugin) return

    try {
      setPermissionLoading(true)
      await pluginsAPI.revokePermissions(selectedPlugin.id, [permission])
      setPermissionMessage(`已撤销权限: ${permission}`)
      await refreshPluginPermissions(selectedPlugin)
    } catch {
      setPermissionMessage('权限撤销失败')
    } finally {
      setPermissionLoading(false)
    }
  }

  const handleToggle = async (plugin: Plugin) => {
    try {
      if (!plugin.enabled) {
        const status = await refreshPluginPermissions(plugin)
        if (status && status.missing_permissions.length > 0) {
          await openPermissionModal(plugin)
          return
        }
      }

      await pluginsAPI.toggle(plugin.id)
      await loadPlugins()
    } catch (error) {
      throw error
    }
  }

  const handleUninstall = async (id: string) => {
    if (!confirm('确定要卸载这个插件吗？')) return
    try {
      await pluginsAPI.uninstall(id)
      await loadPlugins()
    } catch (error) {
      throw error
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0]
      if (!file.name.endsWith('.zip')) {
        alert('只支持 .zip 格式的插件包')
        return
      }

      try {
        setUploading(true)
        await pluginsAPI.upload(file)
        alert('插件导入成功')
        await loadPlugins()
      } catch (error: any) {
        console.error('Failed to upload plugin:', error)
        const detail = error?.response?.data?.detail
        alert(`插件导入失败: ${detail || '未知错误'}`)
      } finally {
        setUploading(false)
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
      }
    }
  }

  if (loading) {
    return <div className={styles['loading']}>加载中...</div>
  }

  const selectedPermissionStatus = selectedPlugin ? permissionStatusMap[selectedPlugin.id] : undefined

  return (
    <div className={styles['plugins-page']}>
      <div className={styles['page-header']}>
        <h1>插件管理</h1>
        <div style={{ display: 'flex', gap: '10px' }}>
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: 'none' }}
            accept=".zip"
            onChange={handleFileUpload}
          />
          <button
            className={`${styles['btn']} ${styles['btn-primary']}`}
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? '导入中...' : '导入插件'}
          </button>
          <button className={`${styles['btn']} ${styles['btn-secondary']}`}>浏览插件市场</button>
        </div>
      </div>

      <div className={styles['plugins-grid']}>
        {plugins.length === 0 ? (
          <div className={styles['empty-state']}>
            <p>还没有安装任何插件</p>
            <button
              className={`${styles['btn']} ${styles['btn-primary']}`}
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? '导入中...' : '导入插件'}
            </button>
          </div>
        ) : (
          plugins.map((plugin) => {
            const permissionStatus = permissionStatusMap[plugin.id]
            const missingCount = permissionStatus?.missing_permissions.length || 0

            return (
              <div key={plugin.id} className={styles['plugin-card']}>
                <div className={styles['plugin-header']}>
                  <h3>{plugin.name}</h3>
                  <span className={styles['plugin-version']}>v{plugin.version || '1.0.0'}</span>
                </div>
                <div className={styles['plugin-status']}>
                  <span className={`${styles['status-badge']} ${plugin.enabled ? styles['enabled'] : styles['disabled']}`}>
                    {plugin.enabled ? '已启用' : '已禁用'}
                  </span>
                  {missingCount > 0 && (
                    <span className={styles['permission-badge']}>待授权 {missingCount}</span>
                  )}
                </div>
                <div className={styles['plugin-actions']}>
                  <button
                    className={`${styles['btn']} ${plugin.enabled ? styles['btn-secondary'] : styles['btn-primary']}`}
                    onClick={() => handleToggle(plugin)}
                  >
                    {plugin.enabled ? '禁用' : '启用'}
                  </button>
                  <button
                    className={`${styles['btn']} ${styles['btn-secondary']}`}
                    onClick={() => openPermissionModal(plugin)}
                  >
                    权限
                  </button>
                  <button
                    className={`${styles['btn']} ${styles['btn-secondary']}`}
                    onClick={() => setDebugPluginId(debugPluginId === plugin.id ? null : plugin.id)}
                  >
                    {debugPluginId === plugin.id ? '关闭调试' : '调试'}
                  </button>
                  <button
                    className={`${styles['btn']} ${styles['btn-danger']}`}
                    onClick={() => handleUninstall(plugin.id)}
                  >
                    卸载
                  </button>
                </div>
                {debugPluginId === plugin.id && (
                  <PluginDebugPanel pluginId={plugin.id} pluginName={plugin.name} />
                )}
              </div>
            )
          })
        )}
      </div>

      {permissionModalOpen && selectedPlugin && (
        <div className={styles['permission-modal-overlay']} role="dialog" aria-modal="true">
          <div className={styles['permission-modal']}>
            <h3>插件权限</h3>
            <p className={styles['permission-modal-plugin']}>{selectedPlugin.name}</p>

            {permissionLoading ? (
              <div className={styles['permission-loading']}>权限加载中...</div>
            ) : (
              <>
                <div className={styles['permission-section']}>
                  <div className={styles['permission-section-title']}>申请权限</div>
                  {selectedPermissionStatus && selectedPermissionStatus.requested_permissions.length > 0 ? (
                    <div className={styles['permission-list']}>
                      {selectedPermissionStatus.requested_permissions.map((permission) => {
                        const granted = selectedPermissionStatus.granted_permissions.includes(permission)
                        return (
                          <div key={permission} className={styles['permission-item']}>
                            <span>{permission}</span>
                            <span className={granted ? styles['permission-granted'] : styles['permission-missing']}>
                              {granted ? '已授权' : '待授权'}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <div className={styles['permission-empty']}>当前插件未声明敏感权限</div>
                  )}
                </div>

                {selectedPermissionStatus && selectedPermissionStatus.granted_permissions.length > 0 && (
                  <div className={styles['permission-section']}>
                    <div className={styles['permission-section-title']}>已授权权限</div>
                    <div className={styles['permission-list']}>
                      {selectedPermissionStatus.granted_permissions.map((permission) => (
                        <div key={`granted-${permission}`} className={styles['permission-item']}>
                          <span>{permission}</span>
                          <button
                            className={`${styles['btn']} ${styles['btn-danger']} ${styles['permission-revoke-btn']}`}
                            onClick={() => handleRevokePermission(permission)}
                          >
                            撤销
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {permissionMessage && <div className={styles['permission-message']}>{permissionMessage}</div>}

            <div className={styles['permission-actions']}>
              <button
                className={`${styles['btn']} ${styles['btn-primary']}`}
                onClick={handleAuthorizeMissingPermissions}
                disabled={permissionLoading}
              >
                授权缺失权限
              </button>
              <button
                className={`${styles['btn']} ${styles['btn-secondary']}`}
                onClick={() => {
                  setPermissionModalOpen(false)
                  setSelectedPlugin(null)
                  setPermissionMessage('')
                }}
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default PluginsPage
