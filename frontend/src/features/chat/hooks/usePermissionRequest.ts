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

/**
 * 权限请求实时推送 Hook。
 * 当 sessionId 有效时自动建立 SSE 连接，监听后端推送的权限请求。
 * 组件卸载或 sessionId 变化时自动断开并重连。
 */
export function usePermissionRequest(sessionId: string | undefined): UsePermissionRequestReturn {
  const [pendingRequests, setPendingRequests] = useState<PermissionRequest[]>([])
  const [connected, setConnected] = useState(false)
  const reconnectAttemptRef = useRef(0)
  const eventSourceRef = useRef<EventSource | null>(null)

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
    if (!sessionId || sessionId === 'default') {
      setConnected(false)
      return
    }

    const apiKey = getCachedApiKey()
    if (!apiKey) {
      appLogger.warning({
        event: 'permission_sse_no_api_key',
        module: 'usePermissionRequest',
        message: 'API Key 未配置，无法建立权限请求 SSE 连接',
      })
      return
    }

    let cancelled = false

    const connect = () => {
      if (cancelled) return

      // 通过 query parameter 传递 API Key（EventSource 不支持自定义 Header）
      const url = `${API_BASE_URL}/security/permissions/stream?api_key=${encodeURIComponent(apiKey)}`
      const eventSource = new EventSource(url)
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

        setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      cancelled = true
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      setConnected(false)
      setPendingRequests([])
    }
  }, [sessionId, handlePermissionRequest, handlePermissionReply])

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
