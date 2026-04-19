import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Blocks, ShoppingCart, Settings as SettingsIcon } from 'lucide-react'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import { Plugin } from '@/features/dashboard/dashboard'
import PluginDebugPanel from '@/features/plugins/PluginDebugPanel'
import {
  usePluginDelete,
  usePluginImport,
  usePluginList,
  usePluginPermissions,
  usePluginToggle,
  useDiscoveredPlugins,
} from '@/features/plugins/hooks'
import { pluginsAPI } from '@/shared/api/api'
import { useToast } from '@/shared/components/Toast'
import styles from './PluginsPage.module.css'

const MAX_PLUGIN_UPLOAD_SIZE = 50 * 1024 * 1024
const ALLOWED_PLUGIN_MIME_TYPES = new Set([
  'application/zip',
  'application/x-zip-compressed',
  'multipart/x-zip',
])

function PluginsPage() {
  const navigate = useNavigate()
  const { plugins, loading, error: listError, retry: retryLoadPlugins, refresh: refreshPlugins } = usePluginList()
  const {
    loading: importing,
    error: importError,
    retry: retryImport,
    importFromFile,
    importFromUrl,
  } = usePluginImport()
  const {
    loading: deleting,
    error: deleteError,
    retry: retryDelete,
    deleteOne,
    deleteBatch,
  } = usePluginDelete()
  const {
    loading: toggling,
    error: toggleError,
    retry: retryToggle,
    toggle,
  } = usePluginToggle()
  const {
    loading: permissionLoading,
    error: permissionError,
    retry: retryPermission,
    permissionStatusMap,
    refreshPermissions,
    authorizePermissions,
    revokePermissions,
  } = usePluginPermissions()
  const {
    discovered,
    loading: discoverLoading,
    error: discoverError,
    refresh: refreshDiscovered,
  } = useDiscoveredPlugins()
  const { addToast, ToastContainer } = useToast()
  const [permissionMessage, setPermissionMessage] = useState('')
  const [permissionModalOpen, setPermissionModalOpen] = useState(false)
  const [selectedPlugin, setSelectedPlugin] = useState<Plugin | null>(null)
  const [debugPluginId, setDebugPluginId] = useState<string | null>(null)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [remoteUrl, setRemoteUrl] = useState('')
  const [expandedDescriptions, setExpandedDescriptions] = useState<Record<string, boolean>>({})
  const [installingPlugins, setInstallingPlugins] = useState<Set<string>>(new Set())
  const fileInputRef = useRef<HTMLInputElement>(null)

  const filteredPlugins = useMemo(() => {
    const keyword = searchKeyword.trim().toLowerCase()
    if (!keyword) return plugins
    return plugins.filter((plugin) => {
      const description = getPluginDescription(plugin).toLowerCase()
      const author = getPluginAuthor(plugin).toLowerCase()
      return (
        plugin.name.toLowerCase().includes(keyword) ||
        String(plugin.version || '').toLowerCase().includes(keyword) ||
        description.includes(keyword) ||
        author.includes(keyword)
      )
    })
  }, [plugins, searchKeyword])

  /** 过滤出未注册到数据库的本地插件（已发现但未安装） */
  const unregisteredPlugins = useMemo(() => {
    const registeredNames = new Set(plugins.map((p) => p.name.toLowerCase()))
    return discovered.filter((d) => !registeredNames.has(d.name.toLowerCase()))
  }, [discovered, plugins])

  /** 安装本地发现的插件到数据库 */
  const handleInstallLocal = async (pluginName: string, pluginVersion: string) => {
    setInstallingPlugins((prev) => new Set(prev).add(pluginName))
    try {
      await pluginsAPI.install({ name: pluginName, version: pluginVersion, config: {} })
      await refreshPlugins()
      await refreshDiscovered()
      addToast(`插件 "${pluginName}" 安装成功`, 'success')
    } catch {
      addToast(`插件 "${pluginName}" 安装失败`, 'error')
    } finally {
      setInstallingPlugins((prev) => {
        const next = new Set(prev)
        next.delete(pluginName)
        return next
      })
    }
  }

  const refreshPluginPermissions = async (plugin: Plugin) => {
    return refreshPermissions(plugin)
  }

  const openPermissionModal = async (plugin: Plugin) => {
    setSelectedPlugin(plugin)
    setPermissionModalOpen(true)
    setPermissionMessage('')
    await refreshPluginPermissions(plugin)
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
      await authorizePermissions(selectedPlugin.id, missing)
      setPermissionMessage('权限授权成功')
      await refreshPluginPermissions(selectedPlugin)
    } catch {
      setPermissionMessage('权限授权失败')
    }
  }

  const handleRevokePermission = async (permission: string) => {
    if (!selectedPlugin) return

    try {
      await revokePermissions(selectedPlugin.id, [permission])
      setPermissionMessage(`已撤销权限: ${permission}`)
      await refreshPluginPermissions(selectedPlugin)
    } catch {
      setPermissionMessage('权限撤销失败')
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

      await toggle(plugin.id)
      await refreshPlugins()
    } catch (error) {
      addToast('插件状态切换失败', 'error')
    }
  }

  const handleUninstall = async (id: string) => {
    if (!confirm('确定要卸载这个插件吗？')) return
    try {
      await deleteOne(id)
      setSelectedIds((prev) => prev.filter((item) => item !== id))
      await refreshPlugins()
      addToast('插件删除成功', 'success')
    } catch {
      addToast('插件删除失败', 'error')
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0]
      const isZipExtension = file.name.toLowerCase().endsWith('.zip')
      const isAllowedMimeType = !file.type || ALLOWED_PLUGIN_MIME_TYPES.has(file.type)

      if (!isZipExtension || !isAllowedMimeType) {
        alert('只支持 .zip 格式的插件包')
        return
      }
      if (file.size <= 0 || file.size > MAX_PLUGIN_UPLOAD_SIZE) {
        alert('插件包大小无效或已超过 50MB 限制')
        return
      }

      try {
        await importFromFile(file)
        await refreshPlugins()
        addToast('插件导入成功', 'success')
      } catch {
        addToast('插件导入失败', 'error')
      } finally {
        if (fileInputRef.current) fileInputRef.current.value = ''
      }
    }
  }

  const handleImportByUrl = async () => {
    const trimmedUrl = remoteUrl.trim()
    if (!trimmedUrl) {
      addToast('请输入远程 URL', 'warning')
      return
    }
    try {
      await importFromUrl(trimmedUrl)
      setRemoteUrl('')
      await refreshPlugins()
      addToast('远程 URL 导入成功', 'success')
    } catch {
      addToast('远程 URL 导入失败', 'error')
    }
  }

  const handleToggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds(filteredPlugins.map((plugin) => plugin.id))
      return
    }
    setSelectedIds([])
  }

  const handleToggleSelectOne = (pluginId: string, checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => (prev.includes(pluginId) ? prev : [...prev, pluginId]))
      return
    }
    setSelectedIds((prev) => prev.filter((id) => id !== pluginId))
  }

  const handleBatchDelete = async () => {
    if (selectedIds.length === 0) return
    if (!confirm(`确定要批量删除 ${selectedIds.length} 个插件吗？`)) return
    try {
      const result = await deleteBatch(selectedIds)
      await refreshPlugins()
      setSelectedIds([])
      if (result.failed.length === 0) {
        addToast(`已批量删除 ${result.successIds.length} 个插件`, 'success')
      } else {
        addToast(`批量删除完成，成功 ${result.successIds.length}，失败 ${result.failed.length}`, 'warning')
      }
    } catch {
      addToast('批量删除失败', 'error')
    }
  }

  const allFilteredSelected = filteredPlugins.length > 0 && filteredPlugins.every((item) => selectedIds.includes(item.id))

  if (loading) {
    return <div className={styles['loading']}>加载中...</div>
  }

  const selectedPermissionStatus = selectedPlugin ? permissionStatusMap[selectedPlugin.id] : undefined

  const renderSecondarySidebar = () => {
    return (
      <div className={styles['secondary-nav']}>
        <button
          className={`${styles['nav-item']} ${styles['active']}`}
          onClick={() => navigate('/plugins/manage')}
        >
          <Blocks size={18} />
          <span>我的插件</span>
        </button>
        <button
          className={`${styles['nav-item']}`}
          onClick={() => navigate('/plugins/config/default')}
        >
          <SettingsIcon size={18} />
          <span>插件配置</span>
        </button>
        <button
          className={`${styles['nav-item']}`}
          onClick={() => navigate('/marketplace')}
        >
          <ShoppingCart size={18} />
          <span>插件市场</span>
        </button>
      </div>
    )
  }

  return (
    <PageLayout
      title="插件管理"
      secondarySidebar={renderSecondarySidebar()}
      className={styles['plugins-page']}
      actions={
        <>
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: 'none' }}
            accept=".zip"
            onChange={handleFileUpload}
          />
          <button
            className={`btn btn-primary`}
            onClick={() => fileInputRef.current?.click()}
            disabled={importing}
          >
            {importing ? '导入中...' : '导入插件'}
          </button>
          <input
            className={styles['url-input']}
            placeholder="输入远程 ZIP URL（支持白名单域名）"
            value={remoteUrl}
            onChange={(e) => setRemoteUrl(e.target.value)}
          />
          <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={handleImportByUrl} disabled={importing}>
            URL 导入
          </button>
        </>
      }
    >
      <div className={styles['toolbar']}>
        <input
          className={styles['search-input']}
          placeholder="搜索插件名称 / 版本 / 作者 / 简介"
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
        />
        <label className={styles['select-all']}>
          <input
            type="checkbox"
            checked={allFilteredSelected}
            onChange={(e) => handleToggleSelectAll(e.target.checked)}
          />
          全选当前结果
        </label>
        <button
          className={`btn ${styles['btn-danger'] || 'btn-danger'}`}
          onClick={handleBatchDelete}
          disabled={selectedIds.length === 0 || deleting}
        >
          {deleting ? '删除中...' : `批量删除(${selectedIds.length})`}
        </button>
      </div>

      {(listError || importError || deleteError || permissionError || toggleError) && (
        <div className={styles['inline-error']}>
          <span>{listError || importError || deleteError || permissionError || toggleError}</span>
          <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={() => {
            if (listError) retryLoadPlugins()
            if (importError) retryImport()
            if (deleteError) retryDelete()
            if (permissionError) retryPermission()
            if (toggleError) retryToggle()
          }}>
            重试
          </button>
        </div>
      )}

      <div className={styles['plugins-grid']}>
        {filteredPlugins.length === 0 ? (
          <div className={styles['empty-state']}>
            <p>{plugins.length === 0 ? '还没有安装任何插件' : '没有匹配的插件'}</p>
            <button
              className={`btn btn-primary`}
              onClick={() => fileInputRef.current?.click()}
              disabled={importing}
            >
              {importing ? '导入中...' : '导入插件'}
            </button>
          </div>
        ) : (
          filteredPlugins.map((plugin) => {
            const permissionStatus = permissionStatusMap[plugin.id]
            const missingCount = permissionStatus?.missing_permissions.length || 0
            const description = getPluginDescription(plugin)
            const author = getPluginAuthor(plugin)
            const expanded = !!expandedDescriptions[plugin.id]

            return (
              <div key={plugin.id} className={styles['plugin-card']}>
                <div className={styles['plugin-header']}>
                  <label className={styles['plugin-select']}>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(plugin.id)}
                      onChange={(e) => handleToggleSelectOne(plugin.id, e.target.checked)}
                    />
                  </label>
                  <h3>{plugin.name}</h3>
                  <span className={styles['plugin-version']}>v{plugin.version || '1.0.0'}</span>
                </div>
                <div className={styles['plugin-meta']}>作者：{author}</div>
                <div className={styles['plugin-description']}>
                  {expanded ? description : (description.slice(0, 80) || '暂无简介')}
                  {description.length > 80 && (
                    <button
                      className={styles['description-toggle']}
                      onClick={() => {
                        setExpandedDescriptions((prev) => ({ ...prev, [plugin.id]: !expanded }))
                      }}
                    >
                      {expanded ? '收起简介' : '查看简介'}
                    </button>
                  )}
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
                    className={`btn ${plugin.enabled ? styles['btn-secondary'] : styles['btn-primary']}`}
                    onClick={() => handleToggle(plugin)}
                    disabled={toggling}
                  >
                    {plugin.enabled ? '禁用' : '启用'}
                  </button>
                  <button
                    className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                    onClick={() => openPermissionModal(plugin)}
                  >
                    权限
                  </button>
                  <button
                    className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                    onClick={() => setDebugPluginId(debugPluginId === plugin.id ? null : plugin.id)}
                  >
                    {debugPluginId === plugin.id ? '关闭调试' : '调试'}
                  </button>
                  <button
                    className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                    onClick={() => navigate(`/plugins/config/${plugin.id}`)}
                  >
                    配置
                  </button>
                  <button
                    className={`btn ${styles['btn-danger'] || 'btn-danger'}`}
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

      {/* 本地可用插件区域 */}
      <div className={styles['local-plugins-section']}>
        <h2 className={styles['section-title']}>本地可用插件</h2>
        {discoverLoading ? (
          <div className={styles['local-loading']}>扫描本地插件中...</div>
        ) : discoverError ? (
          <div className={styles['inline-error']}>
            <span>{discoverError}</span>
            <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={refreshDiscovered}>重试</button>
          </div>
        ) : unregisteredPlugins.length === 0 ? (
          <div className={styles['local-empty']}>所有本地插件均已安装</div>
        ) : (
          <div className={styles['plugins-grid']}>
            {unregisteredPlugins.map((dp) => (
              <div key={dp.name} className={`${styles['plugin-card']} ${styles['local-card']}`}>
                <div className={styles['plugin-header']}>
                  <h3>{dp.name}</h3>
                  <span className={styles['plugin-version']}>v{dp.version || '1.0.0'}</span>
                </div>
                <div className={styles['plugin-description']}>
                  {dp.description || '暂无简介'}
                </div>
                <div className={styles['plugin-status']}>
                  <span className={`${styles['status-badge']} ${styles['local-badge']}`}>
                    未安装
                  </span>
                  {dp.state !== 'unknown' && (
                    <span className={styles['state-info']}>{dp.state}</span>
                  )}
                </div>
                <div className={styles['plugin-actions']}>
                  <button
                    className="btn btn-primary"
                    onClick={() => handleInstallLocal(dp.name, dp.version)}
                    disabled={installingPlugins.has(dp.name)}
                  >
                    {installingPlugins.has(dp.name) ? '安装中...' : '安装'}
                  </button>
                </div>
              </div>
            ))}
          </div>
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
                            className={`btn ${styles['btn-danger'] || 'btn-danger'} ${styles['permission-revoke-btn']}`}
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
                className={`btn btn-primary`}
                onClick={handleAuthorizeMissingPermissions}
                disabled={permissionLoading}
              >
                授权缺失权限
              </button>
              <button
                className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
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
      <ToastContainer />
    </PageLayout>
  )
}

function getPluginDescription(plugin: Plugin): string {
  const direct = plugin.description
  if (typeof direct === 'string' && direct.trim()) {
    return direct
  }
  const config = plugin.config
  if (config && typeof config === 'object' && !Array.isArray(config)) {
    const configDescription = (config as { description?: unknown }).description
    if (typeof configDescription === 'string') {
      return configDescription
    }
  }
  return ''
}

function getPluginAuthor(plugin: Plugin): string {
  const author = plugin.author
  if (typeof author === 'string' && author.trim()) {
    return author
  }
  const config = plugin.config
  if (config && typeof config === 'object' && !Array.isArray(config)) {
    const configAuthor = (config as { author?: unknown }).author
    if (typeof configAuthor === 'string' && configAuthor.trim()) {
      return configAuthor
    }
  }
  return '未知'
}

export default PluginsPage
