/**
 * DiscussionStream SSE 订阅组件。
 *
 * 通过 EventSource 订阅后端 SSE 端点 `/api/discussions/{id}/stream`，
 * 实时展示讨论发言（按时间顺序，显示角色图标、内容、时间戳）。
 *
 * [SECURITY] EventSource API 不支持自定义 Header，鉴权由后端通过 Cookie 完成，
 * 前端不通过 URL query 传 token，遵守项目安全约束。
 *
 * 推送事件类型：
 *   - discussion_message：角色发言片段
 *   - vote_cast：投票完成
 *   - status_changed：状态转换
 *   - heartbeat：心跳保活（前端忽略）
 *   - discussion_error：错误事件
 *
 * 自动重连机制：连接断开后使用指数退避重连（1s, 2s, 4s, 8s, 16s, max 30s）。
 *
 * [MEMORY-SAFE] 组件卸载时调用 eventSource.close() 释放资源，
 * 同时清除重连定时器，避免内存泄漏。
 */
import React, { useEffect, useRef, useState, useMemo } from 'react'
import { AlertTriangle, UserCircle } from 'lucide-react'
import { useI18nStore } from '@/i18n'
import { API_BASE_URL } from '@/shared/api/client'
import { appLogger } from '@/shared/utils/logger'
import type {
  DiscussionRole,
  VoteDecision,
} from '@/shared/api/discussionsApi'
import styles from './DiscussionStream.module.css'

interface DiscussionStreamProps {
  /** 讨论任务 ID */
  discussionId: string
  /** 是否激活（仅在选中任务且未完成时订阅，避免不必要的连接） */
  active: boolean
  /** 后端推送消息后回调（用于父组件刷新详情） */
  onEvent?: (eventType: string, data: StreamEventData) => void
}

/** discussion_message 事件数据 */
interface DiscussionMessageData {
  role: DiscussionRole
  content: string
  round: number
}

/** vote_cast 事件数据 */
interface VoteCastData {
  role: DiscussionRole
  vote: VoteDecision
  reason: string
  round: number
}

/** status_changed 事件数据 */
interface StatusChangedData {
  from: string
  to: string
  round: number
}

/** heartbeat 事件数据 */
interface HeartbeatData {
  ts: number
}

/** discussion_error 事件数据 */
interface DiscussionErrorData {
  error: string
}

/** 联合事件数据类型 */
export type StreamEventData =
  | DiscussionMessageData
  | VoteCastData
  | StatusChangedData
  | HeartbeatData
  | DiscussionErrorData

type ConnectionStatus =
  | 'connecting'
  | 'connected'
  | 'disconnected'
  | 'reconnecting'

/** 流中显示的事件条目 */
interface StreamEntry {
  id: string
  type: 'message' | 'vote' | 'status' | 'error'
  role?: DiscussionRole
  content?: string
  vote?: VoteDecision
  reason?: string
  from?: string
  to?: string
  round?: number
  timestamp: number
}

/** 指数退避重连序列（秒），最大 30s */
const BACKOFF_SECONDS = [1, 2, 4, 8, 16, 30]
const MAX_BACKOFF_INDEX = BACKOFF_SECONDS.length - 1
const MAX_RECONNECT_ATTEMPTS = 5

/** 角色图标颜色映射 */
const ROLE_COLOR_MAP: Record<DiscussionRole, string> = {
  critic: styles.roleCritic,
  validator: styles.roleValidator,
  approver: styles.roleApprover,
}

/**
 * 解析 SSE 事件 data 字段为对象。
 *
 * 解析失败时返回 null，由调用方决定如何处理（记录日志、忽略等）。
 */
function parseEventData<T = StreamEventData>(raw: string): T | null {
  try {
    return JSON.parse(raw) as T
  } catch {
    appLogger.warning({
      event: 'discussion_stream_parse_failed',
      module: 'discussions',
      action: 'sse_parse',
      status: 'warning',
      message: 'SSE 事件数据 JSON 解析失败',
      extra: { raw_preview: raw.slice(0, 100) },
    })
    return null
  }
}

const DiscussionStream: React.FC<DiscussionStreamProps> = ({
  discussionId,
  active,
  onEvent,
}) => {
  const t = useI18nStore((s) => s.t)
  const [entries, setEntries] = useState<StreamEntry[]>([])
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')

  // EventSource 引用，使用 ref 保持稳定，避免重渲染导致连接重建
  const eventSourceRef = useRef<EventSource | null>(null)
  // 重连定时器引用，卸载时清除
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 当前重连次数（用于指数退避）
  const retryCountRef = useRef<number>(0)
  // 唯一 ID 生成器（用于 entry key）
  const entryIdCounterRef = useRef<number>(0)
  // 是否已卸载的标志，避免异步回调在卸载后更新 state
  const isUnmountedRef = useRef<boolean>(false)
  // connect 函数引用，用于在重连定时器中调用最新版本，
  // 避免闭包捕获旧 connect 导致 react-hooks/immutability 警告
  const connectRef = useRef<() => void>(() => {})

  /** 清理当前 EventSource 与重连定时器 */
  const cleanup = React.useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (eventSourceRef.current !== null) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }, [])

  /** 建立 SSE 连接 */
  const connect = React.useCallback(() => {
    if (isUnmountedRef.current) return
    if (!active || !discussionId) return

    // 先清理旧连接
    if (eventSourceRef.current !== null) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }

    const url = `${API_BASE_URL}/discussions/${discussionId}/stream`
    const initialStatus: ConnectionStatus =
      retryCountRef.current === 0 ? 'connecting' : 'reconnecting'
    setStatus(initialStatus)

    appLogger.info({
      event: 'discussion_stream_connect',
      module: 'discussions',
      action: 'sse_connect',
      status: 'start',
      message: '建立 SSE 连接',
      extra: { discussion_id: discussionId, retry_count: retryCountRef.current },
    })

    const source = new EventSource(url, { withCredentials: true })
    eventSourceRef.current = source

    source.onopen = () => {
      if (isUnmountedRef.current) return
      setStatus('connected')
      // 连接成功后重置重试次数
      retryCountRef.current = 0
      appLogger.info({
        event: 'discussion_stream_open',
        module: 'discussions',
        action: 'sse_open',
        status: 'success',
        message: 'SSE 连接已建立',
        extra: { discussion_id: discussionId },
      })
    }

    source.onerror = () => {
      if (isUnmountedRef.current) return
      appLogger.warning({
        event: 'discussion_stream_error',
        module: 'discussions',
        action: 'sse_error',
        status: 'warning',
        message: 'SSE 连接错误，准备重连',
        extra: {
          discussion_id: discussionId,
          retry_count: retryCountRef.current,
        },
      })

      // 关闭当前连接
      source.close()
      eventSourceRef.current = null

      // Cookie 认证失效与网络不可达都无法由 EventSource 暴露状态码。
      // 有界重试后明确降级为页面内错误，而非无限静默重连。
      if (retryCountRef.current >= MAX_RECONNECT_ATTEMPTS) {
        setStatus('disconnected')
        setEntries((prev) => [
          ...prev,
          {
            id: `error-${++entryIdCounterRef.current}`,
            type: 'error',
            content: '实时讨论连接不可用，请重新登录后刷新页面。',
            timestamp: Date.now(),
          },
        ])
        return
      }

      // 指数退避重连
      const backoffIndex = Math.min(retryCountRef.current, MAX_BACKOFF_INDEX)
      const delayMs = BACKOFF_SECONDS[backoffIndex] * 1000
      retryCountRef.current += 1
      setStatus('reconnecting')

      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current)
      }
      reconnectTimerRef.current = setTimeout(() => {
        if (!isUnmountedRef.current && active) {
          // 通过 ref 调用最新的 connect 函数，避免闭包捕获旧版本
          connectRef.current()
        }
      }, delayMs)
    }

    // discussion_message 事件
    source.addEventListener('discussion_message', (event) => {
      if (isUnmountedRef.current) return
      const data = parseEventData<DiscussionMessageData>(event.data)
      if (!data) return
      const entry: StreamEntry = {
        id: `msg-${++entryIdCounterRef.current}`,
        type: 'message',
        role: data.role,
        content: data.content,
        round: data.round,
        timestamp: Date.now(),
      }
      setEntries((prev) => [...prev, entry])
      onEvent?.('discussion_message', data)
    })

    // vote_cast 事件
    source.addEventListener('vote_cast', (event) => {
      if (isUnmountedRef.current) return
      const data = parseEventData<VoteCastData>(event.data)
      if (!data) return
      const entry: StreamEntry = {
        id: `vote-${++entryIdCounterRef.current}`,
        type: 'vote',
        role: data.role,
        vote: data.vote,
        reason: data.reason,
        round: data.round,
        timestamp: Date.now(),
      }
      setEntries((prev) => [...prev, entry])
      onEvent?.('vote_cast', data)
    })

    // status_changed 事件
    source.addEventListener('status_changed', (event) => {
      if (isUnmountedRef.current) return
      const data = parseEventData<StatusChangedData>(event.data)
      if (!data) return
      const entry: StreamEntry = {
        id: `status-${++entryIdCounterRef.current}`,
        type: 'status',
        from: data.from,
        to: data.to,
        round: data.round,
        timestamp: Date.now(),
      }
      setEntries((prev) => [...prev, entry])
      onEvent?.('status_changed', data)
    })

    // discussion_error 事件
    source.addEventListener('discussion_error', (event) => {
      if (isUnmountedRef.current) return
      const data = parseEventData<DiscussionErrorData>(event.data)
      if (!data) return
      const entry: StreamEntry = {
        id: `error-${++entryIdCounterRef.current}`,
        type: 'error',
        content: data.error,
        timestamp: Date.now(),
      }
      setEntries((prev) => [...prev, entry])
      onEvent?.('discussion_error', data)
    })

    // heartbeat 事件：忽略，仅用于保活
    source.addEventListener('heartbeat', () => {
      // 心跳事件无需处理，浏览器自动维持连接
    })
  }, [active, discussionId, onEvent])

  // 同步 connect ref，确保重连定时器中调用的是最新版本
  // 必须在 useEffect 中赋值，避免在渲染过程中修改 ref（react-hooks/refs 规则）
  useEffect(() => {
    connectRef.current = connect
  }, [connect])

  useEffect(() => {
    isUnmountedRef.current = false
    if (active && discussionId) {
      // 切换任务时清空历史 entry
      setEntries([])
      retryCountRef.current = 0
      connect()
    }
    return () => {
      isUnmountedRef.current = true
      cleanup()
    }
  }, [active, discussionId, connect, cleanup])

  // 切换 active 时也清理
  useEffect(() => {
    if (!active) {
      cleanup()
      setStatus('disconnected')
    }
  }, [active, cleanup])

  // 状态指示器文案
  const statusText = useMemo(() => {
    switch (status) {
      case 'connecting':
        return t('discussions.stream.connecting')
      case 'connected':
        return t('discussions.stream.connected')
      case 'disconnected':
        return t('discussions.stream.disconnected')
      case 'reconnecting':
        return t('discussions.stream.reconnecting')
      default:
        return ''
    }
  }, [status, t])

  return (
    <div className={styles.container} aria-live="polite">
      <div className={styles.header}>
        <span
          className={`${styles.statusIndicator} ${styles[`status_${status}`]}`}
          aria-hidden="true"
        />
        <span className={styles.statusText}>{statusText}</span>
      </div>

      <div className={styles.entries} role="log">
        {entries.length === 0 ? (
          <div className={styles.empty}>{t('discussions.stream.connecting')}</div>
        ) : (
          entries.map((entry) => (
            <StreamEntryView key={entry.id} entry={entry} t={t} />
          ))
        )}
      </div>
    </div>
  )
}

/** 渲染单条流式条目 */
const StreamEntryView: React.FC<{
  entry: StreamEntry
  t: (key: string, params?: Record<string, string>) => string
}> = React.memo(function StreamEntryView({ entry, t }) {
  const time = new Date(entry.timestamp).toLocaleTimeString()

  if (entry.type === 'message') {
    const role = entry.role as DiscussionRole
    const roleClass = ROLE_COLOR_MAP[role] ?? ''
    return (
      <div className={`${styles.entry} ${styles.message} ${roleClass}`}>
        <UserCircle size={14} className={styles.roleIcon} aria-hidden="true" />
        <span className={styles.roleLabel}>{t(`discussions.role.${role}`)}</span>
        <span className={styles.time}>{time}</span>
        <p className={styles.content}>{entry.content}</p>
      </div>
    )
  }

  if (entry.type === 'vote') {
    const role = entry.role as DiscussionRole
    const vote = entry.vote as VoteDecision
    return (
      <div className={`${styles.entry} ${styles.vote}`}>
        <UserCircle size={14} className={styles.roleIcon} aria-hidden="true" />
        <span className={styles.roleLabel}>{t(`discussions.role.${role}`)}</span>
        <span className={`${styles.voteDecision} ${styles[`vote_${vote}`]}`}>
          {t(`discussions.vote.${vote}`)}
        </span>
        <span className={styles.time}>{time}</span>
        {entry.reason && <p className={styles.content}>{entry.reason}</p>}
      </div>
    )
  }

  if (entry.type === 'status') {
    return (
      <div className={`${styles.entry} ${styles.statusChange}`}>
        <AlertTriangle size={14} className={styles.roleIcon} aria-hidden="true" />
        <span className={styles.content}>
          {entry.from} -&gt; {entry.to}
          {entry.round !== undefined && ` (${t('discussions.round.label', { n: String(entry.round) })})`}
        </span>
        <span className={styles.time}>{time}</span>
      </div>
    )
  }

  // error
  return (
    <div className={`${styles.entry} ${styles.errorEntry}`}>
      <AlertTriangle size={14} className={styles.roleIcon} aria-hidden="true" />
      <span className={styles.content}>{entry.content}</span>
      <span className={styles.time}>{time}</span>
    </div>
  )
})

export default DiscussionStream
