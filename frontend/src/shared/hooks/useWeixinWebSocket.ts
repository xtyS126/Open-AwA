/**
 * 微信 WebSocket 实时消息推送 Hook
 *
 * 通过 WebSocket 订阅微信新消息事件，自动重连和清理。
 * 组件卸载时关闭连接，避免内存泄漏。
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import type { WeixinWsEvent } from '../api/api'
import { API_BASE_URL } from '@/shared/api/client'

/**
 * 根据 API_BASE_URL 推导 WebSocket URL
 * - 相对路径（/api）：使用当前页面 host
 * - 绝对 URL：使用该 URL 的 host 与协议
 */
function deriveWebSocketUrl(token: string): string {
  // 判断 API_BASE_URL 是否为绝对 URL
  if (API_BASE_URL.startsWith('http://') || API_BASE_URL.startsWith('https://')) {
    const url = new URL(API_BASE_URL)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${url.host}${url.pathname}/weixin/ws?token=${encodeURIComponent(token)}`
  }
  // 相对路径：使用当前页面 host（web 模式）
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}${API_BASE_URL}/weixin/ws?token=${encodeURIComponent(token)}`
}

export interface UseWeixinWebSocketOptions {
  /** 是否启用 WebSocket 连接 */
  enabled?: boolean
  /** 收到新消息事件时的回调 */
  onMessage?: (event: Extract<WeixinWsEvent, { event: 'new_message' }>) => void
  /** 重连间隔（毫秒），默认 5000ms */
  reconnectInterval?: number
}

export interface UseWeixinWebSocketResult {
  /** 当前连接状态 */
  connected: boolean
  /** 最近一次错误信息 */
  error: string | null
  /** 手动关闭连接 */
  close: () => void
  /** 手动重连 */
  reconnect: () => void
}

/**
 * 微信 WebSocket 实时消息推送 Hook。
 *
 * 鉴权方式：从 localStorage 读取 access_token，作为 query 参数传递给 WebSocket 端点。
 * 自动重连：连接断开时按 reconnectInterval 间隔重试。
 * 资源清理：组件卸载时主动关闭连接，避免内存泄漏。
 *
 * 使用示例:
 *   const { connected } = useWeixinWebSocket({
 *     enabled: isAutoReplyRunning,
 *     onMessage: (event) => toast(`新消息: ${event.text}`),
 *   })
 */
export function useWeixinWebSocket(
  options: UseWeixinWebSocketOptions = {}
): UseWeixinWebSocketResult {
  const { enabled = true, onMessage, reconnectInterval = 5000 } = options
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)
  const manualCloseRef = useRef(false)

  // 保持 onMessage 回调的最新引用，避免 effect 频繁重建连接
  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
  }, [])

  const close = useCallback(() => {
    manualCloseRef.current = true
    clearReconnectTimer()
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setConnected(false)
  }, [clearReconnectTimer])

  const connect = useCallback(() => {
    if (typeof window === 'undefined') return
    const token = localStorage.getItem('access_token') || ''
    if (!token) {
      setError('未找到访问令牌')
      return
    }

    manualCloseRef.current = false
    const url = deriveWebSocketUrl(token)

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        setError(null)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WeixinWsEvent
          if (data.event === 'new_message' && onMessageRef.current) {
            onMessageRef.current(data)
          }
        } catch {
          // 忽略无法解析的消息
        }
      }

      ws.onerror = () => {
        setError('WebSocket 连接异常')
        setConnected(false)
      }

      ws.onclose = () => {
        setConnected(false)
        wsRef.current = null
        if (!manualCloseRef.current) {
          // 自动重连
          clearReconnectTimer()
          reconnectTimerRef.current = setTimeout(() => {
            connect()
          }, reconnectInterval)
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'WebSocket 连接失败')
    }
  }, [clearReconnectTimer, reconnectInterval])

  const reconnect = useCallback(() => {
    clearReconnectTimer()
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    connect()
  }, [clearReconnectTimer, connect])

  useEffect(() => {
    if (!enabled) {
      close()
      return
    }
    connect()
    return () => {
      close()
    }
  }, [enabled, connect, close])

  return { connected, error, close, reconnect }
}
