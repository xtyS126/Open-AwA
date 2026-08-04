/**
 * 记忆管理页面 —— 对齐 Canvas 设计参考 (open-awa-canvas/pages/memory.html)。
 * 结构：页面标题 / 统计卡片 / 左侧记忆列表 + 右侧系统状态侧栏。
 * 数据获取通过 TanStack Query 管理服务端状态（短期/长期记忆独立查询）。
 *
 * Spec memory-quality-and-short-term-recovery Task 16：
 * 页面顶部新增 tab 切换器（长期记忆 / 短期记忆），默认展示长期记忆。
 * 切换到短期记忆 tab 时渲染 ShortTermMemoryList 组件。
 *
 * Spec memory-experience-redesign：
 * 1. 短期记忆 tab 标题澄清为"对话记录（短期记忆）"，明确其定位
 * 2. 长期记忆列表展示真实置信度（confidence）、来源标签（source_type）、状态徽章（state）
 * 3. 列表操作新增"准确 / 不准确"验证闭环（validate / deprecate）
 * 4. 侧栏 Hybrid Search 滑块接入 vector-search 真实权重；记忆衰减开关接入 decay-config
 * 5. 统计卡接入 /memory/stats 真实数据，替换硬编码假统计
 * 6. 新增"质量评估"tab（/memory/quality）与"立即巩固"操作（/memory/consolidation/run）
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { conversationAPI, memoryAPI } from '@/shared/api/api'
import { ShortTermMemory, LongTermMemory } from '@/shared/types/api'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { appLogger } from '@/shared/utils/logger'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import { Toggle } from '@/shared/components/ui'
import { useI18nStore } from '@/i18n'
import ShortTermMemoryList from './ShortTermMemoryList'
import styles from './MemoryPage.module.css'

/* ============================================================
 * 类型定义
 * ============================================================ */

/* 统一记忆列表项 —— 长期记忆展示模型 */
interface MemoryListItem {
  key: string
  content: string
  type: 'long-term'
  confidence: number
  importance: number
  sourceType: string
  state: string
  accessCount: number
  time: string
  onDelete: (() => void) | null
  onValidate: (() => void) | null
  onDeprecate: (() => void) | null
}

/* 权重滑块组件入参 */
interface WeightSliderProps {
  label: string
  value: number
  onChange: (value: number) => void
  color: string
  ariaLabel: string
}

/* 记忆统计 —— GET /memory/stats 返回结构 */
interface MemoryStats {
  total_memories: number
  active_memories: number
  archived_memories: number
  average_confidence: number
  average_quality_score: number
  total_access_count: number
  working_memory_count: number
  vector_store_count: number
}

/* 记忆质量报告项 —— GET /memory/quality 返回结构 */
interface MemoryQualityItem {
  id: number
  content: string
  confidence: number
  quality_score: number
  importance?: number
  access_count?: number
  state?: string
  archive_status?: string
  last_access?: string
}

/* 记忆衰减配置 —— GET /memory/decay-config 返回结构 */
interface DecayConfigItem {
  layer: string
  decay_function: string
  half_life_days: number
  threshold: number
  enabled: boolean
}

/* ============================================================
 * 来源类型 → 展示文案与样式映射
 * ============================================================ */

const SOURCE_TYPE_LABELS: Record<string, string> = {
  llm_extracted: '自动提炼',
  user_input: '关键词触发',
  manual: '手动添加',
  plugin: '插件写入',
  preference: '偏好',
  fact: '事实',
  decision: '决策',
  knowledge: '知识',
  other: '其他',
}

const STATE_LABELS: Record<string, string> = {
  active: '活跃',
  validated: '已验证',
  archived: '已归档',
  deprecated: '已遗忘',
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
    <polyline points="23 6 13.5 12.5 8.5 10.5 1 18" />
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

/* 准确图标（对勾）—— 用户验证闭环 */
const CheckIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...svgBase}>
    <polyline points="20 6 9 17 4 12" />
  </svg>
)

/* 不准确图标（叉）—— 用户验证闭环 */
const XIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...svgBase}>
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
)

/* 质量评估图标（测体温表） */
const GaugeIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...svgBase}>
    <path d="M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z" />
    <path d="M14 4h4v16a6 6 0 0 1-12 0V4h4" />
    <path d="M12 4v10" />
  </svg>
)

/* 播放图标（立即巩固） */
const PlayIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...svgBase}>
    <polygon points="6 3 20 12 6 21 6 3" fill="currentColor" stroke="none" />
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

/* 来源类型展示文案（未知值回退原始值） */
function sourceTypeLabel(sourceType?: string): string {
  if (!sourceType) return '手动添加'
  return SOURCE_TYPE_LABELS[sourceType] ?? sourceType
}

/* 状态徽章文案 */
function stateLabel(state?: string): string {
  if (!state) return '活跃'
  return STATE_LABELS[state] ?? state
}

/* 置信度颜色 —— 按分数分级 */
function confidenceColor(confidence: number): string {
  if (confidence >= 0.8) return 'var(--color-success)'
  if (confidence >= 0.5) return 'var(--color-primary)'
  return 'var(--color-warning)'
}

/* 状态徽章 CSS 类映射 —— state 英文值 → CSS Module 类名 */
const STATE_BADGE_CLASSES: Record<string, string> = {
  active: 'stateBadgeActive',
  validated: 'stateBadgeValidated',
  archived: 'stateBadgeArchived',
  deprecated: 'stateBadgeDeprecated',
}

/* ============================================================
 * 主页面组件
 * ============================================================ */

function MemoryPage() {
  /* ----- i18n 与本地用户输入状态 ----- */
  const t = useI18nStore(s => s.t)
  const [searchQuery, setSearchQuery] = useState('')
  const [bm25Weight, setBm25Weight] = useState(0.3)
  const [vectorWeight, setVectorWeight] = useState(0.7)
  /* 操作错误状态（删除操作等本地错误，不依赖服务端查询） */
  const [actionError, setActionError] = useState<string | null>(null)
  /* 巩固操作结果提示 */
  const [consolidationResult, setConsolidationResult] = useState<string | null>(null)
  /* 当前展示的会话 ID（由短期记忆 queryFn 内部决定） */
  const [selectedSessionId, setSelectedSessionId] = useState('')
  /* Spec Task 16：tab 切换器 —— 'long-term' 默认保持现有行为 */
  const [activeTab, setActiveTab] = useState<'long-term' | 'short-term' | 'quality'>('long-term')

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

  /* 短期记忆查询 —— TanStack Query 管理，queryFn 内部执行候选 sessionId 循环逻辑 */
  const shortTermQuery = useQuery<{
    memories: ShortTermMemory[]
    sessionId: string
  }>({
    queryKey: ['memory', 'short-term', chatSessionId],
    queryFn: async () => {
      const candidateSessionIds = await getCandidateSessionIds()

      if (candidateSessionIds.length === 0) {
        return { memories: [], sessionId: '' }
      }

      for (const sessionId of candidateSessionIds) {
        try {
          const response = await memoryAPI.getShortTerm(sessionId)
          return { memories: response.data, sessionId }
        } catch (error) {
          const status = (error as { response?: { status?: number } })?.response?.status
          if (status === 403) {
            continue
          }
          throw error
        }
      }

      return { memories: [], sessionId: '' }
    },
    retry: false,
  })

  /* 长期记忆查询 —— 无搜索词时展示全部，有搜索词时走混合检索（权重随滑块生效） */
  const longTermQuery = useQuery<LongTermMemory[]>({
    queryKey: ['memory', 'long-term', searchQuery.trim(), bm25Weight, vectorWeight],
    queryFn: async () => {
      const query = searchQuery.trim()
      if (query) {
        const response = await memoryAPI.vectorSearch({
          query,
          keyword_weight: bm25Weight,
          vector_weight: vectorWeight,
        })
        return response.data
      }
      const response = await memoryAPI.getLongTerm()
      return response.data
    },
    retry: false,
  })

  /* 记忆统计 —— Spec memory-experience-redesign：替换硬编码统计卡 */
  const statsQuery = useQuery<MemoryStats | null>({
    queryKey: ['memory', 'stats'],
    queryFn: async () => {
      const response = await memoryAPI.getStats()
      return (response.data as MemoryStats) ?? null
    },
    retry: false,
  })

  /* 记忆衰减配置 —— Spec memory-experience-redesign：开关回显真实配置 */
  const decayConfigQuery = useQuery<DecayConfigItem | null>({
    queryKey: ['memory', 'decay-config'],
    queryFn: async () => {
      const response = await memoryAPI.getDecayConfig()
      const data = response.data?.data ?? {}
      return data['semantic'] ?? null
    },
    retry: false,
  })

  /* 记忆质量报告 —— Spec memory-experience-redesign：质量评估 tab */
  const qualityQuery = useQuery<MemoryQualityItem[]>({
    queryKey: ['memory', 'quality'],
    queryFn: async () => {
      const response = await memoryAPI.getQuality(50)
      return (response.data as MemoryQualityItem[]) ?? []
    },
    retry: false,
    enabled: activeTab === 'quality',
  })

  const shortTermMemories = shortTermQuery.data?.memories ?? []
  /* useMemo 包装避免每次渲染产生新引用（react-hooks/exhaustive-deps 警告） */
  const longTermMemories = useMemo<LongTermMemory[]>(
    () => longTermQuery.data ?? [],
    [longTermQuery.data]
  )

  // 同步短期记忆查询返回的 selectedSessionId 到本地状态（用于 UI 展示）
  useEffect(() => {
    setSelectedSessionId(shortTermQuery.data?.sessionId ?? '')
  }, [shortTermQuery.data?.sessionId])

  /* 派生 loading / loadError 状态 */
  const loading = shortTermQuery.isInitialLoading || longTermQuery.isInitialLoading
  const loadError = shortTermQuery.error
    ? getErrorMessage(shortTermQuery.error, '加载短期记忆失败，请稍后重试')
    : longTermQuery.error
      ? getErrorMessage(longTermQuery.error, '加载长期记忆失败，请稍后重试')
      : null

  /* 失败时记录日志（不影响其他数据展示） */
  useEffect(() => {
    if (shortTermQuery.error) {
      const error = shortTermQuery.error
      appLogger.error({
        event: 'memory_page_load_short_term_failed',
        module: 'memory',
        action: 'load_short_term',
        status: 'failure',
        message: '加载短期记忆失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
  }, [shortTermQuery.error])

  useEffect(() => {
    if (longTermQuery.error) {
      const error = longTermQuery.error
      appLogger.error({
        event: 'memory_page_load_long_term_failed',
        module: 'memory',
        action: 'load_long_term',
        status: 'failure',
        message: '加载长期记忆失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
  }, [longTermQuery.error])

  /* 刷新所有数据 —— 同时重新获取短期 + 长期 + 统计 */
  const refreshAll = useCallback(() => {
    void shortTermQuery.refetch()
    void longTermQuery.refetch()
    void statsQuery.refetch()
    void decayConfigQuery.refetch()
  }, [shortTermQuery, longTermQuery, statsQuery, decayConfigQuery])

  /* 删除长期记忆 —— 失效长期记忆查询，触发后台刷新 */
  const handleDeleteLongTerm = useCallback(async (id: number) => {
    setActionError(null)
    try {
      await memoryAPI.deleteLongTerm(id)
      await longTermQuery.refetch()
      void statsQuery.refetch()
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
  }, [longTermQuery, statsQuery])

  /* 用户验证闭环：确认记忆准确（validated 晋升） */
  const handleValidateLongTerm = useCallback(async (id: number) => {
    setActionError(null)
    try {
      await memoryAPI.validateLongTerm(id)
      await longTermQuery.refetch()
    } catch (error) {
      appLogger.error({
        event: 'memory_page_validate_long_term_failed',
        module: 'memory',
        action: 'validate_long_term',
        status: 'failure',
        message: '确认记忆准确失败',
        extra: { memory_id: id, error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '确认记忆失败，请稍后重试'))
    }
  }, [longTermQuery])

  /* 用户验证闭环：主动遗忘（deprecated） */
  const handleDeprecateLongTerm = useCallback(async (id: number) => {
    setActionError(null)
    try {
      await memoryAPI.deprecateLongTerm(id)
      await longTermQuery.refetch()
      void statsQuery.refetch()
    } catch (error) {
      appLogger.error({
        event: 'memory_page_deprecate_long_term_failed',
        module: 'memory',
        action: 'deprecate_long_term',
        status: 'failure',
        message: '遗忘记忆失败',
        extra: { memory_id: id, error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '遗忘记忆失败，请稍后重试'))
    }
  }, [longTermQuery, statsQuery])

  /* 记忆衰减开关 —— Spec memory-experience-redesign：真实持久化 */
  const handleDecayToggle = useCallback(async (enabled: boolean) => {
    setActionError(null)
    try {
      const current = decayConfigQuery.data
      await memoryAPI.updateDecayConfig({
        layer: 'semantic',
        enabled,
        decay_function: current?.decay_function,
        half_life_days: current?.half_life_days,
        threshold: current?.threshold,
      })
      await decayConfigQuery.refetch()
    } catch (error) {
      appLogger.error({
        event: 'memory_page_update_decay_config_failed',
        module: 'memory',
        action: 'update_decay_config',
        status: 'failure',
        message: '更新记忆衰减配置失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '更新记忆衰减配置失败，请稍后重试'))
    }
  }, [decayConfigQuery])

  /* 手动触发记忆巩固 —— Spec memory-experience-redesign */
  const handleRunConsolidation = useCallback(async () => {
    setActionError(null)
    setConsolidationResult(null)
    try {
      const response = await memoryAPI.runConsolidation()
      const data = response.data
      if (data.success) {
        setConsolidationResult(
          `巩固完成：处理 ${data.processed ?? 0} 条，提炼 ${data.extracted ?? 0} 条，写入 ${data.consolidated ?? 0} 条，归档 ${data.archived ?? 0} 条`
        )
      } else {
        setConsolidationResult(`巩固未完成：${data.error ?? '未知错误'}`)
      }
      void longTermQuery.refetch()
      void statsQuery.refetch()
    } catch (error) {
      appLogger.error({
        event: 'memory_page_run_consolidation_failed',
        module: 'memory',
        action: 'run_consolidation',
        status: 'failure',
        message: '手动触发记忆巩固失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '触发记忆巩固失败，请稍后重试'))
    }
  }, [longTermQuery, statsQuery])

  /* 构建记忆列表 —— 仅长期记忆，按时间倒序 */
  const unifiedList = useMemo<MemoryListItem[]>(() => {
    const items: MemoryListItem[] = []

    for (const mem of longTermMemories) {
      const validated = mem.state === 'validated'
      const archived = mem.state === 'archived' || mem.archive_status === 'archived'
      items.push({
        key: `lt-${mem.id}`,
        content: mem.content,
        type: 'long-term',
        confidence: mem.confidence ?? mem.importance,
        importance: mem.importance,
        sourceType: mem.source_type ?? '',
        state: mem.state ?? 'active',
        accessCount: mem.access_count ?? 0,
        time: mem.created_at || mem.last_access || '',
        onDelete: archived ? null : () => void handleDeleteLongTerm(mem.id),
        onValidate: validated ? null : () => void handleValidateLongTerm(mem.id),
        onDeprecate: archived || validated ? null : () => void handleDeprecateLongTerm(mem.id),
      })
    }

    /* 按时间倒序排列 —— 有时间的在前，无时间的在后 */
    items.sort((a, b) => {
      const timeA = a.time ? new Date(a.time).getTime() : 0
      const timeB = b.time ? new Date(b.time).getTime() : 0
      return timeB - timeA
    })

    return items
  }, [longTermMemories, handleDeleteLongTerm, handleValidateLongTerm, handleDeprecateLongTerm])

  /* 质量报告按置信度升序（最需关注的在最前）—— 必须在 early return 之前声明 */
  const qualityItems = useMemo(() => {
    const items = qualityQuery.data ?? []
    return [...items].sort((a, b) => (a.confidence ?? 0) - (b.confidence ?? 0))
  }, [qualityQuery.data])

  if (loading && longTermMemories.length === 0 && shortTermMemories.length === 0) {
    return <div className={styles.loading}>加载中...</div>
  }

  /* 统计数值 —— 真实 stats，缺省时回退列表长度 */
  const stats = statsQuery.data
  const longTermCount = stats ? stats.total_memories : longTermMemories.length
  const activeCount = stats ? stats.active_memories : longTermMemories.length
  const avgConfidence = stats ? stats.average_confidence : 0
  const vectorCount = stats ? stats.vector_store_count : longTermMemories.length
  const shortTermCount = shortTermMemories.length

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
            onClick={() => void handleRunConsolidation()}
            disabled={loading}
          >
            <PlayIcon />
            立即巩固
          </button>
          <button
            className={styles.btnSecondary}
            onClick={refreshAll}
            disabled={loading}
          >
            <RefreshIcon />
            刷新
          </button>
        </div>
      </div>

      {/* ========== 统计概览卡片（真实 stats） ========== */}
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

        {/* 活跃记忆 */}
        <div className={styles.statCard}>
          <div className={styles.statTop}>
            <div className={styles.statIconBox} style={{ background: 'var(--color-success-bg)' }}>
              <span style={{ color: 'var(--color-success)' }}><CheckCircleIcon /></span>
            </div>
            <span className={styles.sessionBadge}>未归档</span>
          </div>
          <p className={styles.statValue}>{activeCount.toLocaleString()}</p>
          <p className={styles.statLabel}>活跃记忆</p>
        </div>

        {/* 平均置信度 */}
        <div className={styles.statCard}>
          <div className={styles.statTop}>
            <div className={styles.statIconBox} style={{ background: 'var(--color-warning-soft-bg)' }}>
              <span style={{ color: 'var(--color-warning)' }}><GaugeIcon /></span>
            </div>
            <TrendUpIcon color="var(--color-warning)" />
          </div>
          <p className={styles.statValue}>{avgConfidence.toFixed(2)}</p>
          <p className={styles.statLabel}>平均置信度</p>
        </div>

        {/* 向量索引 */}
        <div className={styles.statCard}>
          <div className={styles.statTop}>
            <div className={styles.statIconBox} style={{ background: 'var(--color-chart-5-bg, var(--color-bg-tertiary))' }}>
              <span style={{ color: 'var(--color-chart-5)' }}><GlobeIcon /></span>
            </div>
            <TrendUpIcon color="var(--color-chart-5)" />
          </div>
          <p className={styles.statValue}>{vectorCount.toLocaleString()}</p>
          <p className={styles.statLabel}>向量索引</p>
        </div>
      </div>

      {/* ========== 错误提示 ========== */}
      {loadError && <div className={styles.errorMessage}>{loadError}</div>}
      {actionError && <div className={styles.errorMessage}>{actionError}</div>}
      {consolidationResult && <div className={styles.successMessage}>{consolidationResult}</div>}

      {/* ========== 三栏布局：左侧记忆列表 + 右侧系统状态 ========== */}
      <div className={styles.mainLayout}>
        {/* 左侧：记忆条目列表 */}
        <div className={styles.memoryListColumn}>
          {/* Spec Task 16：tab 切换器 —— 长期记忆 / 对话记录 / 质量评估 */}
          <div className={styles.tabBar} role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'long-term'}
              className={`${styles.tabButton} ${activeTab === 'long-term' ? styles.tabButtonActive : ''}`}
              onClick={() => setActiveTab('long-term')}
            >
              长期记忆
              <span className={`${styles.tabCountBadge} ${activeTab === 'long-term' ? styles.tabCountBadgeActive : ''}`}>
                {longTermCount}
              </span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'short-term'}
              className={`${styles.tabButton} ${activeTab === 'short-term' ? styles.tabButtonActive : ''}`}
              onClick={() => setActiveTab('short-term')}
            >
              对话记录
              <span className={`${styles.tabCountBadge} ${activeTab === 'short-term' ? styles.tabCountBadgeActive : ''}`}>
                {shortTermCount}
              </span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'quality'}
              className={`${styles.tabButton} ${activeTab === 'quality' ? styles.tabButtonActive : ''}`}
              onClick={() => setActiveTab('quality')}
            >
              质量评估
            </button>
          </div>

          {/* Spec memory-experience-redesign：短期记忆 tab 澄清为对话记录 */}
          {activeTab === 'short-term' ? (
            <ShortTermMemoryList initialLimit={50} />
          ) : activeTab === 'quality' ? (
            /* ========== 质量评估视图 ========== */
            <div className={styles.listCard}>
              <div className={styles.listHeader}>
                <div className={styles.listHeaderTop}>
                  <h2 className={styles.listTitle}>记忆质量评估</h2>
                  <span className={styles.countBadge}>共 {qualityItems.length} 条</span>
                </div>
                <p className={styles.qualityHint}>
                  按置信度升序排列：越靠前的记忆越需要关注（可验证准确或主动遗忘）
                </p>
              </div>
              {qualityItems.length === 0 ? (
                <div className={styles.emptyState}>
                  <p>暂无质量评估数据</p>
                </div>
              ) : (
                <div className={styles.listItems}>
                  {qualityItems.map((item) => (
                    <div key={`q-${item.id}`} className={styles.memoryItem}>
                      <div className={styles.memoryItemTop}>
                        <p className={styles.memoryItemTitle}>{item.content}</p>
                        <span className={`${styles.stateBadge} ${styles.stateBadgeActive}`}>
                          {stateLabel(item.state)}
                        </span>
                      </div>
                      <div className={styles.memoryItemBottom}>
                        <span className={styles.memoryTime}>
                          {formatRelativeTime(item.last_access)}
                        </span>
                        <div className={styles.confidenceWrap}>
                          <span className={styles.confidenceLabel}>置信度</span>
                          <div className={styles.confidenceTrack}>
                            <div
                              className={styles.confidenceFill}
                              style={{
                                width: `${Math.round((item.confidence ?? 0) * 100)}%`,
                                background: confidenceColor(item.confidence ?? 0),
                              }}
                            />
                          </div>
                          <span
                            className={styles.confidenceValue}
                            style={{ color: confidenceColor(item.confidence ?? 0) }}
                          >
                            {(item.confidence ?? 0).toFixed(2)}
                          </span>
                        </div>
                        <span className={styles.memoryTime}>
                          质量 {item.quality_score?.toFixed(2) ?? '-'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <>
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
                    <span className={styles.countBadge}>共 {unifiedList.length} 条</span>
                  </div>
                  <div className={styles.searchWrap}>
                    <span className={styles.searchIcon}><SearchIcon /></span>
                    <input
                      type="text"
                      placeholder="搜索记忆内容（混合检索）..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className={styles.searchInput}
                    />
                  </div>
                  {searchQuery.trim() && (
                    <p className={styles.qualityHint}>
                      已按 BM25 {bm25Weight.toFixed(1)} / 向量 {vectorWeight.toFixed(1)} 权重混合检索
                    </p>
                  )}
                </div>

                {/* 记忆条目列表 */}
                {unifiedList.length === 0 ? (
                  <div className={styles.emptyState}>
                    <p>{searchQuery.trim() ? '未找到匹配的记忆' : '暂无记忆数据'}</p>
                  </div>
                ) : (
                  <div className={styles.listItems}>
                    {unifiedList.map((item) => (
                      <div key={item.key} className={styles.memoryItem}>
                        <div className={styles.memoryItemTop}>
                          <p className={styles.memoryItemTitle}>{item.content}</p>
                          <div className={styles.memoryItemBadges}>
                            <span className={styles.typeBadgeLongTerm}>
                              {sourceTypeLabel(item.sourceType)}
                            </span>
                            <span className={`${styles.stateBadge} ${styles[STATE_BADGE_CLASSES[item.state] ?? 'stateBadgeActive']}`}>
                              {stateLabel(item.state)}
                            </span>
                          </div>
                        </div>
                        <div className={styles.memoryItemBottom}>
                          <span className={styles.memoryTime}>
                            {formatRelativeTime(item.time)}
                          </span>
                          <span className={styles.memoryTime}>
                            {item.accessCount} 次访问
                          </span>
                          <div className={styles.confidenceWrap}>
                            <span className={styles.confidenceLabel}>置信度</span>
                            <div className={styles.confidenceTrack}>
                              <div
                                className={styles.confidenceFill}
                                style={{
                                  width: `${Math.round(item.confidence * 100)}%`,
                                  background: confidenceColor(item.confidence),
                                }}
                              />
                            </div>
                            <span
                              className={styles.confidenceValue}
                              style={{ color: confidenceColor(item.confidence) }}
                            >
                              {item.confidence.toFixed(2)}
                            </span>
                          </div>
                          {item.onValidate && (
                            <button
                              className={styles.validateBtn}
                              onClick={(e) => {
                                e.stopPropagation()
                                item.onValidate?.()
                              }}
                              aria-label="准确"
                              title="记忆准确，验证后不再参与归档"
                            >
                              <CheckIcon />
                            </button>
                          )}
                          {item.onDeprecate && (
                            <button
                              className={styles.deprecateBtn}
                              onClick={(e) => {
                                e.stopPropagation()
                                item.onDeprecate?.()
                              }}
                              aria-label="不准确"
                              title="记忆不准确，主动遗忘"
                            >
                              <XIcon />
                            </button>
                          )}
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
            </>
          )}
        </div>

        {/* 右侧：系统状态侧栏 */}
        <aside className={styles.sidebar}>
          {/* Memory Manager 状态 */}
          <div className={styles.sidebarCard}>
            <div className={styles.sidebarHeader}>
              <div className={styles.sidebarIconBox} style={{ background: 'var(--color-success-soft-bg)' }}>
                <span style={{ color: 'var(--color-success)' }}><CheckCircleIcon /></span>
              </div>
              <h3 className={styles.sidebarTitle}>{t('memory.managerTitle')}</h3>
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
                <span className={styles.kvLabel}>长期记忆</span>
                <span className={styles.kvValue}>{longTermCount.toLocaleString()} 条</span>
              </div>
              <div className={styles.kvRow}>
                <span className={styles.kvLabel}>已归档</span>
                <span className={styles.kvValue}>
                  {(stats ? stats.archived_memories : 0).toLocaleString()} 条
                </span>
              </div>
              <div className={styles.kvRow}>
                <span className={styles.kvLabel}>累计访问</span>
                <span className={styles.kvValue}>
                  {(stats ? stats.total_access_count : 0).toLocaleString()} 次
                </span>
              </div>
              <div className={styles.kvRow}>
                <span className={styles.kvLabel}>存储路径</span>
                <code className={styles.codeValue}>var/data/qdrant</code>
              </div>
            </div>
          </div>

          {/* Hybrid Search 配置 —— Spec memory-experience-redesign：滑块真实生效 */}
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
                <Toggle
                  checked={decayConfigQuery.data?.enabled ?? true}
                  onChange={handleDecayToggle}
                  size="md"
                  aria-label="记忆衰减"
                />
              </div>
              <p className={styles.qualityHint}>
                权重实时作用于搜索；衰减开关持久化到记忆衰减配置
              </p>
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
              <p className={styles.qualityHint}>由后台任务自动维护，无需人工配置</p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}

export default MemoryPage
