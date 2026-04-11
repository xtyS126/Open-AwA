/**
 * 插件市场页面组件，提供插件浏览、搜索、分类筛选与安装功能。
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getPlugins,
  searchPlugins,
  installPlugin,
  MarketplacePlugin,
} from './marketplaceApi'
import styles from './MarketplacePage.module.css'

/** 分类选项配置 */
const CATEGORY_OPTIONS = [
  { key: 'all', label: '全部' },
  { key: 'tool', label: '工具' },
  { key: 'theme', label: '主题' },
  { key: 'data', label: '数据' },
  { key: 'other', label: '其他' },
]

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

  const pageSize = 12

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
    } catch (error) {
      console.error('加载插件列表失败:', error)
    } finally {
      setLoading(false)
    }
  }, [activeCategory, page])

  /** 搜索插件 */
  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      loadPlugins()
      return
    }
    setLoading(true)
    try {
      const response = await searchPlugins(searchQuery.trim())
      setPlugins(response.data.plugins)
      setTotal(response.data.total)
      setPage(1)
    } catch (error) {
      console.error('搜索插件失败:', error)
    } finally {
      setLoading(false)
    }
  }

  /** 安装插件 */
  const handleInstall = async (pluginId: string) => {
    setInstallingId(pluginId)
    try {
      await installPlugin(pluginId)
      setInstalledIds((prev) => new Set(prev).add(pluginId))
    } catch (error: any) {
      const detail = error?.response?.data?.detail
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

  useEffect(() => {
    // 搜索状态时不自动加载列表
    if (!searchQuery.trim()) {
      loadPlugins()
    }
  }, [loadPlugins, searchQuery])

  /** 生成插件图标首字母 */
  const getIconLetter = (name: string) => {
    return name.charAt(0).toUpperCase()
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className={styles['marketplace-page']}>
      {/* 页面头部 */}
      <div className={styles['page-header']}>
        <h1>插件市场</h1>
        <button className={styles['back-btn']} onClick={() => navigate('/plugins')}>
          返回插件管理
        </button>
      </div>

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
          {plugins.length === 0 ? (
            <div className={styles['empty-state']}>
              <p>未找到匹配的插件</p>
            </div>
          ) : (
            plugins.map((plugin) => (
              <div key={plugin.id} className={styles['plugin-card']}>
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

                {/* 底部：安装数/安装按钮 */}
                <div className={styles['plugin-footer']}>
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
            ))
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
    </div>
  )
}

export default MarketplacePage
