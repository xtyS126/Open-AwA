/**
 * 权限请求实时推送 Hook。
 * 连接后端 SSE 端点，监听权限请求事件，提供 approve/deny 操作。
 * 当有新的权限请求时自动更新 pendingRequests 列表，
 * 用户回复后自动从列表中移除已处理的请求。
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { securityAPI } from '@/shared/api/securityApi'
import { getCachedApiKey, API_BASE_URL } from '@/shared/api/client'
import type { PermissionRequest } from '@/shared/api/securityApi'
import { useAuthStore } from '@/shared/store/authStore'
import { appLogger } from '@/shared/utils/logger'

/** SSE 事件中权限请求的数据结构 */
interface PermissionRequestEvent extends PermissionRequest {
  created_at?: string
}

/** SSE 事件中权限回复的数据结构 */
interface PermissionReplyEvent {
  type: 'permission_reply'
  request_id: string
  reply: 'once' | 'always' | 'reject'
}

/** Hook 返回值 */
interface UsePermissionRequestReturn {
  /** 当前待处理的权限请求列表 */
  pendingRequests: PermissionRequest[]
  /** 批准权限请求（允许一次） */
  approve: (requestId: string) => Promise<void>
  /** 始终允许权限请求 */
  approveAlways: (requestId: string, rules?: string) => Promise<void>
  /** 拒绝权限请求 */
  deny: (requestId: string, reason?: string) => Promise<void>
  /** SSE 连接状态 */
  connected: boolean
}

/** 重连延迟基数（毫秒） */
const RECONNECT_BASE_DELAY = 1000
/** 最大重连延迟（毫秒） */
const MAX_RECONNECT_DELAY = 30000
/** 最大重连次数：超过后停止重连，避免无限重连占用网络资源 */
const MAX_RECONNECT_ATTEMPTS = 5

/**
 * 检测当前 document.cookie 中是否包含 access_token 键。
 * 用于判断是否可使用 Cookie 认证建立 SSE 连接，避免将 API Key 暴露在 URL 中。
 */
function hasCookieCredential(): boolean {
  return document.cookie.split(';').some((c) => c.trim().startsWith('access_token='))
}

/**
 * 检测当前是否运行在移动端（Capacitor WebView）。
 *
 * 移动端通过 window.OpenAwABackend 注入的 JS 接口标识（setupMobileApi.ts 注册）。
 * 移动端没有 ACP 子进程，不会产生权限请求事件，因此跳过 SSE 连接避免无意义重连。
 */
function isMobilePlatform(): boolean {
  return typeof window !== 'undefined' && !!(window as Window & { OpenAwABackend?: unknown }).OpenAwABackend
}

/**
 * 权限请求实时推送 Hook。
 * 当 sessionId 有效时自动建立 SSE 连接，监听后端推送的权限请求。
 * 组件卸载或 sessionId 变化时自动断开并重连。
 */
export function usePermissionRequest(sessionId: string | undefined): UsePermissionRequestReturn {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
  const [pendingRequests, setPendingRequests] = useState<PermissionRequest[]>([])
  const [connected, setConnected] = useState(false)
  const reconnectAttemptRef = useRef(0)
  const eventSourceRef = useRef<EventSource | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 处理权限请求事件
  const handlePermissionRequest = useCallback((request: PermissionRequestEvent) => {
    setPendingRequests((prev) => {
      // 避免重复添加
      if (prev.some((r) => r.id === request.id)) {
        return prev
      }
      return [...prev, request]
    })
  }, [])

  // 处理权限回复事件（其他客户端可能已回复）
  const handlePermissionReply = useCallback((reply: PermissionReplyEvent) => {
    setPendingRequests((prev) => prev.filter((r) => r.id !== reply.request_id))
  }, [])

  // 建立 SSE 连接
  useEffect(() => {
    // 路由重定向前 ChatPage 可能短暂挂载；必须等待认证确认后再建立受保护 SSE。
    if (!isAuthenticated || !sessionId || sessionId === 'default') {
      setConnected(false)
      return
    }

    // 移动端无 ACP 子进程，不会产生权限请求事件，跳过 SSE 连接避免无意义重连
    if (isMobilePlatform()) {
      appLogger.info({
        event: 'permission_sse_skipped_on_mobile',
        module: 'usePermissionRequest',
        message: '移动端无 ACP 子进程，跳过权限请求 SSE 连接',
      })
      setConnected(false)
      return
    }

    const apiKey = getCachedApiKey()
    const hasCookie = hasCookieCredential()

    // 无 Cookie 且无 API Key 时无法建立 SSE 连接
    if (!hasCookie && !apiKey) {
      appLogger.warning({
        event: 'permission_sse_no_api_key',
        module: 'usePermissionRequest',
        message: 'API Key 未配置，无法建立权限请求 SSE 连接',
      })
      return
    }

    let cancelled = false
    let connectTimer: ReturnType<typeof setTimeout> | null = null
    // AbortController 用于 cleanup 时中断 ticket 请求，避免组件卸载后 EventSource
    // 仍被创建导致 net::ERR_ABORTED 噪音日志（P1 修复）
    let ticketAbortController: AbortController | null = null

    const connect = async () => {
      if (cancelled) return

      const baseUrl = `${API_BASE_URL}/security/permissions/stream`
      let eventSource: EventSource

      if (hasCookie) {
        // 优先使用 Cookie 认证，URL 不携带任何凭据
        eventSource = new EventSource(baseUrl, { withCredentials: true })
      } else if (apiKey) {
        // 无 Cookie 时通过一次性 ticket 建立 SSE 连接（SEC-16 修复）
        // ticket 一次性使用、60 秒过期，避免 API Key 泄露到 access log / Referer / 浏览器历史
        ticketAbortController = new AbortController()
        try {
          const ticketResp = await securityAPI.requestSseTicket(ticketAbortController.signal)
          if (cancelled) return
          const ticket = ticketResp.data.ticket
          eventSource = new EventSource(`${baseUrl}?ticket=${encodeURIComponent(ticket)}`)
        } catch (err) {
          // AbortError 是 cleanup 触发的预期行为，不记录警告
          if (cancelled || (err instanceof DOMException && err.name === 'AbortError')) {
            return
          }
          appLogger.warning({
            event: 'permission_sse_ticket_fetch_failed',
            module: 'usePermissionRequest',
            message: '获取 SSE ticket 失败，降级使用 api_key query 参数',
            extra: { error: err instanceof Error ? err.message : String(err) },
          })
          // 降级：仍使用 api_key（向后兼容，但记录警告）
          const url = `${baseUrl}?api_key=${encodeURIComponent(apiKey)}`
          eventSource = new EventSource(url)
        } finally {
          ticketAbortController = null
        }
      } else {
        // 已在 useEffect 入口拦截，理论上不会到达
        return
      }

      if (cancelled) {
        eventSource.close()
        return
      }

      eventSourceRef.current = eventSource

      eventSource.onopen = () => {
        if (cancelled) return
        setConnected(true)
        reconnectAttemptRef.current = 0
        appLogger.info({
          event: 'permission_sse_connected',
          module: 'usePermissionRequest',
          message: '权限请求 SSE 连接已建立',
        })
      }

      eventSource.addEventListener('permission_request', (event: MessageEvent) => {
        if (cancelled) return
        try {
          const data = JSON.parse(event.data) as PermissionRequestEvent
          handlePermissionRequest(data)
        } catch (err) {
          appLogger.warning({
            event: 'permission_sse_parse_error',
            module: 'usePermissionRequest',
            message: '解析权限请求事件失败',
            extra: { error: err instanceof Error ? err.message : String(err) },
          })
        }
      })

      eventSource.onerror = () => {
        if (cancelled) return
        setConnected(false)
        eventSource.close()
        eventSourceRef.current = null

        // 最大重连次数限制：超过后停止重连，避免频繁重连占用网络资源
        if (reconnectAttemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
          appLogger.warning({
            event: 'permission_sse_max_reconnect_reached',
            module: 'usePermissionRequest',
            message: `SSE 连接断开已达最大重连次数 ${MAX_RECONNECT_ATTEMPTS}，停止重连`,
          })
          return
        }

        // 指数退避重连
        const delay = Math.min(
          RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttemptRef.current),
          MAX_RECONNECT_DELAY
        )
        reconnectAttemptRef.current += 1

        appLogger.info({
          event: 'permission_sse_reconnecting',
          module: 'usePermissionRequest',
          message: `SSE 连接断开，${delay}ms 后重连（第 ${reconnectAttemptRef.current} 次）`,
        })

        if (reconnectTimerRef.current !== null) {
          clearTimeout(reconnectTimerRef.current)
        }
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null
          if (!cancelled) connect()
        }, delay)
      }
    }

    // 延迟 100ms 连接，StrictMode dev 双 mount 时第一次 cleanup 取消定时器，
    // 第二次 mount 才真正建立 SSE 连接，避免重复请求 ticket。
    // 生产环境单 mount 无影响，100ms 后正常连接。
    connectTimer = setTimeout(() => {
      void connect()
    }, 100)

    return () => {
      cancelled = true
      if (connectTimer) {
        clearTimeout(connectTimer)
        connectTimer = null
      }
      // 中断正在进行的 ticket 请求，避免组件卸载后 EventSource 仍被创建
      if (ticketAbortController) {
        ticketAbortController.abort()
        ticketAbortController = null
      }
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      setConnected(false)
      setPendingRequests([])
    }
  }, [isAuthenticated, sessionId, handlePermissionRequest, handlePermissionReply])

  // 批准权限请求（允许一次）
  const approve = useCallback(async (requestId: string) => {
    try {
      await securityAPI.replyToPermission({
        request_id: requestId,
        reply: 'once',
      })
      setPendingRequests((prev) => prev.filter((r) => r.id !== requestId))
    } catch (err) {
      appLogger.error({
        event: 'permission_approve_failed',
        module: 'usePermissionRequest',
        message: '批准权限请求失败',
        extra: { requestId, error: err instanceof Error ? err.message : String(err) },
      })
      throw err
    }
  }, [])

  // 始终允许权限请求
  const approveAlways = useCallback(async (requestId: string, rules?: string) => {
    try {
      await securityAPI.replyToPermission({
        request_id: requestId,
        reply: 'always',
        message: rules,
      })
      setPendingRequests((prev) => prev.filter((r) => r.id !== requestId))
    } catch (err) {
      appLogger.error({
        event: 'permission_approve_always_failed',
        module: 'usePermissionRequest',
        message: '始终允许权限请求失败',
        extra: { requestId, error: err instanceof Error ? err.message : String(err) },
      })
      throw err
    }
  }, [])

  // 拒绝权限请求
  const deny = useCallback(async (requestId: string, reason?: string) => {
    try {
      await securityAPI.replyToPermission({
        request_id: requestId,
        reply: 'reject',
        message: reason,
      })
      setPendingRequests((prev) => prev.filter((r) => r.id !== requestId))
    } catch (err) {
      appLogger.error({
        event: 'permission_deny_failed',
        module: 'usePermissionRequest',
        message: '拒绝权限请求失败',
        extra: { requestId, error: err instanceof Error ? err.message : String(err) },
      })
      throw err
    }
  }, [])

  return {
    pendingRequests,
    approve,
    approveAlways,
    deny,
    connected,
  }
}
