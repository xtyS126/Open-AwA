/**
 * 插件市场页面组件，提供插件浏览、搜索、分类筛选与安装功能。
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import PluginSectionNav from '@/features/plugins/PluginSectionNav'
import {
  getPlugins,
  searchPlugins,
  installPlugin,
  getPluginRating,
  type MarketplacePlugin,
  type PluginRatingSummary,
} from './marketplaceApi'
import { EmptyState } from '@/shared/components/ui'
import PluginDetailModal from './PluginDetailModal'
import styles from './MarketplacePage.module.css'

/** 分类选项配置 */
const CATEGORY_OPTIONS = [
  { key: 'all', label: '全部' },
  { key: 'tool', label: '工具' },
  { key: 'theme', label: '主题' },
  { key: 'data', label: '数据' },
  { key: 'other', label: '其他' },
]

/** 实心星与空心星 Unicode 字符 */
const STAR_FILLED = '\u2605'
const STAR_EMPTY = '\u2606'

/** 根据评分渲染 5 颗星（实心/空心） */
function renderStars(score: number): string {
  const rounded = Math.round(score)
  let result = ''
  for (let i = 1; i <= 5; i++) {
    result += i <= rounded ? STAR_FILLED : STAR_EMPTY
  }
  return result
}

function MarketplacePage() {
  const navigate = useNavigate()

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

  /**
   * 前端过滤内置插件 —— 双重保险，确保 source=builtin 的插件不在市场展示。
   * 即使后端 API 已经过滤，前端仍保留此校验以防数据回流。
   */
  const visiblePlugins = useMemo(() => {
    return plugins.filter((p) => p.source !== 'builtin')
  }, [plugins])

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

  /** 安装插件 */
  const handleInstall = async (pluginId: string) => {
    setInstallingId(pluginId)
    try {
      await installPlugin(pluginId)
      setInstalledIds((prev) => new Set(prev).add(pluginId))
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
    <PageLayout
      title="插件市场"
      secondarySidebar={<PluginSectionNav />}
      className={styles['marketplace-page']}
      actions={
        <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={() => navigate('/plugins/manage')}>
          返回插件管理
        </button>
      }
    >
      {/* 搜索栏 */}
      <div className={styles['search-bar']}>
        <input
          className={styles['search-input']}
          type="text"
          placeholder="搜索插件名称、描述或标签..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button className={styles['search-btn']} onClick={handleSearch}>
          搜索
        </button>
      </div>

      {/* 分类筛选 */}
      <div className={styles['category-filter']}>
        {CATEGORY_OPTIONS.map((cat) => (
          <button
            key={cat.key}
            className={`${styles['category-tag']} ${
              activeCategory === cat.key ? styles['category-tag-active'] : ''
            }`}
            onClick={() => handleCategoryChange(cat.key)}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* 加载中 */}
      {loading && <div className={styles['loading']}>加载中...</div>}

      {/* 插件卡片网格 */}
      {!loading && (
        <div className={styles['plugins-grid']}>
          {visiblePlugins.length === 0 ? (
            <EmptyState title="未找到匹配的插件" description="尝试更换搜索关键词或筛选条件" />
          ) : (
            visiblePlugins.map((plugin) => {
              const rating = ratingsMap[plugin.id]
              return (
                <div
                  key={plugin.id}
                  className={styles['plugin-card']}
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
                  <div className={styles['plugin-icon']}>
                    {getIconLetter(plugin.name)}
                  </div>

                  {/* 名称 */}
                  <h3 className={styles['plugin-name']}>{plugin.name}</h3>

                  {/* 描述 */}
                  <p className={styles['plugin-description']}>
                    {plugin.description}
                  </p>

                  {/* 标签 */}
                  {plugin.tags && plugin.tags.length > 0 && (
                    <div className={styles['plugin-tags']}>
                      {plugin.tags.map((tag) => (
                        <span key={tag} className={styles['plugin-tag']}>
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* 作者与版本 */}
                  <div className={styles['plugin-meta']}>
                    <span className={styles['plugin-author']}>{plugin.author}</span>
                    <span className={styles['plugin-version']}>v{plugin.version}</span>
                  </div>

                  {/* 评分摘要 */}
                  <div className={styles['plugin-rating']}>
                    {rating && rating.total_count > 0 ? (
                      <>
                        <span className={styles['plugin-rating-stars']}>
                          {renderStars(rating.average_score)}
                        </span>
                        <span className={styles['plugin-rating-text']}>
                          {rating.average_score.toFixed(1)} ({rating.total_count} 人)
                        </span>
                      </>
                    ) : (
                      <span className={styles['plugin-rating-empty']}>暂无评分</span>
                    )}
                  </div>

                  {/* 底部：安装数/安装按钮 */}
                  <div className={styles['plugin-footer']} onClick={stopPropagation}>
                    <span className={styles['plugin-install-count']}>
                      {plugin.install_count} 次安装
                    </span>
                    {installedIds.has(plugin.id) ? (
                      <span className={styles['installed-badge']}>已安装</span>
                    ) : (
                      <button
                        className={styles['install-btn']}
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
        <div className={styles['pagination']}>
          <button
            className={styles['pagination-btn']}
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            上一页
          </button>
          <span className={styles['pagination-info']}>
            {page} / {totalPages}
          </span>
          <button
            className={styles['pagination-btn']}
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </button>
        </div>
      )}

      {/* 插件详情 Modal */}
      <PluginDetailModal
        open={detailPlugin !== null}
        onClose={() => setDetailPlugin(null)}
        plugin={detailPlugin}
      />
    </PageLayout>
  )
}

export default MarketplacePage
