import { useState, useEffect, useRef } from 'react'
import { pluginsAPI, PluginPermissionStatus } from '../services/api'
import { Plugin } from '../types/dashboard'
import PluginDebugPanel from '../components/PluginDebugPanel'
import './PluginsPage.css'

function PluginsPage() {
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [permissionLoading, setPermissionLoading] = useState(false)
  const [permissionMessage, setPermissionMessage] = useState('')
  const [permissionModalOpen, setPermissionModalOpen] = useState(false)
  const [selectedPlugin, setSelectedPlugin] = useState<Plugin | null>(null)
  const [permissionStatusMap, setPermissionStatusMap] = useState<Record<string, PluginPermissionStatus>>({})
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

      const formData = new FormData()
      formData.append('file', file)

      try {
        setUploading(true)
        const token = localStorage.getItem('token')
        const response = await fetch('/api/plugins/upload', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`
          },
          body: formData
        })

        if (response.ok) {
          alert('插件导入成功')
          await loadPlugins()
        } else {
          const data = await response.json()
          alert(`插件导入失败: ${data.detail || '未知错误'}`)
        }
      } catch (error) {
        console.error('Failed to upload plugin:', error)
        alert('插件导入失败')
      } finally {
        setUploading(false)
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
      }
    }
  }

  if (loading) {
    return <div className="loading">加载中...</div>
  }

  const selectedPermissionStatus = selectedPlugin ? permissionStatusMap[selectedPlugin.id] : undefined

  return (
    <div className="plugins-page">
      <div className="page-header">
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
            className="btn btn-primary"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? '导入中...' : '导入插件'}
          </button>
          <button className="btn btn-secondary">浏览插件市场</button>
        </div>
      </div>

      <div className="plugins-grid">
        {plugins.length === 0 ? (
          <div className="empty-state">
            <p>还没有安装任何插件</p>
            <button
              className="btn btn-primary"
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
              <div key={plugin.id} className="plugin-card">
                <div className="plugin-header">
                  <h3>{plugin.name}</h3>
                  <span className="plugin-version">v{plugin.version || '1.0.0'}</span>
                </div>
                <div className="plugin-status">
                  <span className={`status-badge ${plugin.enabled ? 'enabled' : 'disabled'}`}>
                    {plugin.enabled ? '已启用' : '已禁用'}
                  </span>
                  {missingCount > 0 && (
                    <span className="permission-badge">待授权 {missingCount}</span>
                  )}
                </div>
                <div className="plugin-actions">
                  <button
                    className={`btn ${plugin.enabled ? 'btn-secondary' : 'btn-primary'}`}
                    onClick={() => handleToggle(plugin)}
                  >
                    {plugin.enabled ? '禁用' : '启用'}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => openPermissionModal(plugin)}
                  >
                    权限
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => setDebugPluginId(debugPluginId === plugin.id ? null : plugin.id)}
                  >
                    {debugPluginId === plugin.id ? '关闭调试' : '调试'}
                  </button>
                  <button
                    className="btn btn-danger"
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
        <div className="permission-modal-overlay" role="dialog" aria-modal="true">
          <div className="permission-modal">
            <h3>插件权限</h3>
            <p className="permission-modal-plugin">{selectedPlugin.name}</p>

            {permissionLoading ? (
              <div className="permission-loading">权限加载中...</div>
            ) : (
              <>
                <div className="permission-section">
                  <div className="permission-section-title">申请权限</div>
                  {selectedPermissionStatus && selectedPermissionStatus.requested_permissions.length > 0 ? (
                    <div className="permission-list">
                      {selectedPermissionStatus.requested_permissions.map((permission) => {
                        const granted = selectedPermissionStatus.granted_permissions.includes(permission)
                        return (
                          <div key={permission} className="permission-item">
                            <span>{permission}</span>
                            <span className={granted ? 'permission-granted' : 'permission-missing'}>
                              {granted ? '已授权' : '待授权'}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="permission-empty">当前插件未声明敏感权限</div>
                  )}
                </div>

                {selectedPermissionStatus && selectedPermissionStatus.granted_permissions.length > 0 && (
                  <div className="permission-section">
                    <div className="permission-section-title">已授权权限</div>
                    <div className="permission-list">
                      {selectedPermissionStatus.granted_permissions.map((permission) => (
                        <div key={`granted-${permission}`} className="permission-item">
                          <span>{permission}</span>
                          <button
                            className="btn btn-danger permission-revoke-btn"
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

            {permissionMessage && <div className="permission-message">{permissionMessage}</div>}

            <div className="permission-actions">
              <button
                className="btn btn-primary"
                onClick={handleAuthorizeMissingPermissions}
                disabled={permissionLoading}
              >
                授权缺失权限
              </button>
              <button
                className="btn btn-secondary"
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
