/**
 * 本地搜索页面组件。
 * 提供离线网页/文档搜索功能，支持即时搜索、索引管理和统计查看。
 *
 * 参考来源: FlexSearch (https://github.com/nextapps-de/flexsearch, Apache-2.0)
 * 作者: nextapps-de/Thomas Wilkerling
 * 许可: Apache-2.0
 */
import { useState, useEffect, useCallback } from 'react'
import { useFlexSearch } from '@/shared/hooks/useFlexSearch'
import { toolsAPI } from '@/shared/api/toolsApi'
import styles from './LocalSearchPage.module.css'

interface SearchResultItem {
  id: string
  title: string
  url: string
  snippet: string
  content_preview: string
  score: number
  indexed_at: string
}

interface IndexStats {
  doc_count: number
  unique_terms: number
  index_dir: string
  avg_terms_per_doc: number
}

export default function LocalSearchPage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResultItem[]>([])
  const [serverResults, setServerResults] = useState<SearchResultItem[]>([])
  const [loading, setLoading] = useState(false)
  const [searchMode, setSearchMode] = useState<'local' | 'server'>('local')
  const [stats, setStats] = useState<IndexStats | null>(null)
  const [error, setError] = useState('')
  const [indexUrl, setIndexUrl] = useState('')
  const [indexTitle, setIndexTitle] = useState('')
  const [indexContent, setIndexContent] = useState('')
  const [indexing, setIndexing] = useState(false)

  const {
    addDocument,
    search: flexSearch,
    docCount,
    init,
  } = useFlexSearch({ cjk: true })

  /* 初始化客户端搜索引擎 */
  useEffect(() => {
    init()
  }, [init])

  /* 加载服务端索引统计 */
  useEffect(() => {
    loadStats()
  }, [])

  const loadStats = async () => {
    try {
      const res = await toolsAPI.searchStats()
      if (res.data.success && res.data.data) {
        setStats(res.data.data as unknown as IndexStats)
      }
    } catch {
      /* 服务端统计加载失败不影响客户端搜索 */
    }
  }

  /* 执行搜索 */
  const handleSearch = useCallback(
    async (searchQuery?: string) => {
      const q = (searchQuery || query).trim()
      if (!q) {
        setResults([])
        setServerResults([])
        return
      }

      setLoading(true)
      setError('')

      try {
        if (searchMode === 'local') {
          /* 客户端即时搜索 */
          const searchResults = flexSearch(q, 20)
          /* 如果本地索引为空，尝试从服务端加载 */
          if (searchResults.length === 0) {
            await handleServerSearch(q)
          } else {
            setResults(
              searchResults.map((r) => ({
                id: String(r.id),
                title: String(r.id),
                url: '',
                snippet: `相关性评分: ${r.score}`,
                content_preview: '',
                score: r.score,
                indexed_at: '',
              }))
            )
          }
        } else {
          await handleServerSearch(q)
        }
      } catch (e) {
        setError(`搜索失败: ${e instanceof Error ? e.message : '未知错误'}`)
      } finally {
        setLoading(false)
      }
    },
    [query, searchMode, flexSearch]
  )

  const handleServerSearch = async (q: string) => {
    try {
      const res = await toolsAPI.localSearch(q, 20, 'tfidf')
      if (res.data.success && res.data.data) {
        const data = res.data.data as unknown as { results: SearchResultItem[] }
        setServerResults(data.results || [])
      } else {
        setError(res.data.error || '服务端搜索失败')
      }
    } catch (e) {
      setError(`服务端搜索请求失败: ${e instanceof Error ? e.message : '未知错误'}`)
    }
  }

  /* 索引文档到客户端 */
  const handleIndexToClient = useCallback(() => {
    if (!indexTitle || !indexContent) return
    const id = indexUrl || `doc_${Date.now()}`
    addDocument(id, `${indexTitle} ${indexTitle} ${indexContent}`)
    setIndexTitle('')
    setIndexContent('')
    setIndexUrl('')
  }, [indexTitle, indexContent, indexUrl, addDocument])

  /* 索引文档到服务端 */
  const handleIndexToServer = useCallback(async () => {
    if (!indexTitle || !indexContent) return
    setIndexing(true)
    try {
      const id = indexUrl || `doc_${Date.now()}`
      const res = await toolsAPI.indexDocument(id, indexTitle, indexContent, indexUrl)
      if (res.data.success) {
        setIndexTitle('')
        setIndexContent('')
        setIndexUrl('')
        await loadStats()
      } else {
        setError(res.data.error || '索引失败')
      }
    } catch (e) {
      setError(`索引请求失败: ${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setIndexing(false)
    }
  }, [indexTitle, indexContent, indexUrl])

  /* 键盘事件 */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        handleSearch()
      }
    },
    [handleSearch]
  )

  const displayResults = searchMode === 'local' ? results : serverResults

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1 className={styles.title}>本地搜索</h1>
        <p className={styles.subtitle}>
          离线搜索引擎 - 索引和搜索本地网页、文档内容
        </p>
      </header>

      {/* 搜索栏 */}
      <div className={styles.searchBar}>
        <div className={styles.searchInputWrap}>
          <input
            type="text"
            className={styles.searchInput}
            placeholder="输入搜索关键词..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            autoFocus
          />
          <button
            className={styles.searchButton}
            onClick={() => handleSearch()}
            disabled={loading}
          >
            {loading ? '搜索中...' : '搜索'}
          </button>
        </div>

        <div className={styles.searchOptions}>
          <label className={styles.radioLabel}>
            <input
              type="radio"
              name="searchMode"
              value="local"
              checked={searchMode === 'local'}
              onChange={() => setSearchMode('local')}
            />
            客户端搜索（即时）
          </label>
          <label className={styles.radioLabel}>
            <input
              type="radio"
              name="searchMode"
              value="server"
              checked={searchMode === 'server'}
              onChange={() => setSearchMode('server')}
            />
            服务端搜索（TF-IDF）
          </label>
          <span className={styles.docCount}>
            客户端索引: {docCount} 篇 | 服务端索引: {stats?.doc_count || 0} 篇
          </span>
        </div>
      </div>

      {/* 错误提示 */}
      {error && <div className={styles.error}>{error}</div>}

      {/* 搜索结果 */}
      <div className={styles.results}>
        {displayResults.length > 0 && (
          <p className={styles.resultCount}>
            找到 {displayResults.length} 个结果
          </p>
        )}
        {displayResults.map((item) => (
          <div key={item.id} className={styles.resultItem}>
            <div className={styles.resultHeader}>
              <a
                href={item.url || '#'}
                className={styles.resultTitle}
                target={item.url ? '_blank' : undefined}
                rel={item.url ? 'noopener noreferrer' : undefined}
              >
                {item.title || item.id}
              </a>
              {item.score > 0 && (
                <span className={styles.resultScore}>
                  相关度: {(item.score * 100).toFixed(0)}%
                </span>
              )}
            </div>
            {item.snippet && (
              <p className={styles.resultSnippet}>{item.snippet}</p>
            )}
            {item.content_preview && (
              <p className={styles.resultPreview}>
                {item.content_preview.slice(0, 300)}
              </p>
            )}
          </div>
        ))}
        {!loading && query && displayResults.length === 0 && (
          <p className={styles.noResults}>
            未找到匹配结果。请尝试其他关键词或先添加文档到索引。
          </p>
        )}
      </div>

      {/* 索引管理 */}
      <section className={styles.indexSection}>
        <h2 className={styles.sectionTitle}>索引管理</h2>
        <div className={styles.indexForm}>
          <input
            type="text"
            className={styles.indexInput}
            placeholder="文档ID/URL（可选）"
            value={indexUrl}
            onChange={(e) => setIndexUrl(e.target.value)}
          />
          <input
            type="text"
            className={styles.indexInput}
            placeholder="文档标题"
            value={indexTitle}
            onChange={(e) => setIndexTitle(e.target.value)}
          />
          <textarea
            className={styles.indexTextarea}
            placeholder="文档内容（纯文本）"
            value={indexContent}
            onChange={(e) => setIndexContent(e.target.value)}
            rows={4}
          />
          <div className={styles.indexActions}>
            <button
              className={styles.indexButton}
              onClick={handleIndexToClient}
              disabled={!indexTitle || !indexContent}
            >
              添加到客户端索引
            </button>
            <button
              className={styles.indexButton}
              onClick={handleIndexToServer}
              disabled={!indexTitle || !indexContent || indexing}
            >
              {indexing ? '索引中...' : '添加到服务端索引'}
            </button>
          </div>
        </div>
      </section>

      {/* 统计信息 */}
      {stats && (
        <section className={styles.statsSection}>
          <h2 className={styles.sectionTitle}>索引统计</h2>
          <div className={styles.statsGrid}>
            <div className={styles.statCard}>
              <span className={styles.statValue}>{stats.doc_count}</span>
              <span className={styles.statLabel}>索引文档数</span>
            </div>
            <div className={styles.statCard}>
              <span className={styles.statValue}>{stats.unique_terms}</span>
              <span className={styles.statLabel}>唯一词条数</span>
            </div>
            <div className={styles.statCard}>
              <span className={styles.statValue}>{stats.avg_terms_per_doc}</span>
              <span className={styles.statLabel}>平均词条/文档</span>
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
