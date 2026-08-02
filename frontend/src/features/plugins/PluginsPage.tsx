import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from '@/shared/routing'
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
import { EmptyState, StatusBadge, Tooltip } from '@/shared/components/ui'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { Plugin } from '@/features/dashboard/dashboard'
import PluginDebugPanel from '@/features/plugins/PluginDebugPanel'
import {
  usePluginDelete,
  usePluginList,
  usePluginPermissions,
  usePluginToggle,
  useDiscoveredPlugins,
  usePluginImport,
} from '@/features/plugins/hooks'
import { isBuiltinPlugin, isUninstallablePlugin } from '@/features/plugins/pluginTypes'
import { useToast } from '@/shared/components/Toast'
import { useI18nStore } from '@/i18n'
import { pluginsAPI } from '@/shared/api/api'
import {
  getPlugins,
  searchPlugins,
  installPlugin,
  getPluginRating,
  type MarketplacePlugin,
  type PluginRatingSummary,
} from './marketplaceApi'
import PluginDetailModal from './PluginDetailModal'
import styles from './PluginsPage.module.css'
import marketStyles from './MarketplacePage.module.css'

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
            <ErrorBoundary name="PluginDebugPanel" variant="compact">
              <PluginDebugPanel pluginId={plugin.id} pluginName={plugin.name} />
            </ErrorBoundary>
          </div>
        )}
      </div>
    </div>
  )
})

// ============================================================================
// 市场 Tab —— 集中承载所有"获取新插件"入口
// 在线市场安装 / ZIP 上传 / URL 远程导入 / 本地可用插件扫描
// ============================================================================

/** 市场分类选项配置 */
const MARKET_CATEGORY_OPTIONS = [
  { key: 'all', label: '全部' },
  { key: 'tool', label: '工具' },
  { key: 'theme', label: '主题' },
  { key: 'data', label: '数据' },
  { key: 'other', label: '其他' },
]

/** 实心星与空心星 Unicode 字符 */
const STAR_FILLED = '\u2605'
const STAR_EMPTY = '\u2606'

/** ZIP 上传大小上限：50MB */
const MAX_PLUGIN_UPLOAD_SIZE = 50 * 1024 * 1024
/** 允许的 ZIP MIME 类型白名单 */
const ALLOWED_PLUGIN_MIME_TYPES = new Set([
  'application/zip',
  'application/x-zip-compressed',
  'multipart/x-zip',
])

/** 根据评分渲染 5 颗星（实心/空心） */
function renderStars(score: number): string {
  const rounded = Math.round(score)
  let result = ''
  for (let i = 1; i <= 5; i++) {
    result += i <= rounded ? STAR_FILLED : STAR_EMPTY
  }
  return result
}

/**
 * MarketplaceTab —— 市场 Tab 内容组件。
 *
 * 集中承载所有"获取新插件"入口：
 * - 在线市场安装（搜索、分类筛选、详情查看）
 * - ZIP 上传安装
 * - URL 远程导入
 * - 本地可用插件扫描与一键安装
 *
 * 安装成功后通过 onInstalled 回调通知父组件刷新已安装列表。
 */
interface MarketplaceTabProps {
  /** 插件安装成功后回调（用于刷新已安装列表） */
  onInstalled: () => void
}

function MarketplaceTab({ onInstalled }: MarketplaceTabProps): React.ReactElement {
  const { addToast, ToastContainer } = useToast()
  const [plugins, setPlugins] = useState<MarketplacePlugin[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [activeCategory, setActiveCategory] = useState('all')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [installingId, setInstallingId] = useState<string | null>(null)
  const [installedIds, setInstalledIds] = useState<Set<string>>(new Set())
  /* 评分汇总缓存：pluginId -> 评分摘要 */
  const [ratingsMap, setRatingsMap] = useState<Record<string, PluginRatingSummary>>({})
  /* 当前打开详情的插件 */
  const [detailPlugin, setDetailPlugin] = useState<MarketplacePlugin | null>(null)

  /* 本地安装相关状态 —— ZIP 上传 + URL 导入 */
  const [remoteUrl, setRemoteUrl] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { loading: importing, error: importError, importFromFile, importFromUrl, retry: retryImport } = usePluginImport()

  /* 已安装插件列表 —— 用于过滤本地已发现的未注册插件 */
  const { plugins: installedPlugins, refresh: refreshInstalled } = usePluginList()
  /* 本地已发现的插件 */
  const {
    discovered,
    loading: discoverLoading,
    error: discoverError,
    refresh: refreshDiscovered,
  } = useDiscoveredPlugins()
  /* 本地安装中状态：pluginName -> boolean */
  const [installingLocalPlugins, setInstallingLocalPlugins] = useState<Set<string>>(new Set())

  /**
   * 前端过滤内置插件 —— 双重保险，确保 source=builtin 的插件不在市场展示。
   * 即使后端 API 已经过滤，前端仍保留此校验以防数据回流。
   */
  const visiblePlugins = useMemo(() => {
    return plugins.filter((p) => p.source !== 'builtin')
  }, [plugins])

  /** 过滤出未注册到数据库的本地插件（已发现但未安装） */
  const unregisteredPlugins = useMemo(() => {
    const registeredNames = new Set(installedPlugins.map((p) => p.name.toLowerCase()))
    return discovered.filter((d) => !registeredNames.has(d.name.toLowerCase()))
  }, [discovered, installedPlugins])

  const pageSize = 12

  /** 批量加载当前页插件的评分摘要 */
  const loadRatings = useCallback(async (pluginIds: string[]) => {
    if (pluginIds.length === 0) return
    // 并行获取每个插件的评分摘要，单个失败不影响其他
    const results = await Promise.allSettled(
      pluginIds.map((id) => getPluginRating(id))
    )
    const next: Record<string, PluginRatingSummary> = {}
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        next[pluginIds[index]] = result.value.data
      }
    })
    setRatingsMap(next)
  }, [])

  /** 加载插件列表 */
  const loadPlugins = useCallback(async () => {
    setLoading(true)
    try {
      const response = await getPlugins({
        category: activeCategory === 'all' ? undefined : activeCategory,
        page,
        page_size: pageSize,
      })
      setPlugins(response.data.plugins)
      setTotal(response.data.total)
      // 加载评分摘要
      loadRatings(response.data.plugins.map((p) => p.id))
    } catch (error) {
      console.error('加载插件列表失败:', error)
    } finally {
      setLoading(false)
    }
  }, [activeCategory, page, loadRatings])

  /** 搜索插件 */
  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      loadPlugins()
      return
    }
    setPage(1)
  }

  /** 在线安装插件 */
  const handleInstall = async (pluginId: string) => {
    setInstallingId(pluginId)
    try {
      await installPlugin(pluginId)
      setInstalledIds((prev) => new Set(prev).add(pluginId))
      // 通知父组件刷新已安装列表
      onInstalled()
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(`安装失败: ${detail || '未知错误'}`)
    } finally {
      setInstallingId(null)
    }
  }

  /** 处理分类切换 */
  const handleCategoryChange = (category: string) => {
    setActiveCategory(category)
    setPage(1)
    setSearchQuery('')
  }

  /** 处理搜索框回车 */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }

  /** 点击插件卡片打开详情 */
  const handleCardClick = (plugin: MarketplacePlugin) => {
    setDetailPlugin(plugin)
  }

  /** 阻止卡片内按钮点击冒泡到卡片 */
  const stopPropagation = (e: React.MouseEvent) => {
    e.stopPropagation()
  }

  /* ==================== 本地安装相关处理函数 ==================== */

  /** 触发文件选择对话框 */
  const handleClickImport = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  /** 处理 ZIP 文件上传 —— 校验扩展名与大小后调用上传接口 */
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
        await refreshInstalled()
        onInstalled()
        addToast('插件导入成功', 'success')
      } catch {
        addToast('插件导入失败', 'error')
      } finally {
        if (fileInputRef.current) fileInputRef.current.value = ''
      }
    }
  }, [importFromFile, refreshInstalled, onInstalled, addToast])

  /** 处理 URL 导入 —— 去除首尾空白后调用远程导入接口 */
  const handleImportByUrl = useCallback(async () => {
    const trimmedUrl = remoteUrl.trim()
    if (!trimmedUrl) {
      addToast('请输入远程 URL', 'warning')
      return
    }
    try {
      await importFromUrl(trimmedUrl)
      setRemoteUrl('')
      await refreshInstalled()
      onInstalled()
      addToast('远程 URL 导入成功', 'success')
    } catch {
      addToast('远程 URL 导入失败', 'error')
    }
  }, [remoteUrl, importFromUrl, refreshInstalled, onInstalled, addToast])

  /** 安装本地发现的插件到数据库 */
  const handleInstallLocal = useCallback(async (pluginName: string, pluginVersion: string) => {
    setInstallingLocalPlugins((prev) => new Set(prev).add(pluginName))
    try {
      await pluginsAPI.install({ name: pluginName, version: pluginVersion, config: {} })
      await refreshInstalled()
      await refreshDiscovered()
      onInstalled()
      addToast(`插件 "${pluginName}" 安装成功`, 'success')
    } catch {
      addToast(`插件 "${pluginName}" 安装失败`, 'error')
    } finally {
      setInstallingLocalPlugins((prev) => {
        const next = new Set(prev)
        next.delete(pluginName)
        return next
      })
    }
  }, [refreshInstalled, refreshDiscovered, onInstalled, addToast])

  useEffect(() => {
    // 搜索状态时重新搜索（支持分页），非搜索状态加载列表
    if (searchQuery.trim()) {
      setLoading(true)
      searchPlugins(searchQuery.trim(), page, pageSize)
        .then(response => {
          setPlugins(response.data.plugins)
          setTotal(response.data.total)
          loadRatings(response.data.plugins.map((p) => p.id))
        })
        .catch(error => console.error('搜索插件失败:', error))
        .finally(() => setLoading(false))
    } else {
      loadPlugins()
    }
  }, [loadPlugins, searchQuery, page, loadRatings])

  /** 生成插件图标首字母 */
  const getIconLetter = (name: string) => {
    return name.charAt(0).toUpperCase()
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <>
      {/* 本地安装工具栏 —— ZIP 上传 + URL 导入 */}
      <div className={marketStyles['local-install-toolbar']}>
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: 'none' }}
          accept=".zip"
          onChange={handleFileUpload}
        />
        <button
          className={marketStyles['install-btn']}
          onClick={handleClickImport}
          disabled={importing}
        >
          <Plus size={14} />
          {importing ? '导入中...' : '上传 ZIP 安装'}
        </button>
        <input
          className={marketStyles['search-input']}
          style={{ flex: 1, maxWidth: 360 }}
          placeholder="输入远程 ZIP URL（支持白名单域名）"
          value={remoteUrl}
          onChange={(e) => setRemoteUrl(e.target.value)}
        />
        <button
          className={marketStyles['search-btn']}
          onClick={() => { void handleImportByUrl() }}
          disabled={importing}
        >
          <Link2 size={14} />
          URL 导入
        </button>
      </div>

      {/* 导入错误提示 */}
      {importError && (
        <div className={marketStyles['inline-error']}>
          <span>{importError}</span>
          <button className={marketStyles['search-btn']} onClick={() => { void retryImport() }}>
            重试
          </button>
        </div>
      )}

      {/* 搜索栏 */}
      <div className={marketStyles['search-bar']}>
        <input
          className={marketStyles['search-input']}
          type="text"
          placeholder="搜索插件名称、描述或标签..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button className={marketStyles['search-btn']} onClick={handleSearch}>
          搜索
        </button>
      </div>

      {/* 分类筛选 */}
      <div className={marketStyles['category-filter']}>
        {MARKET_CATEGORY_OPTIONS.map((cat) => (
          <button
            key={cat.key}
            className={`${marketStyles['category-tag']} ${
              activeCategory === cat.key ? marketStyles['category-tag-active'] : ''
            }`}
            onClick={() => handleCategoryChange(cat.key)}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* 加载中 */}
      {loading && <div className={marketStyles['loading']}>加载中...</div>}

      {/* 插件卡片网格 */}
      {!loading && (
        <div className={marketStyles['plugins-grid']}>
          {visiblePlugins.length === 0 ? (
            <EmptyState title="未找到匹配的插件" description="尝试更换搜索关键词或筛选条件" />
          ) : (
            visiblePlugins.map((plugin) => {
              const rating = ratingsMap[plugin.id]
              return (
                <div
                  key={plugin.id}
                  className={marketStyles['plugin-card']}
                  onClick={() => handleCardClick(plugin)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      handleCardClick(plugin)
                    }
                  }}
                >
                  {/* 图标 */}
                  <div className={marketStyles['plugin-icon']}>
                    {getIconLetter(plugin.name)}
                  </div>

                  {/* 名称 */}
                  <h3 className={marketStyles['plugin-name']}>{plugin.name}</h3>

                  {/* 描述 */}
                  <p className={marketStyles['plugin-description']}>
                    {plugin.description}
                  </p>

                  {/* 标签 */}
                  {plugin.tags && plugin.tags.length > 0 && (
                    <div className={marketStyles['plugin-tags']}>
                      {plugin.tags.map((tag) => (
                        <span key={tag} className={marketStyles['plugin-tag']}>
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* 作者与版本 */}
                  <div className={marketStyles['plugin-meta']}>
                    <span className={marketStyles['plugin-author']}>{plugin.author}</span>
                    <span className={marketStyles['plugin-version']}>v{plugin.version}</span>
                  </div>

                  {/* 评分摘要 */}
                  <div className={marketStyles['plugin-rating']}>
                    {rating && rating.total_count > 0 ? (
                      <>
                        <span className={marketStyles['plugin-rating-stars']}>
                          {renderStars(rating.average_score)}
                        </span>
                        <span className={marketStyles['plugin-rating-text']}>
                          {rating.average_score.toFixed(1)} ({rating.total_count} 人)
                        </span>
                      </>
                    ) : (
                      <span className={marketStyles['plugin-rating-empty']}>暂无评分</span>
                    )}
                  </div>

                  {/* 底部：安装数/安装按钮 */}
                  <div className={marketStyles['plugin-footer']} onClick={stopPropagation}>
                    <span className={marketStyles['plugin-install-count']}>
                      {plugin.install_count} 次安装
                    </span>
                    {installedIds.has(plugin.id) ? (
                      <span className={marketStyles['installed-badge']}>已安装</span>
                    ) : (
                      <button
                        className={marketStyles['install-btn']}
                        onClick={() => handleInstall(plugin.id)}
                        disabled={installingId === plugin.id}
                      >
                        {installingId === plugin.id ? '安装中...' : '安装'}
                      </button>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}

      {/* 分页控件 */}
      {!loading && totalPages > 1 && (
        <div className={marketStyles['pagination']}>
          <button
            className={marketStyles['pagination-btn']}
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            上一页
          </button>
          <span className={marketStyles['pagination-info']}>
            {page} / {totalPages}
          </span>
          <button
            className={marketStyles['pagination-btn']}
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </button>
        </div>
      )}

      {/* 本地可用插件区域 —— 扫描本地未注册插件，一键安装 */}
      <div className={marketStyles['local-plugins-section']}>
        <h2 className={marketStyles['section-title']}>本地可用插件</h2>
        {discoverLoading ? (
          <div className={marketStyles['loading']}>扫描本地插件中...</div>
        ) : discoverError ? (
          <div className={marketStyles['inline-error']}>
            <span>{discoverError}</span>
            <button className={marketStyles['search-btn']} onClick={() => { void refreshDiscovered() }}>
              重试
            </button>
          </div>
        ) : unregisteredPlugins.length === 0 ? (
          <div className={marketStyles['loading']}>所有本地插件均已安装</div>
        ) : (
          <div className={marketStyles['plugins-grid']}>
            {unregisteredPlugins.map((dp) => (
              <div key={dp.name} className={`${marketStyles['plugin-card']} ${marketStyles['local-card']}`}>
                <div className={marketStyles['plugin-icon']}>
                  <Puzzle size={24} />
                </div>
                <h3 className={marketStyles['plugin-name']}>{dp.name}</h3>
                <p className={marketStyles['plugin-description']}>
                  {dp.description || '暂无简介'}
                </p>
                <div className={marketStyles['plugin-meta']}>
                  <span className={marketStyles['plugin-version']}>v{dp.version || '1.0.0'}</span>
                  <StatusBadge status="inactive" label={dp.state !== 'unknown' ? dp.state : '未安装'} />
                </div>
                <div className={marketStyles['plugin-footer']}>
                  <button
                    className={marketStyles['install-btn']}
                    onClick={() => { void handleInstallLocal(dp.name, dp.version) }}
                    disabled={installingLocalPlugins.has(dp.name)}
                  >
                    <Plus size={14} />
                    {installingLocalPlugins.has(dp.name) ? '安装中...' : '安装'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 插件详情 Modal */}
      <PluginDetailModal
        open={detailPlugin !== null}
        onClose={() => setDetailPlugin(null)}
        plugin={detailPlugin}
      />
      <ToastContainer />
    </>
  )
}

function PluginsPage() {
  const navigate = useNavigate()
  const { t } = useI18nStore()
  /* 当前激活的 Tab：installed=已安装管理，market=插件市场 */
  const [activeTab, setActiveTab] = useState<'installed' | 'market'>('installed')
  const { plugins, loading, error: listError, retry: retryLoadPlugins, refresh: refreshPlugins } = usePluginList()
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
  const { addToast, ToastContainer } = useToast()
  const [permissionMessage, setPermissionMessage] = useState('')
  const [permissionModalOpen, setPermissionModalOpen] = useState(false)
  const [selectedPlugin, setSelectedPlugin] = useState<Plugin | null>(null)
  const [debugPluginId, setDebugPluginId] = useState<string | null>(null)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [expandedDescriptions, setExpandedDescriptions] = useState<Record<string, boolean>>({})

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

  /** 过滤出未注册到数据库的本地插件（已发现但未安装） —— 由 MarketplaceTab 内联组件承载 */

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

  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchKeyword(e.target.value)
  }, [])

  const handleRetryErrors = useCallback(() => {
    if (listError) retryLoadPlugins()
    if (deleteError) retryDelete()
    if (permissionError) retryPermission()
    if (toggleError) retryToggle()
  }, [listError, deleteError, permissionError, toggleError, retryLoadPlugins, retryDelete, retryPermission, retryToggle])

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

  const handleClosePermissionModal = useCallback(() => {
    setPermissionModalOpen(false)
    setSelectedPlugin(null)
    setPermissionMessage('')
  }, [])

  /** 全选状态仅针对用户插件 */
  const allUserSelected = groupedPlugins.userPlugins.length > 0
    && groupedPlugins.userPlugins.every((item) => selectedIds.includes(item.id))

  if (loading && activeTab === 'installed') {
    return (
      <PageLayout
        title="插件管理"
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
      className={styles['plugins-page']}
      actions={
        activeTab === 'installed' ? (
          <button
            className={`${styles['btn']} ${styles['btn-outline']}`}
            onClick={() => { void refreshPlugins() }}
            disabled={loading}
          >
            <RefreshCw size={16} />
            刷新
          </button>
        ) : null
      }
    >
      {/* Tab 切换 —— 已安装 / 市场 */}
      <div className={styles['tabs']}>
        <button
          className={`${styles['tab']} ${activeTab === 'installed' ? styles['tab-active'] : ''}`}
          onClick={() => setActiveTab('installed')}
        >
          <Package size={16} />
          已安装
          <span className={styles['tab-count']}>{plugins.length}</span>
        </button>
        <button
          className={`${styles['tab']} ${activeTab === 'market' ? styles['tab-active'] : ''}`}
          onClick={() => setActiveTab('market')}
        >
          <Puzzle size={16} />
          市场
        </button>
      </div>

      {activeTab === 'installed' ? (
        <>
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

          {/* 工具栏 —— 搜索 + 全选 + 批量删除 */}
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
          </div>

          {/* 错误提示 */}
          {(listError || deleteError || permissionError || toggleError) && (
            <div className={styles['inline-error']}>
              <span>{listError || deleteError || permissionError || toggleError}</span>
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
                  onClick={() => setActiveTab('market')}
                >
                  <Puzzle size={16} />
                  去市场安装
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
        </>
      ) : (
        /* 市场 Tab —— 集中承载所有获取新插件入口 */
        <MarketplaceTab onInstalled={() => { void refreshPlugins() }} />
      )}
      <ToastContainer />
    </PageLayout>
  )
}

export default PluginsPage
