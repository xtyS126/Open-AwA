/**
 * 微信 WebSocket 实时消息推送 Hook
 *
 * 通过 WebSocket 订阅微信新消息事件，自动重连和清理。
 * 组件卸载时关闭连接，避免内存泄漏。
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import type { WeixinWsEvent } from '../api/api'
import { API_BASE_URL, getCachedApiKey } from '@/shared/api/client'

/**
 * 根据 API_BASE_URL 推导 WebSocket URL（不含 token，token 通过子协议传递）
 * - 相对路径（/api）：使用当前页面 host
 * - 绝对 URL：使用该 URL 的 host 与协议
 */
function deriveWebSocketUrl(): string {
  // 判断 API_BASE_URL 是否为绝对 URL
  if (API_BASE_URL.startsWith('http://') || API_BASE_URL.startsWith('https://')) {
    const url = new URL(API_BASE_URL)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${url.host}${url.pathname}/weixin/ws`
  }
  // 相对路径：使用当前页面 host（web 模式）
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}${API_BASE_URL}/weixin/ws`
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
 * 鉴权方式（SEC-16 修复）：
 *   - token 不再作为 URL query 参数传递（会泄露到日志/Referer/浏览器历史）
 *   - 改为通过 Sec-WebSocket-Protocol 子协议头传递，避免出现在 URL 中
 *   - token 从内存中的 API Key 缓存（getCachedApiKey）读取，sessionStorage 优先于 localStorage
 *
 * TODO（长期方案）：Sec-WebSocket-Protocol 仍可能被中间代理记录，应改为一次性 ticket 模式：
 *   1. 前端先调用 POST /api/weixin/ws-ticket 换取一次性短时 ticket
 *   2. WebSocket 连接时仅传 ticket，后端校验后销毁
 *   3. 后端 weixin.py 需同步适配子协议或 ticket 端点
 *
 * 自动重连：连接断开时按 reconnectInterval 间隔重试。
 * 资源清理：组件卸载时主动关闭连接，避免内存泄漏。
 *
 * 使用示例:
 *   const { connected } = useWeixinWebSocket({
 *     enabled: isAutoReplyRunning,
 *     onMessage: (event) => toast(`新消息: ${event.text}`),
 *   });
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

  // 使用 ref 打破 connect 与自身的循环引用，避免函数先使用后声明
  const connectRef = useRef<() => void>(() => {})

  const connect = useCallback(() => {
    if (typeof window === 'undefined') return
    // SEC-16: 从内存中的 API Key 缓存读取 token，避免 URL 暴露
    // 优先级：内存变量 > sessionStorage > localStorage（由 client.ts 管理）
    const token = getCachedApiKey() || ''
    if (!token) {
      setError('未找到访问令牌')
      return
    }

    manualCloseRef.current = false
    const url = deriveWebSocketUrl()

    try {
      // SEC-16: token 通过 Sec-WebSocket-Protocol 子协议传递，不出现在 URL 中
      // 协议格式：'bearer.<token>'，后端 weixin.py 需解析子协议并校验
      // 注意：浏览器 WebSocket API 会将 protocols 数组拼接为 Sec-WebSocket-Protocol 头
      // TODO: 后端 weixin.py 需同步适配 Sec-WebSocket-Protocol 解析逻辑
      const ws = new WebSocket(url, [`bearer.${token}`])
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
            connectRef.current()
          }, reconnectInterval)
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'WebSocket 连接失败')
    }
  }, [clearReconnectTimer, reconnectInterval])

  // 保持 connectRef 指向最新的 connect 函数，供 setTimeout 内部调用
  // 必须在 useEffect 中更新 ref，避免渲染期间修改 ref
  useEffect(() => {
    connectRef.current = connect
  }, [connect])

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
