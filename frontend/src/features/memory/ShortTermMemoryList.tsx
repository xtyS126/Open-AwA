/**
 * Spec memory-quality-and-short-term-recovery Task 17
 * 短期记忆列表组件 —— 在 MemoryPage 的"短期记忆"tab 下渲染。
 *
 * 功能：
 * - 按 session_id 分组渲染，每组可折叠展开
 * - 每条记忆显示 role（user/assistant/system 图标区分）/ content_preview / created_at
 * - 顶部搜索框，输入关键词调用 GET /api/memory/short-term?query=关键词
 * - 空状态展示"暂无短期记忆"
 * - 加载中展示 spinner
 *
 * 数据获取通过 TanStack Query 管理，搜索输入做 300ms 防抖。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { memoryAPI } from '@/shared/api/api'
import type { ShortTermMemory } from '@/shared/types/api'
import { appLogger } from '@/shared/utils/logger'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import styles from './ShortTermMemoryList.module.css'

/* ============================================================
 * 类型定义
 * ============================================================ */

/* 按会话分组的短期记忆 */
interface SessionGroup {
  sessionId: string
  memories: ShortTermMemory[]
}

/* ============================================================
 * SVG 图标组件 —— 内联保持文件自包含，尺寸统一 16x16
 * ============================================================ */

const svgBase = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

/* 用户消息图标（人形） */
const UserIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...svgBase}>
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
)

/* 助手消息图标（机器人） */
const AssistantIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...svgBase}>
    <rect x="3" y="11" width="18" height="10" rx="2" />
    <circle cx="12" cy="5" r="2" />
    <path d="M12 7v4" />
    <line x1="8" y1="16" x2="8" y2="16" />
    <line x1="16" y1="16" x2="16" y2="16" />
  </svg>
)

/* 系统消息图标（齿轮） */
const SystemIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...svgBase}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
)

/* 搜索图标 */
const SearchIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...svgBase}>
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
)

/* 折叠箭头图标 */
const ChevronIcon = ({ expanded }: { expanded: boolean }) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    {...svgBase}
    style={{
      transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)',
      transition: 'transform var(--transition-base)',
    }}
  >
    <polyline points="9 18 15 12 9 6" />
  </svg>
)

/* 加载中 spinner */
const Spinner = () => (
  <svg
    width="20"
    height="20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={styles.spinner}
  >
    <path d="M21 12a9 9 0 1 1-6.219-8.56" />
  </svg>
)

/* ============================================================
 * 工具函数
 * ============================================================ */

/* 相对时间格式化 */
function formatRelativeTime(timestamp?: string): string {
  if (!timestamp) return '未知时间'
  const then = new Date(timestamp).getTime()
  if (isNaN(then)) return '未知时间'
  const diffMs = Date.now() - then
  if (diffMs < 0) return '刚刚'
  const diffMin = Math.floor(diffMs / (1000 * 60))
  if (diffMin <= 0) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  const diffHours = Math.floor(diffMin / 60)
  if (diffHours < 24) return `${diffHours}小时前`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays === 1) return '1天前'
  if (diffDays < 7) return `${diffDays}天前`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}周前`
  return `${Math.floor(diffDays / 30)}月前`
}

/* 截断内容预览 */
function truncateContent(content: string, maxLen: number = 200): string {
  if (content.length <= maxLen) return content
  return content.slice(0, maxLen - 3) + '...'
}

/* 根据角色获取图标 */
function getRoleIcon(role: string) {
  switch (role) {
    case 'user':
      return <UserIcon />
    case 'assistant':
      return <AssistantIcon />
    case 'system':
      return <SystemIcon />
    default:
      return <SystemIcon />
  }
}

/* 根据角色获取徽章样式类名 */
function getRoleBadgeClass(role: string): string {
  switch (role) {
    case 'user':
      return styles.roleBadgeUser
    case 'assistant':
      return styles.roleBadgeAssistant
    case 'system':
      return styles.roleBadgeSystem
    default:
      return styles.roleBadgeSystem
  }
}

/* 根据角色获取展示名称 */
function getRoleDisplayName(role: string): string {
  switch (role) {
    case 'user':
      return '用户'
    case 'assistant':
      return '助手'
    case 'system':
      return '系统'
    default:
      return role
  }
}

/* 按会话 ID 分组 */
function groupBySession(memories: ShortTermMemory[]): SessionGroup[] {
  const groups = new Map<string, ShortTermMemory[]>()
  for (const mem of memories) {
    const sessionId = mem.session_id || '(无会话)'
    if (!groups.has(sessionId)) {
      groups.set(sessionId, [])
    }
    groups.get(sessionId)!.push(mem)
  }
  // 每组内按时间正序排列（旧到新）
  for (const sessionMemories of groups.values()) {
    sessionMemories.sort((a, b) => {
      const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0
      const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0
      return timeA - timeB
    })
  }
  // 组之间按最新消息时间倒序排列
  return Array.from(groups.entries())
    .map(([sessionId, sessionMemories]) => ({
      sessionId,
      memories: sessionMemories,
      latestTime: sessionMemories[sessionMemories.length - 1]?.timestamp || '',
    }))
    .sort((a, b) => {
      const timeA = a.latestTime ? new Date(a.latestTime).getTime() : 0
      const timeB = b.latestTime ? new Date(b.latestTime).getTime() : 0
      return timeB - timeA
    })
}

/* ============================================================
 * 单个会话分组组件
 * ============================================================ */

interface SessionGroupProps {
  group: SessionGroup
  defaultExpanded?: boolean
}

function SessionGroupItem({ group, defaultExpanded = true }: SessionGroupProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const latestTime = group.memories[group.memories.length - 1]?.timestamp

  return (
    <div className={styles.sessionGroup}>
      <button
        type="button"
        className={styles.sessionGroupHeader}
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
      >
        <ChevronIcon expanded={expanded} />
        <span className={styles.sessionIdText} title={group.sessionId}>
          {group.sessionId}
        </span>
        <span className={styles.sessionCountBadge}>{group.memories.length} 条</span>
        {latestTime && (
          <span className={styles.sessionLatestTime}>{formatRelativeTime(latestTime)}</span>
        )}
      </button>
      {expanded && (
        <div className={styles.messageList}>
          {group.memories.map((mem) => (
            <div key={`stm-${mem.id}`} className={styles.messageItem}>
              <div className={styles.messageHeader}>
                <span className={`${styles.roleBadge} ${getRoleBadgeClass(mem.role)}`}>
                  {getRoleIcon(mem.role)}
                  <span>{getRoleDisplayName(mem.role)}</span>
                </span>
                <span className={styles.messageTime}>{formatRelativeTime(mem.timestamp)}</span>
              </div>
              <p className={styles.messageContent}>{truncateContent(mem.content)}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ============================================================
 * 主组件
 * ============================================================ */

export interface ShortTermMemoryListProps {
  /** 初始 limit，默认 50 */
  initialLimit?: number
}

function ShortTermMemoryList({ initialLimit = 50 }: ShortTermMemoryListProps) {
  /* 本地搜索状态（带 300ms 防抖） */
  const [searchInput, setSearchInput] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(searchInput.trim())
    }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  /* 短期记忆查询 —— TanStack Query 管理 */
  const shortTermQuery = useQuery<ShortTermMemory[]>({
    queryKey: ['memory', 'short-term-list', debouncedQuery, initialLimit],
    queryFn: async () => {
      const params: { limit?: number; query?: string } = { limit: initialLimit }
      if (debouncedQuery) {
        params.query = debouncedQuery
      }
      const response = await memoryAPI.listShortTerm(params)
      return response.data
    },
    retry: false,
  })

  /* 使用 useMemo 包裹避免每次渲染都生成新数组引用，导致下游 useMemo 依赖变化 */
  const memories = useMemo(() => shortTermQuery.data ?? [], [shortTermQuery.data])
  const loading = shortTermQuery.isInitialLoading
  const error = shortTermQuery.error
    ? getErrorMessage(shortTermQuery.error, '加载短期记忆失败，请稍后重试')
    : null

  /* 失败时记录日志 */
  useEffect(() => {
    if (shortTermQuery.error) {
      const error = shortTermQuery.error
      appLogger.error({
        event: 'short_term_list_load_failed',
        module: 'memory',
        action: 'load_short_term_list',
        status: 'failure',
        message: '加载短期记忆列表失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
  }, [shortTermQuery.error])

  /* 按会话分组 */
  const sessionGroups = useMemo(() => groupBySession(memories), [memories])

  /* 刷新 */
  const handleRefresh = useCallback(() => {
    void shortTermQuery.refetch()
  }, [shortTermQuery])

  return (
    <div className={styles.container}>
      {/* 顶部：标题 + 搜索框 + 刷新 */}
      <div className={styles.header}>
        <div className={styles.headerTop}>
          <h2 className={styles.title}>对话记录（短期记忆）</h2>
          <div className={styles.headerActions}>
            <span className={styles.countBadge}>共 {memories.length} 条 / {sessionGroups.length} 个会话</span>
            <button
              type="button"
              className={styles.refreshBtn}
              onClick={handleRefresh}
              disabled={loading}
              aria-label="刷新"
            >
              <Spinner />
            </button>
          </div>
        </div>
        <p className={styles.subtitleHint}>
          短期记忆是对话原文，供 AI 恢复会话上下文使用，不参与语义检索
        </p>
        <div className={styles.searchWrap}>
          <span className={styles.searchIcon}>
            <SearchIcon />
          </span>
          <input
            type="text"
            placeholder="按关键词搜索短期记忆..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className={styles.searchInput}
          />
        </div>
      </div>

      {/* 内容区 */}
      {loading ? (
        <div className={styles.loadingState}>
          <Spinner />
          <span>加载中...</span>
        </div>
      ) : error ? (
        <div className={styles.errorState}>{error}</div>
      ) : sessionGroups.length === 0 ? (
        <div className={styles.emptyState}>
          <p>{debouncedQuery ? '未找到匹配的短期记忆' : '暂无短期记忆'}</p>
        </div>
      ) : (
        <div className={styles.sessionList}>
          {sessionGroups.map((group) => (
            <SessionGroupItem
              key={`session-${group.sessionId}`}
              group={group}
              defaultExpanded={sessionGroups.length <= 3}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default ShortTermMemoryList
