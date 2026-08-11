/**
 * 角色市场页面 — 浏览、搜索、安装和评分市场中的角色。
 */
import { useState, useEffect, useCallback } from 'react'
import { Download, Star, Search, TrendingUp, Clock } from 'lucide-react'
import { getMarketRoles, getCategories, installRole, rateRole } from '@/shared/api/roleMarketApi'
import type { MarketRole, MarketCategory } from '@/shared/api/roleMarketApi'
import styles from './RoleMarketPage.module.css'

export interface RoleMarketPageProps {
  embedded?: boolean
}

export default function RoleMarketPage({ embedded = false }: RoleMarketPageProps) {
  const [roles, setRoles] = useState<MarketRole[]>([])
  const [categories, setCategories] = useState<MarketCategory[]>([])
  const [loading, setLoading] = useState(true)
  const [activeCategory, setActiveCategory] = useState('all')
  const [sortBy, setSortBy] = useState('popular')
  const [searchQuery, setSearchQuery] = useState('')
  const [installedIds, setInstalledIds] = useState<Set<string>>(new Set())

  const loadRoles = useCallback(async () => {
    try {
      setLoading(true)
      const resp = await getMarketRoles({
        category: activeCategory,
        sort: sortBy,
        page: 1,
        page_size: 50,
      })
      let items = resp.items
      if (searchQuery) {
        items = items.filter(
          (r) =>
            r.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            r.description.toLowerCase().includes(searchQuery.toLowerCase())
        )
      }
      setRoles(items)
    } catch (e) {
      console.error('加载市场角色失败', e)
    } finally {
      setLoading(false)
    }
  }, [activeCategory, sortBy, searchQuery])

  const loadCategories = useCallback(async () => {
    try {
      const resp = await getCategories()
      setCategories(resp.categories)
    } catch (e) {
      console.error('加载分类失败', e)
    }
  }, [])

  useEffect(() => {
    loadCategories()
  }, [loadCategories])
  useEffect(() => {
    loadRoles()
  }, [loadRoles])

  const handleInstall = async (roleId: string) => {
    try {
      const result = await installRole(roleId)
      if (result.ok) {
        setInstalledIds((prev) => new Set(prev).add(roleId))
      }
    } catch (e) {
      console.error('安装角色失败', e)
    }
  }

  const handleRate = async (roleId: string, rating: number) => {
    try {
      await rateRole(roleId, rating)
    } catch (e) {
      console.error('评分失败', e)
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        {!embedded && <h1>角色市场</h1>}
        <div className={styles.searchBox}>
          <Search size={16} className={styles.searchIcon} />
          <input
            className={styles.searchInput}
            placeholder="搜索角色..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* 分类和排序 */}
      <div className={styles.toolbar}>
        <div className={styles.categories}>
          {categories.map((cat) => (
            <button
              key={cat.id}
              className={`${styles.categoryBtn} ${activeCategory === cat.id ? styles.active : ''}`}
              onClick={() => setActiveCategory(cat.id)}
            >
              {cat.name}
            </button>
          ))}
        </div>
        <div className={styles.sortBtns}>
          <button
            className={`${styles.sortBtn} ${sortBy === 'popular' ? styles.active : ''}`}
            onClick={() => setSortBy('popular')}
          >
            <TrendingUp size={14} /> 热门
          </button>
          <button
            className={`${styles.sortBtn} ${sortBy === 'newest' ? styles.active : ''}`}
            onClick={() => setSortBy('newest')}
          >
            <Clock size={14} /> 最新
          </button>
        </div>
      </div>

      {/* 角色列表 */}
      {loading ? (
        <div className={styles.loading}>加载中...</div>
      ) : roles.length === 0 ? (
        <div className={styles.empty}>暂无角色</div>
      ) : (
        <div className={styles.grid}>
          {roles.map((role) => (
            <div key={role.id} className={styles.card}>
              <div className={styles.cardHeader}>
                <h3 className={styles.cardTitle}>{role.name}</h3>
                {role.is_preset && <span className={styles.presetBadge}>官方</span>}
              </div>
              <p className={styles.cardDesc}>{role.description}</p>
              <div className={styles.cardMeta}>
                <span className={styles.usageCount}>
                  <Download size={12} /> {role.usage_count} 次使用
                </span>
              </div>
              <div className={styles.cardActions}>
                <div className={styles.rating}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      className={styles.starBtn}
                      onClick={() => handleRate(role.id, n)}
                      title={`${n}星`}
                    >
                      <Star size={12} />
                    </button>
                  ))}
                </div>
                <button
                  className={styles.installBtn}
                  onClick={() => handleInstall(role.id)}
                  disabled={installedIds.has(role.id)}
                >
                  {installedIds.has(role.id) ? '已安装' : '安装'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
