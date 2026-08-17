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
 *   - 鉴权：双轨策略，按优先级降级
 *     1. Sec-WebSocket-Protocol 子协议 `bearer.{token}`（token 从 getCachedApiKey 读取）
 *     2. Cookie access_token（同源时浏览器自动携带，后端 chat.py 从 Cookie 兜底鉴权）
 *   - 资源清理：disconnect 时主动 close 并清理重连定时器
 *
 * 安全说明（对应 SEC-16）：
 *   token 不通过 URL query 传递，避免泄露到日志/Referer/浏览器历史。
 *   优先通过 Sec-WebSocket-Protocol 子协议传递；纯 Cookie 登录场景降级为 Cookie 鉴权，
 *   Origin 校验已防 CSWSH，Cookie 路径安全可控。
 */
import { API_BASE_URL, getCachedApiKey } from '@/shared/api/client'
import { appLogger } from '@/shared/utils/logger'
import { asRecord } from '@/shared/types/api'
import { registerLogoutHandler } from '@/shared/store/authStore'
import { useInboxStore, type InboxMessage } from './store/inboxStore'

/** 消息回调类型 */
export type InboxMessageHandler = (message: InboxMessage) => void

/** 重连参数 */
const MAX_RECONNECT_ATTEMPTS = 5
const MAX_RECONNECT_DELAY_MS = 30000
const BASE_RECONNECT_DELAY_MS = 1000
/** 认证失败（后端 close code 4002：无效/过期 token）时不再自动重连，等待用户刷新页面重新登录 */
const AUTH_FAILED_CLOSE_CODES = new Set([4001, 4002])
/** 连接失败冷却窗口：心跳驱动（5 秒）在窗口内不重复发起连接，避免失败循环刷屏 */
const CONNECT_FAIL_COOLDOWN_MS = 30000

/** WebSocket session_id 固定为 inbox，后端不强制校验 */
const INBOX_SESSION_ID = 'inbox'

/** 跨标签页协调通道名称。 */
const INBOX_COORDINATION_CHANNEL = 'openawa_inbox_stream'
/** 广播通道不可用时的降级存储键。 */
const INBOX_COORDINATION_STORAGE_KEY = 'openawa_inbox_stream_event'
/** 活跃标签心跳间隔。 */
const PRESENCE_HEARTBEAT_MS = 5000
/** 无心跳标签的失效时间。 */
const PRESENCE_TTL_MS = PRESENCE_HEARTBEAT_MS * 3

type InboxStreamStatus = ReturnType<typeof useInboxStore.getState>['streamStatus']

type InboxCoordinationEvent =
  | { type: 'presence'; tabId: string; active: boolean; timestamp: number }
  | { type: 'status'; tabId: string; status: InboxStreamStatus }
  | { type: 'message'; tabId: string; raw: string }
  | { type: 'logout'; tabId: string }

interface InboxStoragePayload {
  event: InboxCoordinationEvent
  senderTabId: string
}

function generateTabId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `inbox-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/** 单例状态 */
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0
let manualClose = false
/** 上次连接失败时间戳：心跳驱动的 connectInternal 在冷却窗口内跳过，避免失败循环 */
let lastConnectFailAt = 0
/** 引用计数：多个页面调用 connect 时累加，最后一个 disconnect 才真正关闭 */
let connectCount = 0
let coordinationChannel: BroadcastChannel | null = null
let coordinationStorageHandler: ((event: StorageEvent) => void) | null = null
let presenceTimer: ReturnType<typeof setInterval> | null = null
let localTabActive = false
let leaderTabId: string | null = null
const localTabId = generateTabId()
const activeTabs = new Map<string, number>()

/** 订阅者集合：收到消息时通知所有订阅者 */
const subscribers = new Set<InboxMessageHandler>()

function isLocalLeader(): boolean {
  return localTabActive && leaderTabId === localTabId
}

function setStreamStatus(status: InboxStreamStatus, broadcast = false): void {
  useInboxStore.getState().setStreamStatus(status)
  if (broadcast && isLocalLeader()) {
    postCoordinationEvent({ type: 'status', tabId: localTabId, status })
  }
}

function postCoordinationEvent(event: InboxCoordinationEvent): void {
  if (coordinationChannel) {
    try {
      coordinationChannel.postMessage(event)
      return
    } catch (error) {
      appLogger.warning({
        event: 'inbox_stream_coordination_post_failed',
        module: 'inbox',
        message: 'inbox 跨标签广播失败，已降级到 storage',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
  }
  try {
    const payload: InboxStoragePayload = { event, senderTabId: localTabId }
    localStorage.setItem(INBOX_COORDINATION_STORAGE_KEY, JSON.stringify(payload))
    localStorage.removeItem(INBOX_COORDINATION_STORAGE_KEY)
  } catch {
    // storage 不可用时保留当前标签的连接能力。
  }
}

function stopPresenceTimer(): void {
  if (presenceTimer !== null) {
    clearInterval(presenceTimer)
    presenceTimer = null
  }
}

function refreshLeadership(): void {
  const now = Date.now()
  for (const [tabId, lastSeen] of activeTabs) {
    if (now - lastSeen > PRESENCE_TTL_MS) {
      activeTabs.delete(tabId)
    }
  }

  const nextLeader = [...activeTabs.keys()].sort()[0] ?? null
  const changed = leaderTabId !== nextLeader
  leaderTabId = nextLeader
  if (!localTabActive) {
    return
  }
  if (isLocalLeader()) {
    connectInternal()
  } else if (changed) {
    disconnectInternal(false)
    setStreamStatus('connecting')
  }
}

function announcePresence(active: boolean): void {
  const timestamp = Date.now()
  if (active) {
    activeTabs.set(localTabId, timestamp)
  } else {
    activeTabs.delete(localTabId)
  }
  postCoordinationEvent({ type: 'presence', tabId: localTabId, active, timestamp })
  refreshLeadership()
}

function activateLocalTab(): void {
  localTabActive = true
  announcePresence(true)
  if (presenceTimer === null) {
    presenceTimer = setInterval(() => announcePresence(true), PRESENCE_HEARTBEAT_MS)
  }
}

function deactivateLocalTab(): void {
  localTabActive = false
  stopPresenceTimer()
  announcePresence(false)
  disconnectInternal()
}

function handleCoordinationEvent(event: InboxCoordinationEvent): void {
  if (event.tabId === localTabId) {
    return
  }
  if (event.type === 'presence') {
    if (event.active) {
      activeTabs.set(event.tabId, event.timestamp)
    } else {
      activeTabs.delete(event.tabId)
    }
    refreshLeadership()
    return
  }
  if (event.type === 'status') {
    if (!isLocalLeader()) {
      setStreamStatus(event.status)
    }
    return
  }
  if (event.type === 'message') {
    handleMessage(event.raw)
    return
  }
  resetInboxStream(false)
}

function ensureCoordination(): void {
  if (typeof window === 'undefined' || coordinationChannel || coordinationStorageHandler) {
    return
  }
  if (typeof BroadcastChannel !== 'undefined') {
    try {
      coordinationChannel = new BroadcastChannel(INBOX_COORDINATION_CHANNEL)
      coordinationChannel.onmessage = (messageEvent: MessageEvent<InboxCoordinationEvent>) => {
        handleCoordinationEvent(messageEvent.data)
      }
      return
    } catch (error) {
      appLogger.warning({
        event: 'inbox_stream_coordination_init_failed',
        module: 'inbox',
        message: 'inbox 跨标签广播初始化失败，已降级到 storage',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
  }
  coordinationStorageHandler = (storageEvent: StorageEvent) => {
    if (storageEvent.key !== INBOX_COORDINATION_STORAGE_KEY || !storageEvent.newValue) {
      return
    }
    try {
      const payload = JSON.parse(storageEvent.newValue) as InboxStoragePayload
      if (payload.senderTabId !== localTabId) {
        handleCoordinationEvent(payload.event)
      }
    } catch {
      // 忽略无效的跨标签页数据。
    }
  }
  window.addEventListener('storage', coordinationStorageHandler)
}

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
    const obj = asRecord(JSON.parse(raw))
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
  if (manualClose || !isLocalLeader()) return
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    setStreamStatus('unavailable', true)
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

/** 检测浏览器 Cookie 中是否含 access_token（纯 Cookie 登录场景） */
function hasAccessTokenCookie(): boolean {
  if (typeof document === 'undefined') return false
  return document.cookie
    .split(';')
    .some((c) => c.trim().startsWith('access_token='))
}

/** 内部连接实现 */
function connectInternal(): void {
  if (typeof window === 'undefined') return
  if (!isLocalLeader()) return
  if (ws !== null) return
  // 失败冷却闸：心跳（5 秒）会反复调用本函数，连接失败后 30 秒内不再重复发起，
  // 由 scheduleReconnect 的指数退避负责重连节奏，避免失败循环刷屏
  if (Date.now() - lastConnectFailAt < CONNECT_FAIL_COOLDOWN_MS) return

  const token = getCachedApiKey()
  const hasCookie = hasAccessTokenCookie()

  // 无 token 且无 Cookie：完全无凭据，无法鉴权，放弃连接
  if (!token && !hasCookie) {
    setStreamStatus('unavailable', true)
    appLogger.warning({
      event: 'inbox_stream_no_credential',
      module: 'inbox',
      message: 'inbox 流连接缺少访问令牌与 Cookie，跳过连接',
    })
    return
  }

  manualClose = false
  setStreamStatus('connecting', true)
  const url = deriveWebSocketUrl()

  // 连接超时检测：10 秒内未建立连接则关闭并重试
  let connectTimeout: ReturnType<typeof setTimeout> | null = null

  try {
    // 鉴权策略：
    // - 有 token：通过 Sec-WebSocket-Protocol 子协议传递（避免 URL 暴露）
    // - 无 token 但有 Cookie：不传子协议，浏览器同源自动携带 Cookie，后端兜底鉴权
    const subprotocols = token ? [`bearer.${token}`] : undefined
    const socket = new WebSocket(url, subprotocols)
    ws = socket

    // 连接超时检测：10 秒内未建立连接则关闭并重试
    connectTimeout = setTimeout(() => {
      if (ws && ws.readyState !== WebSocket.OPEN) {
        appLogger.warning({
          event: 'inbox_stream_connect_timeout',
          module: 'inbox',
          message: 'inbox 流连接超时（10 秒未建立），关闭并重试',
        })
        ws.close()
        // ws = null 和 scheduleReconnect 在 onclose 中处理
      }
    }, 10000)

    socket.onopen = () => {
      if (connectTimeout !== null) {
        clearTimeout(connectTimeout)
        connectTimeout = null
      }
      reconnectAttempts = 0
      setStreamStatus('connected', true)
      appLogger.info({
        event: 'inbox_stream_connected',
        module: 'inbox',
        message: 'inbox 流已连接',
        extra: { auth_mode: token ? 'subprotocol' : 'cookie' },
      })
    }

    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        handleMessage(event.data)
        postCoordinationEvent({ type: 'message', tabId: localTabId, raw: event.data })
      }
    }

    socket.onerror = () => {
      lastConnectFailAt = Date.now()
      // 清理 ws 引用，允许后续重连（连接建立前失败时 onclose 可能不触发）
      ws = null
      appLogger.warning({
        event: 'inbox_stream_error',
        module: 'inbox',
        message: 'inbox 流连接异常',
      })
      // 触发重连流程（连接建立前失败时 onclose 可能不会触发）
      scheduleReconnect()
    }

    socket.onclose = (event) => {
      if (connectTimeout !== null) {
        clearTimeout(connectTimeout)
        connectTimeout = null
      }
      ws = null
      lastConnectFailAt = Date.now()
      if (manualClose) return
      // 认证失败（无效/过期 token）：停止自动重连，避免无限重试噪音；
      // 用户刷新页面重新登录后自然恢复
      if (AUTH_FAILED_CLOSE_CODES.has(event.code)) {
        reconnectAttempts = MAX_RECONNECT_ATTEMPTS
        setStreamStatus('unavailable', true)
        appLogger.warning({
          event: 'inbox_stream_auth_failed',
          module: 'inbox',
          message: `inbox 流认证失败（close code ${event.code}），停止自动重连，请刷新页面重新登录`,
        })
        return
      }
      scheduleReconnect()
    }
  } catch (err) {
    if (connectTimeout !== null) {
      clearTimeout(connectTimeout)
      connectTimeout = null
    }
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
function disconnectInternal(updateStatus = true): void {
  manualClose = true
  if (updateStatus) {
    setStreamStatus('disconnected')
  }
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
    ensureCoordination()
    activateLocalTab()
  }
}

/**
 * 断开 inbox 实时流（引用计数 -1）。
 * 引用计数归零时真正关闭 WebSocket 连接并清理重连定时器。
 */
export function disconnectInboxStream(): void {
  connectCount = Math.max(0, connectCount - 1)
  if (connectCount === 0) {
    deactivateLocalTab()
  }
}

/** 认证切换时强制关闭连接并清空订阅，避免旧账号事件进入新账号界面。 */
function resetInboxStream(broadcast: boolean): void {
  connectCount = 0
  subscribers.clear()
  localTabActive = false
  stopPresenceTimer()
  activeTabs.clear()
  leaderTabId = null
  disconnectInternal()
  if (broadcast) {
    postCoordinationEvent({ type: 'logout', tabId: localTabId })
  }
}

export function resetInboxStreamForLogout(): void {
  ensureCoordination()
  resetInboxStream(true)
}

// 登出清理注册：authStore 不再静态导入本模块（避免首屏加载 inbox WebSocket 模块链），
// 改由本模块加载时注册登出重置逻辑。仅当本模块已被加载（用户访问过 inbox/定时任务页）时生效。
registerLogoutHandler(() => resetInboxStreamForLogout())

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
