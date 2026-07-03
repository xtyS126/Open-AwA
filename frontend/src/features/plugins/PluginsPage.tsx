import React, { useCallback, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  AtSign,
  BarChart3,
  Bug,
  CheckCircle2,
  Hand,
  Link2,
  Package,
  Pause,
  Play,
  Plus,
  Puzzle,
  RefreshCw,
  Search,
  Settings as SettingsIcon,
  Shield,
  Trash2,
  Wrench,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import { StatusBadge, Tooltip } from '@/shared/components/ui'
import { Plugin } from '@/features/dashboard/dashboard'
import PluginDebugPanel from '@/features/plugins/PluginDebugPanel'
import PluginSectionNav from '@/features/plugins/PluginSectionNav'
import {
  usePluginDelete,
  usePluginImport,
  usePluginList,
  usePluginPermissions,
  usePluginToggle,
  useDiscoveredPlugins,
} from '@/features/plugins/hooks'
import { isBuiltinPlugin, isUninstallablePlugin } from '@/features/plugins/pluginTypes'
import { pluginsAPI } from '@/shared/api/api'
import { useToast } from '@/shared/components/Toast'
import { useI18nStore } from '@/i18n'
import styles from './PluginsPage.module.css'

const MAX_PLUGIN_UPLOAD_SIZE = 50 * 1024 * 1024
const ALLOWED_PLUGIN_MIME_TYPES = new Set([
  'application/zip',
  'application/x-zip-compressed',
  'multipart/x-zip',
])

/** 从 API 错误对象中提取可读消息 —— 兼容 detail 与 error 两种字段 */
function getPluginErrorMessage(error: unknown, fallback: string): string {
  const err = error as { response?: { data?: { detail?: unknown; error?: unknown } } }
  const detail = err?.response?.data?.detail
  const errorField = err?.response?.data?.error
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (typeof errorField === 'string' && errorField.trim()) {
    return errorField
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return fallback
}

/** 插件分类对应的色板配置 */
interface PluginColorScheme {
  /** 顶部色条颜色 */
  bar: string
  /** 图标背景色 */
  iconBg: string
  /** 图标前景色 */
  iconColor: string
  /** 分类徽章背景色 */
  badgeBg: string
  /** 分类徽章文字色 */
  badgeText: string
}

/** 根据插件名与分类推断色板，对齐 Canvas 顶色条配色 */
function getPluginColorScheme(plugin: Plugin): PluginColorScheme {
  const name = plugin.name.toLowerCase()
  const category = (plugin.category || '').toLowerCase()

  if (!plugin.enabled) {
    return {
      bar: 'var(--color-text-tertiary)',
      iconBg: 'var(--color-bg-tertiary)',
      iconColor: 'var(--color-text-tertiary)',
      badgeBg: 'var(--color-bg-tertiary)',
      badgeText: 'var(--color-text-secondary)',
    }
  }

  if (name.includes('chart') || name.includes('data') || name.includes('visual') || category.includes('data')) {
    return {
      bar: 'var(--color-success)',
      iconBg: 'var(--color-success-bg)',
      iconColor: 'var(--color-success)',
      badgeBg: 'var(--color-primary-soft-bg)',
      badgeText: 'var(--color-primary)',
    }
  }

  if (name.includes('system') || name.includes('tool') || name.includes('wrench') || category.includes('system')) {
    return {
      bar: 'var(--color-chart-5)',
      iconBg: 'var(--color-tag-purple-bg)',
      iconColor: 'var(--color-chart-5)',
      badgeBg: 'var(--color-tag-purple-bg)',
      badgeText: 'var(--color-tag-purple-text)',
    }
  }

  if (name.includes('theme') || name.includes('color') || name.includes('palette') || category.includes('theme')) {
    return {
      bar: 'var(--color-chart-4)',
      iconBg: 'var(--color-warning-bg)',
      iconColor: 'var(--color-chart-4)',
      badgeBg: 'var(--color-warning-bg)',
      badgeText: 'var(--color-warning-strong)',
    }
  }

  if (name.includes('hello') || name.includes('world')) {
    return {
      bar: 'var(--color-primary)',
      iconBg: 'var(--color-primary-soft-bg)',
      iconColor: 'var(--color-primary)',
      badgeBg: 'var(--color-bg-tertiary)',
      badgeText: 'var(--color-text-secondary)',
    }
  }

  if (name.includes('social') || name.includes('twitter') || name.includes('media')) {
    return {
      bar: 'var(--color-primary)',
      iconBg: 'var(--color-info-bg)',
      iconColor: 'var(--color-primary)',
      badgeBg: 'var(--color-info-bg)',
      badgeText: 'var(--color-primary)',
    }
  }

  return {
    bar: 'var(--color-primary)',
    iconBg: 'var(--color-primary-soft-bg)',
    iconColor: 'var(--color-primary)',
    badgeBg: 'var(--color-primary-soft-bg)',
    badgeText: 'var(--color-primary)',
  }
}

/** 根据插件名推断图标，对齐 Canvas 卡片图标选择 */
function getPluginIcon(name: string): LucideIcon {
  const lower = name.toLowerCase()
  if (lower.includes('chart') || lower.includes('data') || lower.includes('visual')) return BarChart3
  if (lower.includes('system') || lower.includes('tool') || lower.includes('wrench')) return Wrench
  if (lower.includes('theme') || lower.includes('color') || lower.includes('palette')) return Hand
  if (lower.includes('social') || lower.includes('twitter') || lower.includes('media')) return AtSign
  if (lower.includes('hello') || lower.includes('world')) return Hand
  return Puzzle
}

/** 获取分类展示文案 */
function getPluginCategoryLabel(plugin: Plugin): string {
  const name = plugin.name.toLowerCase()
  const category = plugin.category || ''
  if (category === 'builtin') return '系统内置'
  if (name.includes('chart') || name.includes('data')) return '数据可视化'
  if (name.includes('system') || name.includes('tool')) return '系统'
  if (name.includes('theme') || name.includes('color')) return '外观'
  if (name.includes('twitter') || name.includes('social')) return '社交媒体'
  if (name.includes('hello') || name.includes('world')) return '示例'
  return '通用'
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

/** PluginCard 组件 Props —— 单个插件卡片所需的全部状态与回调 */
interface PluginCardProps {
  plugin: Plugin
  /** 是否受保护（内置不可卸载），决定按钮禁用状态 */
  isProtected: boolean
  /** 是否被选中（批量操作） */
  isSelected: boolean
  /** 简介是否展开 */
  isExpanded: boolean
  /** 调试面板是否激活 */
  isDebugActive: boolean
  /** 待授权权限数 */
  permissionMissingCount: number
  /** 状态切换中 */
  toggling: boolean
  /** 删除中 */
  deleting: boolean
  /** 选中状态变更 */
  onSelectChange: (checked: boolean) => void
  /** 切换简介展开 */
  onToggleDescription: () => void
  /** 切换调试面板 */
  onToggleDebug: () => void
  /** 打开权限弹窗 */
  onOpenPermission: () => void
  /** 切换启用/禁用 */
  onToggle: () => void
  /** 卸载插件 */
  onUninstall: () => void
  /** 跳转配置页 */
  onNavigateConfig: () => void
}

/**
 * PluginCard —— 单个插件卡片，使用 React.memo 优化列表渲染性能。
 *
 * 当 isProtected 为 true（内置插件）时，禁用卸载/禁用按钮并显示 Tooltip 提示，
 * 仅保留"设置"（查看配置）按钮可用。
 */
const PluginCard = React.memo(function PluginCard(props: PluginCardProps): React.ReactElement {
  const {
    plugin,
    isProtected,
    isSelected,
    isExpanded,
    isDebugActive,
    permissionMissingCount,
    toggling,
    deleting,
    onSelectChange,
    onToggleDescription,
    onToggleDebug,
    onOpenPermission,
    onToggle,
    onUninstall,
    onNavigateConfig,
  } = props
  const { t } = useI18nStore()

  const description = getPluginDescription(plugin)
  const author = getPluginAuthor(plugin)
  const colorScheme = getPluginColorScheme(plugin)
  const categoryLabel = getPluginCategoryLabel(plugin)

  const cannotDisableText = t('plugins.builtin.cannotDisable')

  /** 包裹受保护按钮：禁用态 + Tooltip 提示 */
  const renderProtectedAction = (
    button: React.ReactNode,
    tooltipText: string,
  ): React.ReactNode => {
    if (!isProtected) {
      return button
    }
    return (
      <Tooltip content={tooltipText} position="top">
        {button}
      </Tooltip>
    )
  }

  return (
    <div className={`${styles['plugin-card']} ${isProtected ? styles['builtin-card'] : ''}`}>
      {/* 顶部色条 —— 按分类着色 */}
      <div className={styles['card-color-bar']} style={{ background: colorScheme.bar }} />
      <div className={styles['card-body']}>
        {/* 卡片头部 —— 图标 + 名称 + 版本 + 分类 + 状态徽章 */}
        <div className={styles['card-header']}>
          <div className={styles['card-header-left']}>
            {/* 内置插件不渲染复选框（不可批量删除） */}
            {!isProtected && (
              <label className={styles['card-checkbox']}>
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={(e) => onSelectChange(e.target.checked)}
                />
              </label>
            )}
            <div
              className={styles['plugin-icon-box']}
              style={{ background: colorScheme.iconBg, color: colorScheme.iconColor }}
            >
              {React.createElement(getPluginIcon(plugin.name), { size: 20 })}
            </div>
            <div>
              <div className={styles['plugin-name-row']}>
                <span className={styles['plugin-name']}>{plugin.name}</span>
                <span className={styles['version-badge']}>v{plugin.version || '1.0.0'}</span>
                {isProtected && (
                  <Tooltip content={t('plugins.builtin.shieldTooltip')} position="top">
                    <span className={styles['builtin-shield-badge']}>
                      <Shield size={11} />
                    </span>
                  </Tooltip>
                )}
              </div>
              <span
                className={styles['category-badge']}
                style={{ background: colorScheme.badgeBg, color: colorScheme.badgeText }}
              >
                {categoryLabel}
              </span>
            </div>
          </div>
          <div className={styles['card-header-right']}>
            <StatusBadge
              status={plugin.enabled ? 'active' : 'inactive'}
              label={plugin.enabled ? '已启用' : '已停用'}
            />
          </div>
        </div>

        {/* 作者信息 —— 小字辅助说明 */}
        <div className={styles['plugin-author']}>
          作者：{author}
        </div>

        {/* 卡片描述 */}
        <p className={styles['card-description']}>
          {isExpanded ? (description || '暂无简介') : (description.slice(0, 80) || '暂无简介')}
          {description.length > 80 && (
            <button
              className={styles['description-toggle']}
              onClick={onToggleDescription}
            >
              {isExpanded ? '收起简介' : '查看简介'}
            </button>
          )}
        </p>

        {/* 权限待授权提示 */}
        {permissionMissingCount > 0 && (
          <div className={styles['permission-hint']}>
            <Shield size={12} />
            待授权 {permissionMissingCount} 项权限
          </div>
        )}

        {/* 卡片底部操作区 —— 设置/调试/权限/启用或禁用/卸载 */}
        <div className={styles['card-footer']}>
          <button
            className={`${styles['action-btn']} ${styles['action-btn-neutral']}`}
            onClick={onNavigateConfig}
          >
            <SettingsIcon size={14} />
            设置
          </button>
          <button
            className={`${styles['action-btn']} ${styles['action-btn-neutral']}`}
            onClick={onToggleDebug}
          >
            <Bug size={14} />
            {isDebugActive ? '收起调试' : '调试'}
          </button>
          <button
            className={`${styles['action-btn']} ${styles['action-btn-neutral']}`}
            onClick={onOpenPermission}
          >
            <Shield size={14} />
            权限
          </button>
          {plugin.enabled ? (
            renderProtectedAction(
              <button
                className={`${styles['action-btn']} ${styles['action-btn-warning']}`}
                onClick={onToggle}
                disabled={isProtected || toggling}
                aria-label={isProtected ? cannotDisableText : undefined}
                aria-disabled={isProtected}
              >
                <Pause size={14} />
                禁用
              </button>,
              cannotDisableText,
            )
          ) : (
            renderProtectedAction(
              <button
                className={`${styles['action-btn']} ${styles['action-btn-success']}`}
                onClick={onToggle}
                disabled={isProtected || toggling}
                aria-label={isProtected ? cannotDisableText : undefined}
                aria-disabled={isProtected}
              >
                <Play size={14} />
                启用
              </button>,
              cannotDisableText,
            )
          )}
          {!isProtected && (
            <button
              className={`${styles['action-btn']} ${styles['action-btn-danger']}`}
              onClick={onUninstall}
              disabled={deleting}
            >
              <Trash2 size={14} />
              卸载
            </button>
          )}
        </div>

        {/* 调试面板 */}
        {isDebugActive && (
          <div className={styles['debug-panel']}>
            <PluginDebugPanel pluginId={plugin.id} pluginName={plugin.name} />
          </div>
        )}
      </div>
    </div>
  )
})

function PluginsPage() {
  const navigate = useNavigate()
  const { t } = useI18nStore()
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

  /** 按来源分组：用户插件与系统内置插件分开渲染 */
  const groupedPlugins = useMemo(() => {
    const userPlugins = filteredPlugins.filter((p) => !isBuiltinPlugin(p))
    const builtinPlugins = filteredPlugins.filter((p) => isBuiltinPlugin(p))
    return { userPlugins, builtinPlugins }
  }, [filteredPlugins])

  /** 统计概览数据 */
  const stats = useMemo(() => {
    const total = plugins.length
    const enabled = plugins.filter((p) => p.enabled).length
    const disabled = total - enabled
    return { total, enabled, disabled }
  }, [plugins])

  /** 过滤出未注册到数据库的本地插件（已发现但未安装） */
  const unregisteredPlugins = useMemo(() => {
    const registeredNames = new Set(plugins.map((p) => p.name.toLowerCase()))
    return discovered.filter((d) => !registeredNames.has(d.name.toLowerCase()))
  }, [discovered, plugins])

  /** 安装本地发现的插件到数据库 */
  const handleInstallLocal = useCallback(async (pluginName: string, pluginVersion: string) => {
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
  }, [refreshPlugins, refreshDiscovered, addToast])

  const refreshPluginPermissions = useCallback(async (plugin: Plugin) => {
    return refreshPermissions(plugin)
  }, [refreshPermissions])

  const openPermissionModal = useCallback(async (plugin: Plugin) => {
    setSelectedPlugin(plugin)
    setPermissionModalOpen(true)
    setPermissionMessage('')
    await refreshPluginPermissions(plugin)
  }, [refreshPluginPermissions])

  const handleAuthorizeMissingPermissions = useCallback(async () => {
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
  }, [selectedPlugin, permissionStatusMap, authorizePermissions, refreshPluginPermissions])

  const handleRevokePermission = useCallback(async (permission: string) => {
    if (!selectedPlugin) return

    try {
      await revokePermissions(selectedPlugin.id, [permission])
      setPermissionMessage(`已撤销权限: ${permission}`)
      await refreshPluginPermissions(selectedPlugin)
    } catch {
      setPermissionMessage('权限撤销失败')
    }
  }, [selectedPlugin, revokePermissions, refreshPluginPermissions])

  const handleToggle = useCallback(async (plugin: Plugin) => {
    // 内置插件前端拦截，不发起请求
    if (isUninstallablePlugin(plugin)) {
      addToast(t('plugins.builtin.cannotDisable'), 'warning')
      return
    }
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
      // 后端返回 403 时显示具体错误信息
      addToast(getPluginErrorMessage(error, '插件状态切换失败'), 'error')
    }
  }, [refreshPluginPermissions, openPermissionModal, toggle, refreshPlugins, addToast, t])

  const handleUninstall = useCallback(async (plugin: Plugin) => {
    // 内置插件前端拦截
    if (isUninstallablePlugin(plugin)) {
      addToast(t('plugins.builtin.cannotUninstall'), 'warning')
      return
    }
    if (!confirm('确定要卸载这个插件吗？')) return
    try {
      await deleteOne(plugin.id)
      setSelectedIds((prev) => prev.filter((item) => item !== plugin.id))
      await refreshPlugins()
      addToast('插件删除成功', 'success')
    } catch (error) {
      // 后端返回 403 时显示具体错误信息（如"内置插件不可卸载"）
      addToast(getPluginErrorMessage(error, '插件删除失败'), 'error')
    }
  }, [deleteOne, refreshPlugins, addToast, t])

  const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
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
  }, [importFromFile, refreshPlugins, addToast])

  const handleImportByUrl = useCallback(async () => {
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
  }, [remoteUrl, importFromUrl, refreshPlugins, addToast])

  const handleToggleSelectAll = useCallback((checked: boolean) => {
    // 仅选中用户插件（内置插件不可删除，不参与批量选择）
    if (checked) {
      setSelectedIds(groupedPlugins.userPlugins.map((plugin) => plugin.id))
      return
    }
    setSelectedIds([])
  }, [groupedPlugins.userPlugins])

  const handleToggleSelectOne = useCallback((pluginId: string, checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => (prev.includes(pluginId) ? prev : [...prev, pluginId]))
      return
    }
    setSelectedIds((prev) => prev.filter((id) => id !== pluginId))
  }, [])

  const handleBatchDelete = useCallback(async () => {
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
  }, [selectedIds, deleteBatch, refreshPlugins, addToast])

  const handleClickImport = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleRemoteUrlChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setRemoteUrl(e.target.value)
  }, [])

  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchKeyword(e.target.value)
  }, [])

  const handleRetryErrors = useCallback(() => {
    if (listError) retryLoadPlugins()
    if (importError) retryImport()
    if (deleteError) retryDelete()
    if (permissionError) retryPermission()
    if (toggleError) retryToggle()
  }, [listError, importError, deleteError, permissionError, toggleError, retryLoadPlugins, retryImport, retryDelete, retryPermission, retryToggle])

  const handleToggleDescription = useCallback((pluginId: string) => {
    setExpandedDescriptions((prev) => ({ ...prev, [pluginId]: !prev[pluginId] }))
  }, [])

  const handleTogglePlugin = useCallback((plugin: Plugin) => {
    handleToggle(plugin)
  }, [handleToggle])

  const handleOpenPermission = useCallback((plugin: Plugin) => {
    openPermissionModal(plugin)
  }, [openPermissionModal])

  const handleToggleDebug = useCallback((pluginId: string) => {
    setDebugPluginId((prev) => (prev === pluginId ? null : pluginId))
  }, [])

  const handleNavigateConfig = useCallback((pluginId: string) => {
    navigate(`/plugins/config/${pluginId}`)
  }, [navigate])

  const handleUninstallPlugin = useCallback((plugin: Plugin) => {
    handleUninstall(plugin)
  }, [handleUninstall])

  const handleInstallLocalPlugin = useCallback((pluginName: string, pluginVersion: string) => {
    handleInstallLocal(pluginName, pluginVersion)
  }, [handleInstallLocal])

  const handleClosePermissionModal = useCallback(() => {
    setPermissionModalOpen(false)
    setSelectedPlugin(null)
    setPermissionMessage('')
  }, [])

  /** 全选状态仅针对用户插件 */
  const allUserSelected = groupedPlugins.userPlugins.length > 0
    && groupedPlugins.userPlugins.every((item) => selectedIds.includes(item.id))

  if (loading) {
    return (
      <PageLayout
        title="插件管理"
        secondarySidebar={<PluginSectionNav />}
        className={styles['plugins-page']}
      >
        <div className={styles['loading']}>加载中...</div>
      </PageLayout>
    )
  }

  const selectedPermissionStatus = selectedPlugin ? permissionStatusMap[selectedPlugin.id] : undefined

  /** 渲染单个插件卡片 */
  const renderPluginCard = (plugin: Plugin): React.ReactNode => {
    const permissionStatus = permissionStatusMap[plugin.id]
    const missingCount = permissionStatus?.missing_permissions.length || 0
    const isProtected = isUninstallablePlugin(plugin)
    return (
      <PluginCard
        key={plugin.id}
        plugin={plugin}
        isProtected={isProtected}
        isSelected={selectedIds.includes(plugin.id)}
        isExpanded={!!expandedDescriptions[plugin.id]}
        isDebugActive={debugPluginId === plugin.id}
        permissionMissingCount={missingCount}
        toggling={toggling}
        deleting={deleting}
        onSelectChange={(checked) => handleToggleSelectOne(plugin.id, checked)}
        onToggleDescription={() => handleToggleDescription(plugin.id)}
        onToggleDebug={() => handleToggleDebug(plugin.id)}
        onOpenPermission={() => handleOpenPermission(plugin)}
        onToggle={() => handleTogglePlugin(plugin)}
        onUninstall={() => handleUninstallPlugin(plugin)}
        onNavigateConfig={() => handleNavigateConfig(plugin.id)}
      />
    )
  }

  return (
    <PageLayout
      title="插件管理"
      secondarySidebar={<PluginSectionNav />}
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
            className={`${styles['btn']} ${styles['btn-outline']}`}
            onClick={() => { void refreshPlugins() }}
            disabled={loading}
          >
            <RefreshCw size={16} />
            刷新
          </button>
          <button
            className={`${styles['btn']} ${styles['btn-primary']}`}
            onClick={handleClickImport}
            disabled={importing}
          >
            <Plus size={16} />
            {importing ? '导入中...' : '安装插件'}
          </button>
        </>
      }
    >

      {/* 统计概览行 —— 已安装 / 已启用 / 已停用 */}
      <div className={styles['stats-row']}>
        <div className={styles['stat-card']}>
          <div className={`${styles['stat-icon']} ${styles['stat-icon-primary']}`}>
            <Package size={18} />
          </div>
          <div>
            <div className={styles['stat-label']}>已安装</div>
            <div className={styles['stat-value']}>{stats.total} 个</div>
          </div>
        </div>
        <div className={styles['stat-card']}>
          <div className={`${styles['stat-icon']} ${styles['stat-icon-success']}`}>
            <CheckCircle2 size={18} />
          </div>
          <div>
            <div className={styles['stat-label']}>已启用</div>
            <div className={styles['stat-value']}>{stats.enabled} 个</div>
          </div>
        </div>
        <div className={styles['stat-card']}>
          <div className={`${styles['stat-icon']} ${styles['stat-icon-warning']}`}>
            <AlertTriangle size={18} />
          </div>
          <div>
            <div className={styles['stat-label']}>已停用</div>
            <div className={styles['stat-value']}>{stats.disabled} 个</div>
          </div>
        </div>
      </div>

      {/* 工具栏 —— 搜索 + 全选 + 批量删除 + URL 导入 */}
      <div className={styles['toolbar']}>
        <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
          <Search size={16} style={{ position: 'absolute', left: 12, color: 'var(--color-text-tertiary)', pointerEvents: 'none' }} />
          <input
            className={styles['search-input']}
            style={{ paddingLeft: 36 }}
            placeholder="搜索插件名称 / 版本 / 作者 / 简介"
            value={searchKeyword}
            onChange={handleSearchChange}
          />
        </div>
        <label className={styles['select-all']}>
          <input
            type="checkbox"
            checked={allUserSelected}
            onChange={(e) => handleToggleSelectAll(e.target.checked)}
          />
          全选当前结果
        </label>
        <button
          className={`${styles['btn']} ${styles['btn-danger']}`}
          onClick={() => { void handleBatchDelete() }}
          disabled={selectedIds.length === 0 || deleting}
        >
          {deleting ? '删除中...' : `批量删除(${selectedIds.length})`}
        </button>
        <input
          className={styles['url-input']}
          placeholder="输入远程 ZIP URL（支持白名单域名）"
          value={remoteUrl}
          onChange={handleRemoteUrlChange}
        />
        <button
          className={`${styles['btn']} ${styles['btn-secondary']}`}
          onClick={() => { void handleImportByUrl() }}
          disabled={importing}
        >
          <Link2 size={16} />
          URL 导入
        </button>
      </div>

      {/* 错误提示 */}
      {(listError || importError || deleteError || permissionError || toggleError) && (
        <div className={styles['inline-error']}>
          <span>{listError || importError || deleteError || permissionError || toggleError}</span>
          <button className={`${styles['btn']} ${styles['btn-secondary']}`} onClick={handleRetryErrors}>
            重试
          </button>
        </div>
      )}

      {/* 插件卡片分区 —— 用户插件 + 系统内置插件 */}
      {groupedPlugins.userPlugins.length === 0 && groupedPlugins.builtinPlugins.length === 0 ? (
        /* 全局空状态：没有任何插件或搜索无结果 */
        <div className={styles['plugins-grid']}>
          <div className={styles['empty-state']}>
            <p>{plugins.length === 0 ? '还没有安装任何插件' : '没有匹配的插件'}</p>
            <button
              className={`${styles['btn']} ${styles['btn-primary']}`}
              onClick={handleClickImport}
              disabled={importing}
            >
              <Plus size={16} />
              {importing ? '导入中...' : '安装插件'}
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* 用户插件分区 */}
          <section className={styles['plugin-section']}>
            <div className={styles['section-header']}>
              <h2 className={styles['section-title']}>{t('plugins.section.user')}</h2>
              <span className={styles['count-badge']}>{groupedPlugins.userPlugins.length}</span>
            </div>
            {groupedPlugins.userPlugins.length === 0 ? (
              <div className={styles['empty-state']}>
                <p>{t('plugins.section.userEmpty')}</p>
              </div>
            ) : (
              <div className={styles['plugins-grid']}>
                {groupedPlugins.userPlugins.map(renderPluginCard)}
              </div>
            )}
          </section>

          {/* 系统内置插件分区 —— 仅在有内置插件时渲染 */}
          {groupedPlugins.builtinPlugins.length > 0 && (
            <section className={`${styles['plugin-section']} ${styles['builtin-section']}`}>
              <div className={styles['section-header']}>
                <div className={styles['section-title-row']}>
                  <Shield size={18} className={styles['builtin-shield-icon']} />
                  <h2 className={styles['section-title']}>{t('plugins.section.builtin')}</h2>
                  <span className={`${styles['count-badge']} ${styles['builtin-badge']}`}>
                    {groupedPlugins.builtinPlugins.length}
                  </span>
                </div>
                <p className={styles['section-description']}>
                  {t('plugins.section.builtin.description')}
                </p>
              </div>
              <div className={styles['plugins-grid']}>
                {groupedPlugins.builtinPlugins.map(renderPluginCard)}
              </div>
            </section>
          )}
        </>
      )}

      {/* 本地可用插件区域 */}
      <div className={styles['local-plugins-section']}>
        <h2 className={styles['section-title']}>本地可用插件</h2>
        {discoverLoading ? (
          <div className={styles['local-loading']}>扫描本地插件中...</div>
        ) : discoverError ? (
          <div className={styles['inline-error']}>
            <span>{discoverError}</span>
            <button className={`${styles['btn']} ${styles['btn-secondary']}`} onClick={() => { void refreshDiscovered() }}>
              重试
            </button>
          </div>
        ) : unregisteredPlugins.length === 0 ? (
          <div className={styles['local-empty']}>所有本地插件均已安装</div>
        ) : (
          <div className={styles['plugins-grid']}>
            {unregisteredPlugins.map((dp) => (
              <div key={dp.name} className={`${styles['plugin-card']} ${styles['local-card']}`}>
                <div className={styles['card-color-bar']} style={{ background: 'var(--color-text-tertiary)' }} />
                <div className={styles['card-body']}>
                  <div className={styles['card-header']}>
                    <div className={styles['card-header-left']}>
                      <div
                        className={styles['plugin-icon-box']}
                        style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
                      >
                        <Puzzle size={20} />
                      </div>
                      <div>
                        <div className={styles['plugin-name-row']}>
                          <span className={styles['plugin-name']}>{dp.name}</span>
                          <span className={styles['version-badge']}>v{dp.version || '1.0.0'}</span>
                        </div>
                        <span
                          className={styles['category-badge']}
                          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}
                        >
                          {dp.state !== 'unknown' ? dp.state : '未安装'}
                        </span>
                      </div>
                    </div>
                    <div className={styles['card-header-right']}>
                      <StatusBadge status="inactive" label="未安装" />
                    </div>
                  </div>
                  <p className={styles['card-description']}>
                    {dp.description || '暂无简介'}
                  </p>
                  <div className={styles['card-footer']}>
                    <button
                      className={`${styles['action-btn']} ${styles['action-btn-success']}`}
                      onClick={() => handleInstallLocalPlugin(dp.name, dp.version)}
                      disabled={installingPlugins.has(dp.name)}
                    >
                      <Plus size={14} />
                      {installingPlugins.has(dp.name) ? '安装中...' : '安装'}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 权限模态框 */}
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
                            className={styles['permission-revoke-btn']}
                            onClick={() => { void handleRevokePermission(permission) }}
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
                onClick={() => { void handleAuthorizeMissingPermissions() }}
                disabled={permissionLoading}
              >
                授权缺失权限
              </button>
              <button
                className={`${styles['btn']} ${styles['btn-secondary']}`}
                onClick={handleClosePermissionModal}
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

export default PluginsPage
