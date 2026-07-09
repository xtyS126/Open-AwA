/**
 * 收件箱 WebSocket 实时通知流。
 *
 * 连接后端 inbox 实时推送通道（复用 /api/chat/ws/{session_id} 端点），
 * 后端 add_notification 通过 ws_manager.broadcast_to_user 推送的消息会被本模块接收，
 * 自动写入 inboxStore 并通知所有订阅者（用于 toast 提醒、定时任务列表自动刷新等）。
 *
 * 设计要点：
 *   - 单例：全局仅一个 WS 连接，多个页面共享
 *   - 引用计数：connectInboxStream/disconnectInboxStream 配对调用，最后一个断开才真正关闭
 *   - 自动重连：指数退避（base * 2^attempts + 抖动），最多 5 次，封顶 30s
 *   - 鉴权：Sec-WebSocket-Protocol 子协议 `bearer.{token}`，token 从 getCachedApiKey 读取
 *   - 资源清理：disconnect 时主动 close 并清理重连定时器
 *
 * 安全说明（对应 SEC-16）：
 *   token 不通过 URL query 传递，避免泄露到日志/Referer/浏览器历史。
 *   通过 Sec-WebSocket-Protocol 子协议传递，后端 chat.py 解析子协议并校验。
 */
import { API_BASE_URL, getCachedApiKey } from '@/shared/api/client'
import { appLogger } from '@/shared/utils/logger'
import { useInboxStore, type InboxMessage } from './store/inboxStore'

/** 消息回调类型 */
export type InboxMessageHandler = (message: InboxMessage) => void

/** 重连参数 */
const MAX_RECONNECT_ATTEMPTS = 5
const MAX_RECONNECT_DELAY_MS = 30000
const BASE_RECONNECT_DELAY_MS = 1000

/** WebSocket session_id 固定为 inbox，后端不强制校验 */
const INBOX_SESSION_ID = 'inbox'

/** 单例状态 */
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0
let manualClose = false
/** 引用计数：多个页面调用 connect 时累加，最后一个 disconnect 才真正关闭 */
let connectCount = 0

/** 订阅者集合：收到消息时通知所有订阅者 */
const subscribers = new Set<InboxMessageHandler>()

/**
 * 推导 WebSocket URL。
 * - 绝对 URL（http/https）：使用其 host 与协议
 * - 相对路径（/api）：使用当前页面 host
 */
function deriveWebSocketUrl(): string {
  if (API_BASE_URL.startsWith('http://') || API_BASE_URL.startsWith('https://')) {
    const url = new URL(API_BASE_URL)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${url.host}${url.pathname}/chat/ws/${INBOX_SESSION_ID}`
  }
  // 相对路径：使用当前页面 host（web 模式）
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}${API_BASE_URL}/chat/ws/${INBOX_SESSION_ID}`
}

/** 计算指数退避重连延迟（含随机抖动，避免多个客户端同步重连） */
function getReconnectDelay(): number {
  const exponential = BASE_RECONNECT_DELAY_MS * Math.pow(2, reconnectAttempts)
  const jitter = Math.random() * 500
  return Math.min(exponential + jitter, MAX_RECONNECT_DELAY_MS)
}

/** 清理重连定时器 */
function clearReconnectTimer(): void {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

/** 校验并解析消息对象，无效返回 null */
function parseMessage(raw: string): InboxMessage | null {
  try {
    const obj = JSON.parse(raw) as Record<string, unknown>
    if (
      typeof obj.id !== 'string' ||
      typeof obj.title !== 'string' ||
      typeof obj.content !== 'string'
    ) {
      return null
    }
    const category = obj.category as InboxMessage['category']
    if (category !== 'notification' && category !== 'approval' && category !== 'task_result') {
      return null
    }
    return {
      id: obj.id,
      title: obj.title,
      content: obj.content,
      category,
      read: typeof obj.read === 'boolean' ? obj.read : false,
      action_url: typeof obj.action_url === 'string' ? obj.action_url : null,
      action_label: typeof obj.action_label === 'string' ? obj.action_label : null,
      created_at: typeof obj.created_at === 'string' ? obj.created_at : new Date().toISOString(),
    }
  } catch {
    return null
  }
}

/** 处理收到的 WebSocket 消息：写入 store + 通知订阅者 */
function handleMessage(raw: string): void {
  const msg = parseMessage(raw)
  if (!msg) {
    appLogger.warning({
      event: 'inbox_stream_parse_failed',
      module: 'inbox',
      message: 'inbox 流消息解析失败或字段缺失',
    })
    return
  }
  // 写入 store（addMessage 内部去重）
  useInboxStore.getState().addMessage(msg)
  // 通知所有订阅者（toast 提醒、定时任务列表刷新等）
  subscribers.forEach((handler) => {
    try {
      handler(msg)
    } catch (err) {
      appLogger.warning({
        event: 'inbox_stream_subscriber_error',
        module: 'inbox',
        message: 'inbox 流订阅者回调异常',
        extra: { error: err instanceof Error ? err.message : String(err) },
      })
    }
  })
}

/** 调度下一次重连 */
function scheduleReconnect(): void {
  if (manualClose) return
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    appLogger.warning({
      event: 'inbox_stream_max_reconnect',
      module: 'inbox',
      message: `inbox 流达到最大重连次数 ${MAX_RECONNECT_ATTEMPTS}，停止重连`,
    })
    return
  }
  clearReconnectTimer()
  const delay = getReconnectDelay()
  reconnectAttempts++
  appLogger.info({
    event: 'inbox_stream_reconnect_scheduled',
    module: 'inbox',
    message: `inbox 流将在 ${Math.round(delay)}ms 后重连（第 ${reconnectAttempts} 次）`,
  })
  reconnectTimer = setTimeout(() => {
    connectInternal()
  }, delay)
}

/** 内部连接实现 */
function connectInternal(): void {
  if (typeof window === 'undefined') return
  if (ws !== null) return

  const token = getCachedApiKey()
  if (!token) {
    appLogger.warning({
      event: 'inbox_stream_no_token',
      module: 'inbox',
      message: 'inbox 流连接缺少访问令牌，跳过连接',
    })
    return
  }

  manualClose = false
  const url = deriveWebSocketUrl()

  try {
    // 鉴权：通过 Sec-WebSocket-Protocol 子协议传递 token，避免 URL 暴露
    const socket = new WebSocket(url, [`bearer.${token}`])
    ws = socket

    socket.onopen = () => {
      reconnectAttempts = 0
      appLogger.info({
        event: 'inbox_stream_connected',
        module: 'inbox',
        message: 'inbox 流已连接',
      })
    }

    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        handleMessage(event.data)
      }
    }

    socket.onerror = () => {
      appLogger.warning({
        event: 'inbox_stream_error',
        module: 'inbox',
        message: 'inbox 流连接异常',
      })
    }

    socket.onclose = () => {
      ws = null
      if (!manualClose) {
        scheduleReconnect()
      }
    }
  } catch (err) {
    appLogger.error({
      event: 'inbox_stream_connect_failed',
      module: 'inbox',
      message: 'inbox 流连接创建失败',
      extra: { error: err instanceof Error ? err.message : String(err) },
    })
    ws = null
    scheduleReconnect()
  }
}

/** 内部断开实现 */
function disconnectInternal(): void {
  manualClose = true
  clearReconnectTimer()
  reconnectAttempts = 0
  if (ws !== null) {
    try {
      ws.close()
    } catch {
      // 忽略关闭异常（连接已断开等情况）
    }
    ws = null
  }
}

/**
 * 连接 inbox 实时流（引用计数 +1）。
 * 多个页面可重复调用，最后一个 disconnectInboxStream 才真正关闭连接。
 */
export function connectInboxStream(): void {
  connectCount++
  if (connectCount === 1) {
    connectInternal()
  }
}

/**
 * 断开 inbox 实时流（引用计数 -1）。
 * 引用计数归零时真正关闭 WebSocket 连接并清理重连定时器。
 */
export function disconnectInboxStream(): void {
  connectCount = Math.max(0, connectCount - 1)
  if (connectCount === 0) {
    disconnectInternal()
  }
}

/**
 * 订阅 inbox 实时消息。
 * 收到新消息时回调 handler，返回取消订阅函数。
 * 不会自动管理连接生命周期，调用方需自行 connectInboxStream/disconnectInboxStream。
 */
export function subscribeInboxMessages(handler: InboxMessageHandler): () => void {
  subscribers.add(handler)
  return () => {
    subscribers.delete(handler)
  }
}

/** 查询当前连接是否处于 OPEN 状态 */
export function isInboxStreamConnected(): boolean {
  return ws !== null && ws.readyState === WebSocket.OPEN
}
