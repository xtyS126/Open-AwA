/**
 * 记忆管理页面 —— 对齐 Canvas 设计参考 (open-awa-canvas/pages/memory.html)。
 * 结构：页面标题 / 4 列统计卡片 / 左侧记忆列表 + 右侧系统状态侧栏。
 * 数据获取逻辑保持不变（短期/长期记忆），新增经验库数据加载。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { conversationAPI, memoryAPI } from '@/shared/api/api'
import { experiencesAPI } from '@/features/experiences/experiencesApi'
import { ShortTermMemory, LongTermMemory } from '@/shared/types/api'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { appLogger } from '@/shared/utils/logger'
import { Toggle } from '@/shared/components/ui'
import styles from './MemoryPage.module.css'

/* ============================================================
 * 类型定义
 * ============================================================ */

/* 经验条目数据结构 —— 从 experiencesAPI 返回中提取所需字段 */
interface ExperienceItem {
  id: number
  title: string
  content: string
  confidence: number
  created_at: string
  last_access: string
}

/* 统一记忆列表项 —— 合并长期记忆与经验为统一展示模型 */
interface MemoryListItem {
  key: string
  content: string
  type: 'long-term' | 'experience'
  confidence: number
  time: string
  onDelete: (() => void) | null
}

/* 权重滑块组件入参 */
interface WeightSliderProps {
  label: string
  value: number
  onChange: (value: number) => void
  color: string
  ariaLabel: string
}

/* ============================================================
 * SVG 图标组件 —— 内联保持文件自包含，尺寸统一 20x20 / 18x18 / 16x16
 * ============================================================ */

const svgBase = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

/* 长期记忆图标（3D 盒子） */
const BoxIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" {...svgBase}>
    <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
    <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
    <line x1="12" y1="22.08" x2="12" y2="12" />
  </svg>
)

/* 短期记忆图标（文件） */
const FileIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" {...svgBase}>
    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
    <polyline points="13 2 13 9 20 9" />
  </svg>
)

/* 经验库图标（星形） */
const StarIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" {...svgBase}>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
)

/* 向量索引图标（地球） */
const GlobeIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" {...svgBase}>
    <circle cx="12" cy="12" r="10" />
    <line x1="2" y1="12" x2="22" y2="12" />
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
  </svg>
)

/* 趋势上升图标（折线 + 箭头） */
const TrendUpIcon = ({ color }: { color: string }) => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke={color}
    strokeWidth={2}
    strokeLinecap="round"
    strokeLinejoin="round"
    style={{ opacity: 0.4 }}
  >
    <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
    <polyline points="17 6 23 6 23 12" />
  </svg>
)

/* 搜索图标（放大镜） */
const SearchIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...svgBase}>
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
)

/* 搜索配置图标（放大镜带横线） */
const SearchConfigIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...svgBase}>
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
    <line x1="8" y1="11" x2="14" y2="11" />
  </svg>
)

/* 对勾圆圈图标（Memory Manager 状态） */
const CheckCircleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...svgBase}>
    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
    <polyline points="22 4 12 14.01 9 11.01" />
  </svg>
)

/* 3D 盒子图标（Auto-dream） */
const DreamIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...svgBase}>
    <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
    <line x1="12" y1="2" x2="12" y2="22" />
    <line x1="12" y1="12" x2="21" y2="8" />
    <line x1="12" y1="12" x2="3" y2="8" />
    <line x1="12" y1="22" x2="21" y2="16" />
    <line x1="12" y1="22" x2="3" y2="16" />
  </svg>
)

/* 刷新图标 */
const RefreshIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...svgBase}>
    <polyline points="23 4 23 10 17 10" />
    <polyline points="1 20 1 14 7 14" />
    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
  </svg>
)

/* 删除图标（垃圾桶） */
const TrashIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...svgBase}>
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    <line x1="10" y1="11" x2="10" y2="17" />
    <line x1="14" y1="11" x2="14" y2="17" />
  </svg>
)

/* ============================================================
 * 权重滑块组件 —— 对齐 Canvas 混合搜索配置滑块
 * 使用原生 range input（透明覆盖）+ 视觉轨道/填充/滑块
 * ============================================================ */

const WeightSlider = ({ label, value, onChange, color, ariaLabel }: WeightSliderProps) => {
  const percent = Math.round(value * 100)
  return (
    <div className={styles.sliderBlock}>
      <div className={styles.sliderHeader}>
        <span className={styles.sliderLabel}>{label}</span>
        <span className={styles.sliderValue}>{value.toFixed(1)}</span>
      </div>
      <div className={styles.sliderWrapper}>
        <div className={styles.sliderTrack}>
          <div className={styles.sliderFill} style={{ width: `${percent}%`, background: color }} />
        </div>
        <div
          className={styles.sliderThumb}
          style={{ left: `${percent}%`, background: color }}
          aria-hidden="true"
        />
        <input
          type="range"
          min={0}
          max={1}
          step={0.1}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className={styles.sliderInput}
          aria-label={ariaLabel}
        />
      </div>
    </div>
  )
}

/* ============================================================
 * 工具函数
 * ============================================================ */

function getErrorMessage(error: unknown, fallback: string): string {
  const maybeError = error as { response?: { status?: number, data?: { detail?: string } } }
  const status = maybeError?.response?.status
  const detail = maybeError?.response?.data?.detail

  if (status === 403) {
    return '当前会话不属于你，无法查看对应短期记忆，请先在聊天页发起新的对话。'
  }

  return typeof detail === 'string' && detail.trim() ? detail : fallback
}

/* 相对时间格式化 —— 将时间戳转为 "N天前" 形式 */
function formatRelativeTime(timestamp?: string): string {
  if (!timestamp) return '未知时间'
  const then = new Date(timestamp).getTime()
  if (isNaN(then)) return '未知时间'
  const diffMs = Date.now() - then
  if (diffMs < 0) return '刚刚'
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  if (diffDays <= 0) return '今天'
  if (diffDays === 1) return '1天前'
  if (diffDays < 7) return `${diffDays}天前`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}周前`
  return `${Math.floor(diffDays / 30)}月前`
}

/* ============================================================
 * 主页面组件
 * ============================================================ */

function MemoryPage() {
  /* ----- 数据状态 ----- */
  const [shortTermMemories, setShortTermMemories] = useState<ShortTermMemory[]>([])
  const [longTermMemories, setLongTermMemories] = useState<LongTermMemory[]>([])
  const [experiences, setExperiences] = useState<ExperienceItem[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [selectedSessionId, setSelectedSessionId] = useState('')
  const [searchQuery, setSearchQuery] = useState('')

  /* ----- 混合搜索配置状态 ----- */
  const [bm25Weight, setBm25Weight] = useState(0.3)
  const [vectorWeight, setVectorWeight] = useState(0.7)
  const [memoryDecay, setMemoryDecay] = useState(true)

  const chatSessionId = useSessionStore((state) => state.sessionId)

  /* 获取候选会话 ID 列表 —— 保持原有逻辑 */
  const getCandidateSessionIds = useCallback(async () => {
    const candidates = new Set<string>()

    if (chatSessionId && chatSessionId !== 'default') {
      candidates.add(chatSessionId)
    }

    const response = await conversationAPI.getRecordsPreview(20)
    for (const record of response.data.records || []) {
      const sessionId = String(record.session_id || '').trim()
      if (sessionId) {
        candidates.add(sessionId)
      }
    }

    return Array.from(candidates)
  }, [chatSessionId])

  /* 加载短期记忆 —— 保持原有逻辑 */
  const loadShortTermMemories = useCallback(async () => {
    const candidateSessionIds = await getCandidateSessionIds()

    if (candidateSessionIds.length === 0) {
      setSelectedSessionId('')
      setShortTermMemories([])
      return
    }

    for (const sessionId of candidateSessionIds) {
      try {
        const response = await memoryAPI.getShortTerm(sessionId)
        setSelectedSessionId(sessionId)
        setShortTermMemories(response.data)
        return
      } catch (error) {
        const status = (error as { response?: { status?: number } })?.response?.status
        if (status === 403) {
          continue
        }
        throw error
      }
    }

    setSelectedSessionId('')
    setShortTermMemories([])
  }, [getCandidateSessionIds])

  /* 加载所有数据 —— 短期 + 长期 + 经验，各数据源独立容错 */
  const loadAllData = useCallback(async () => {
    setLoading(true)
    setLoadError(null)

    /* 短期记忆加载 —— 优先执行，保证会话探测逻辑正常运行 */
    try {
      await loadShortTermMemories()
    } catch (error) {
      appLogger.error({
        event: 'memory_page_load_short_term_failed',
        module: 'memory',
        action: 'load_short_term',
        status: 'failure',
        message: '加载短期记忆失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      setLoadError(getErrorMessage(error, '加载短期记忆失败，请稍后重试'))
    }

    /* 长期记忆加载 */
    try {
      const response = await memoryAPI.getLongTerm()
      setLongTermMemories(response.data)
    } catch (error) {
      appLogger.error({
        event: 'memory_page_load_long_term_failed',
        module: 'memory',
        action: 'load_long_term',
        status: 'failure',
        message: '加载长期记忆失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      setLongTermMemories([])
    }

    /* 经验库数据加载 —— 独立 try/catch，失败不影响其他数据展示 */
    let experiencesData: ExperienceItem[] = []
    try {
      const response = await experiencesAPI.getExperiences({ limit: 50 })
      const rawData = response.data
      experiencesData = Array.isArray(rawData) ? (rawData as ExperienceItem[]) : []
    } catch (error) {
      appLogger.warning({
        event: 'memory_page_load_experiences_failed',
        module: 'memory',
        action: 'load_experiences',
        status: 'failure',
        message: '加载经验库失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
    setExperiences(experiencesData)

    setLoading(false)
  }, [loadShortTermMemories])

  /* 挂载时加载所有数据 */
  useEffect(() => {
    void loadAllData()
  }, [loadAllData])

  /* 删除长期记忆 —— 仅刷新长期列表，避免全量重载 */
  const handleDeleteLongTerm = async (id: number) => {
    setActionError(null)
    try {
      await memoryAPI.deleteLongTerm(id)
      const response = await memoryAPI.getLongTerm()
      setLongTermMemories(response.data)
    } catch (error) {
      appLogger.error({
        event: 'memory_page_delete_long_term_failed',
        module: 'memory',
        action: 'delete_long_term',
        status: 'failure',
        message: '删除长期记忆失败',
        extra: { memory_id: id, error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '删除长期记忆失败，请稍后重试'))
    }
  }

  /* 构建统一记忆列表 —— 合并长期记忆与经验，按时间倒序 */
  const unifiedList = useMemo<MemoryListItem[]>(() => {
    const items: MemoryListItem[] = []

    for (const mem of longTermMemories) {
      items.push({
        key: `lt-${mem.id}`,
        content: mem.content,
        type: 'long-term',
        confidence: mem.importance,
        time: mem.created_at || mem.last_access || '',
        onDelete: () => void handleDeleteLongTerm(mem.id),
      })
    }

    for (const exp of experiences) {
      items.push({
        key: `exp-${exp.id}`,
        content: exp.title || exp.content,
        type: 'experience',
        confidence: exp.confidence,
        time: exp.created_at || exp.last_access || '',
        onDelete: null,
      })
    }

    /* 按时间倒序排列 —— 有时间的在前，无时间的在后 */
    items.sort((a, b) => {
      const timeA = a.time ? new Date(a.time).getTime() : 0
      const timeB = b.time ? new Date(b.time).getTime() : 0
      return timeB - timeA
    })

    return items
    // handleDeleteLongTerm 不作为依赖 —— 它是组件内函数，每次渲染都重新创建
  }, [longTermMemories, experiences])

  /* 搜索过滤 —— 按内容模糊匹配 */
  const filteredList = useMemo<MemoryListItem[]>(() => {
    if (!searchQuery.trim()) return unifiedList
    const query = searchQuery.toLowerCase()
    return unifiedList.filter((item) => item.content.toLowerCase().includes(query))
  }, [unifiedList, searchQuery])

  if (loading && longTermMemories.length === 0 && shortTermMemories.length === 0) {
    return <div className={styles.loading}>加载中...</div>
  }

  /* 统计数值 */
  const longTermCount = longTermMemories.length
  const shortTermCount = shortTermMemories.length
  const experienceCount = experiences.length
  const vectorCount = longTermCount /* 每条长期记忆对应一个向量索引 */

  return (
    <div className={styles.memoryPage}>
      {/* ========== 页面标题 ========== */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>记忆管理</h1>
          <p className={styles.pageSubtitle}>AI 记忆系统状态与配置</p>
        </div>
        <div className={styles.pageActions}>
          <button
            className={styles.btnSecondary}
            onClick={() => void loadAllData()}
            disabled={loading}
          >
            <RefreshIcon />
            刷新
          </button>
        </div>
      </div>

      {/* ========== 统计概览卡片（4 列） ========== */}
      <div className={styles.statGrid}>
        {/* 长期记忆 */}
        <div className={styles.statCard}>
          <div className={styles.statTop}>
            <div className={styles.statIconBox} style={{ background: 'var(--color-primary-soft-bg)' }}>
              <span style={{ color: 'var(--color-primary)' }}><BoxIcon /></span>
            </div>
            <TrendUpIcon color="var(--color-primary)" />
          </div>
          <p className={styles.statValue}>{longTermCount.toLocaleString()}</p>
          <p className={styles.statLabel}>长期记忆</p>
        </div>

        {/* 短期记忆 */}
        <div className={styles.statCard}>
          <div className={styles.statTop}>
            <div className={styles.statIconBox} style={{ background: 'var(--color-success-bg)' }}>
              <span style={{ color: 'var(--color-success)' }}><FileIcon /></span>
            </div>
            <span className={styles.sessionBadge}>当前会话</span>
          </div>
          <p className={styles.statValue}>{shortTermCount.toLocaleString()}</p>
          <p className={styles.statLabel}>短期记忆</p>
        </div>

        {/* 经验库 */}
        <div className={styles.statCard}>
          <div className={styles.statTop}>
            <div className={styles.statIconBox} style={{ background: 'var(--color-tag-purple-bg)' }}>
              <span style={{ color: 'var(--color-chart-5)' }}><StarIcon /></span>
            </div>
            <TrendUpIcon color="var(--color-chart-5)" />
          </div>
          <p className={styles.statValue}>{experienceCount.toLocaleString()}</p>
          <p className={styles.statLabel}>经验库</p>
        </div>

        {/* 向量索引 */}
        <div className={styles.statCard}>
          <div className={styles.statTop}>
            <div className={styles.statIconBox} style={{ background: 'var(--color-warning-soft-bg)' }}>
              <span style={{ color: 'var(--color-warning)' }}><GlobeIcon /></span>
            </div>
            <TrendUpIcon color="var(--color-warning)" />
          </div>
          <p className={styles.statValue}>{vectorCount.toLocaleString()}</p>
          <p className={styles.statLabel}>向量索引</p>
        </div>
      </div>

      {/* ========== 错误提示 ========== */}
      {loadError && <div className={styles.errorMessage}>{loadError}</div>}
      {actionError && <div className={styles.errorMessage}>{actionError}</div>}

      {/* ========== 三栏布局：左侧记忆列表 + 右侧系统状态 ========== */}
      <div className={styles.mainLayout}>
        {/* 左侧：记忆条目列表 */}
        <div className={styles.memoryListColumn}>
          {/* 会话提示 —— 保持原有功能 */}
          {selectedSessionId && (
            <div className={styles.sessionHint}>
              当前查看会话：{selectedSessionId}
            </div>
          )}
          <div className={styles.listCard}>
            {/* 标题 + 搜索 */}
            <div className={styles.listHeader}>
              <div className={styles.listHeaderTop}>
                <h2 className={styles.listTitle}>记忆条目</h2>
                <span className={styles.countBadge}>共 {filteredList.length} 条</span>
              </div>
              <div className={styles.searchWrap}>
                <span className={styles.searchIcon}><SearchIcon /></span>
                <input
                  type="text"
                  placeholder="搜索记忆内容..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className={styles.searchInput}
                />
              </div>
            </div>

            {/* 记忆条目列表 */}
            {filteredList.length === 0 ? (
              <div className={styles.emptyState}>
                <p>{searchQuery.trim() ? '未找到匹配的记忆' : '暂无记忆数据'}</p>
              </div>
            ) : (
              <div className={styles.listItems}>
                {filteredList.map((item) => (
                  <div key={item.key} className={styles.memoryItem}>
                    <div className={styles.memoryItemTop}>
                      <p className={styles.memoryItemTitle}>{item.content}</p>
                      <span
                        className={
                          item.type === 'long-term'
                            ? styles.typeBadgeLongTerm
                            : styles.typeBadgeExperience
                        }
                      >
                        {item.type === 'long-term' ? '长期记忆' : '经验'}
                      </span>
                    </div>
                    <div className={styles.memoryItemBottom}>
                      <span className={styles.memoryTime}>
                        {formatRelativeTime(item.time)}
                      </span>
                      <div className={styles.confidenceWrap}>
                        <span className={styles.confidenceLabel}>置信度</span>
                        <div className={styles.confidenceTrack}>
                          <div
                            className={styles.confidenceFill}
                            style={{
                              width: `${Math.round(item.confidence * 100)}%`,
                              background: item.type === 'long-term'
                                ? 'var(--color-primary)'
                                : 'var(--color-chart-5)',
                            }}
                          />
                        </div>
                        <span
                          className={styles.confidenceValue}
                          style={{
                            color: item.type === 'long-term'
                              ? 'var(--color-primary)'
                              : 'var(--color-chart-5)',
                          }}
                        >
                          {item.confidence.toFixed(2)}
                        </span>
                      </div>
                      {item.onDelete && (
                        <button
                          className={styles.deleteBtn}
                          onClick={(e) => {
                            e.stopPropagation()
                            item.onDelete?.()
                          }}
                          aria-label="删除"
                        >
                          <TrashIcon />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 右侧：系统状态侧栏 */}
        <aside className={styles.sidebar}>
          {/* Memory Manager 状态 */}
          <div className={styles.sidebarCard}>
            <div className={styles.sidebarHeader}>
              <div className={styles.sidebarIconBox} style={{ background: 'var(--color-success-soft-bg)' }}>
                <span style={{ color: 'var(--color-success)' }}><CheckCircleIcon /></span>
              </div>
              <h3 className={styles.sidebarTitle}>Memory Manager</h3>
            </div>
            <div className={styles.kvList}>
              <div className={styles.kvRow}>
                <span className={styles.kvLabel}>状态</span>
                <div className={styles.kvStatus}>
                  <span className={styles.statusDot} />
                  <span className={styles.kvStatusText}>运行中</span>
                </div>
              </div>
              <div className={styles.kvRow}>
                <span className={styles.kvLabel}>向量数据库</span>
                <span className={styles.kvValue}>ChromaDB</span>
              </div>
              <div className={styles.kvRow}>
                <span className={styles.kvLabel}>存储路径</span>
                <code className={styles.codeValue}>./data/vector_db</code>
              </div>
              <div className={styles.kvRow}>
                <span className={styles.kvLabel}>自动整理</span>
                <span className={styles.kvValue}>每日 03:00</span>
              </div>
            </div>
          </div>

          {/* Hybrid Search 配置 */}
          <div className={styles.sidebarCard}>
            <div className={styles.sidebarHeader}>
              <div className={styles.sidebarIconBox} style={{ background: 'var(--color-primary-soft-bg)' }}>
                <span style={{ color: 'var(--color-primary)' }}><SearchConfigIcon /></span>
              </div>
              <h3 className={styles.sidebarTitle}>Hybrid Search 配置</h3>
            </div>
            <div className={styles.sliderList}>
              <WeightSlider
                label="BM25 权重"
                value={bm25Weight}
                onChange={setBm25Weight}
                color="var(--color-primary)"
                ariaLabel="BM25 权重"
              />
              <WeightSlider
                label="向量权重"
                value={vectorWeight}
                onChange={setVectorWeight}
                color="var(--color-chart-5)"
                ariaLabel="向量权重"
              />
              <div className={styles.toggleRow}>
                <span className={styles.kvLabel}>记忆衰减</span>
                <Toggle checked={memoryDecay} onChange={setMemoryDecay} size="md" aria-label="记忆衰减" />
              </div>
            </div>
          </div>

          {/* Auto-dream 配置 */}
          <div className={styles.sidebarCard}>
            <div className={styles.sidebarHeader}>
              <div className={styles.sidebarIconBox} style={{ background: 'var(--color-warning-soft-bg)' }}>
                <span style={{ color: 'var(--color-warning)' }}><DreamIcon /></span>
              </div>
              <h3 className={styles.sidebarTitle}>Auto-dream 配置</h3>
            </div>
            <div className={styles.kvList}>
              <div className={styles.kvRow}>
                <span className={styles.kvLabel}>状态</span>
                <div className={styles.kvStatus}>
                  <span className={styles.statusDot} />
                  <span className={styles.kvStatusText}>已启用</span>
                </div>
              </div>
              <div className={styles.kvRow}>
                <span className={styles.kvLabel}>触发条件</span>
                <span className={styles.kvValue}>记忆 &gt; 1000条</span>
              </div>
              <div className={styles.kvRow}>
                <span className={styles.kvLabel}>执行频率</span>
                <span className={styles.kvValue}>每周一次</span>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}

export default MemoryPage
