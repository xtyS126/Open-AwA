/**
 * 跨标签页聊天状态广播 hook。
 *
 * 优先使用 BroadcastChannel 在同源的多个标签页间传播聊天流式事件；
 * 当 BroadcastChannel 不可用时（部分隐私模式或旧环境），降级到
 * localStorage storage 事件机制。
 *
 * 暴露广播方法与订阅方法：
 * - broadcastStreamStart：通知其他标签页流式开始（携带用户消息）
 * - broadcastStreamChunk：广播流式 chunk（携带当前累计的完整内容）
 * - broadcastStreamEnd：广播流式结束（携带最终内容）
 * - broadcastConversationChange：广播会话列表变更
 * - subscribe：注册事件回调，返回取消订阅函数
 *
 * 防重复机制：
 * - BroadcastChannel 天然不回传发送方，无需额外过滤
 * - storage 降级模式下，通过 tabId 过滤自发事件
 */
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { appLogger } from '@/shared/utils/logger'

/** 跨标签页广播的事件类型 */
export type ChatBroadcastEvent =
  | {
      type: 'stream_start'
      sessionId: string
      messageId: string
      userMessage: string
      timestamp: number
    }
  | {
      type: 'stream_chunk'
      sessionId: string
      messageId: string
      content: string
      reasoning?: string
      timestamp: number
    }
  | {
      type: 'stream_end'
      sessionId: string
      messageId: string
      finalContent: string
      finalReasoning?: string
      timestamp: number
    }
  | { type: 'conversation_changed'; timestamp: number }

/** BroadcastChannel 频道名称 */
const BROADCAST_CHANNEL_NAME = 'openawa_chat'

/** storage 降级模式下使用的 localStorage key */
const STORAGE_FALLBACK_KEY = 'openawa_chat_broadcast'

/** 事件监听回调类型 */
type Listener = (event: ChatBroadcastEvent) => void

/** storage 降级模式下写入 localStorage 的载荷结构 */
interface StoragePayload {
  event: ChatBroadcastEvent
  senderTabId: string
}

/**
 * 生成当前标签页唯一 ID。
 * 优先使用 crypto.randomUUID；不可用时降级到时间戳+随机数组合。
 */
function generateTabId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch {
    // 部分隐私模式下 crypto.randomUUID 可能抛错，降级处理
  }
  return `tab-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/**
 * 判断当前环境是否可用 BroadcastChannel。
 * 仅在 typeof BroadcastChannel === 'function' 时视为可用，
 * 避免某些环境提供了构造器但实例化失败的边界情况。
 */
function isBroadcastChannelAvailable(): boolean {
  return typeof BroadcastChannel !== 'undefined'
}

/**
 * 跨标签页聊天状态广播 hook。
 *
 * 在组件挂载时建立广播通道（BroadcastChannel 或 storage 降级），
 * 在组件卸载时关闭通道并移除监听。暴露的广播方法与订阅方法均通过
 * useCallback/useMemo 稳定化，可安全作为 useEffect 依赖。
 */
export function useChatBroadcast() {
  // 当前标签页唯一 ID，用于 storage 降级模式下过滤自发事件
  const tabIdRef = useRef<string>(generateTabId())
  // 订阅者集合，使用 Set 保证幂等注册与取消
  const listenersRef = useRef<Set<Listener>>(new Set())
  // BroadcastChannel 实例引用（成功创建时非空）
  const channelRef = useRef<BroadcastChannel | null>(null)

  useEffect(() => {
    const listeners = listenersRef.current
    let storageHandler: ((event: StorageEvent) => void) | null = null

    // 优先尝试 BroadcastChannel
    if (isBroadcastChannelAvailable()) {
      try {
        const channel = new BroadcastChannel(BROADCAST_CHANNEL_NAME)
        channel.onmessage = (event: MessageEvent) => {
          const data = event.data as ChatBroadcastEvent | undefined
          if (!data || typeof data !== 'object' || typeof data.type !== 'string') {
            return
          }
          // BroadcastChannel 天然不回传发送方，无需过滤
          listeners.forEach((listener) => {
            try {
              listener(data)
            } catch (err) {
              appLogger.warning({
                event: 'chat_broadcast_listener_error',
                module: 'chat_broadcast',
                message: 'broadcast listener threw',
                extra: { error: err instanceof Error ? err.message : String(err) },
              })
            }
          })
        }
        channelRef.current = channel
      } catch (err) {
        appLogger.warning({
          event: 'chat_broadcast_channel_init_failed',
          module: 'chat_broadcast',
          message: 'BroadcastChannel init failed, fallback to storage',
          extra: { error: err instanceof Error ? err.message : String(err) },
        })
        channelRef.current = null
      }
    }

    // 降级路径：仅当 BroadcastChannel 不可用或初始化失败时启用 storage 监听
    if (!channelRef.current) {
      storageHandler = (event: StorageEvent) => {
        if (event.key !== STORAGE_FALLBACK_KEY || !event.newValue) {
          return
        }
        try {
          const payload = JSON.parse(event.newValue) as StoragePayload
          if (!payload || typeof payload !== 'object') {
            return
          }
          // 过滤自发事件：storage 事件可能触发发送方
          if (payload.senderTabId === tabIdRef.current) {
            return
          }
          const broadcastEvent = payload.event
          if (
            !broadcastEvent ||
            typeof broadcastEvent !== 'object' ||
            typeof broadcastEvent.type !== 'string'
          ) {
            return
          }
          listeners.forEach((listener) => {
            try {
              listener(broadcastEvent)
            } catch (err) {
              appLogger.warning({
                event: 'chat_broadcast_listener_error',
                module: 'chat_broadcast',
                message: 'storage fallback listener threw',
                extra: { error: err instanceof Error ? err.message : String(err) },
              })
            }
          })
        } catch {
          // 解析失败静默忽略，避免脏数据影响主流程
        }
      }
      window.addEventListener('storage', storageHandler)
    }

    return () => {
      if (channelRef.current) {
        try {
          channelRef.current.close()
        } catch {
          // 关闭失败静默处理
        }
        channelRef.current = null
      }
      if (storageHandler) {
        window.removeEventListener('storage', storageHandler)
      }
    }
  }, [])

  /**
   * 内部发送函数：优先使用 BroadcastChannel，
   * 不可用或发送失败时降级到 localStorage。
   */
  const post = useCallback((event: ChatBroadcastEvent) => {
    // 优先使用 BroadcastChannel
    if (channelRef.current) {
      try {
        channelRef.current.postMessage(event)
        return
      } catch (err) {
        appLogger.warning({
          event: 'chat_broadcast_post_failed',
          module: 'chat_broadcast',
          message: 'BroadcastChannel postMessage failed, fallback to storage',
          extra: { error: err instanceof Error ? err.message : String(err) },
        })
        // 发送失败时降级到 storage
      }
    }
    // 降级路径：写入 localStorage 触发其他标签页的 storage 事件
    const payload: StoragePayload = {
      event,
      senderTabId: tabIdRef.current,
    }
    try {
      localStorage.setItem(STORAGE_FALLBACK_KEY, JSON.stringify(payload))
    } catch {
      // localStorage 不可用时静默失败，不影响主流程
    }
  }, [])

  /** 通知其他标签页流式开始（携带用户消息） */
  const broadcastStreamStart = useCallback(
    (sessionId: string, messageId: string, userMessage: string) => {
      post({
        type: 'stream_start',
        sessionId,
        messageId,
        userMessage,
        timestamp: Date.now(),
      })
    },
    [post]
  )

  /** 广播流式 chunk（携带当前累计的完整内容） */
  const broadcastStreamChunk = useCallback(
    (sessionId: string, messageId: string, content: string, reasoning?: string) => {
      post({
        type: 'stream_chunk',
        sessionId,
        messageId,
        content,
        reasoning,
        timestamp: Date.now(),
      })
    },
    [post]
  )

  /** 广播流式结束（携带最终内容） */
  const broadcastStreamEnd = useCallback(
    (
      sessionId: string,
      messageId: string,
      finalContent: string,
      finalReasoning?: string
    ) => {
      post({
        type: 'stream_end',
        sessionId,
        messageId,
        finalContent,
        finalReasoning,
        timestamp: Date.now(),
      })
    },
    [post]
  )

  /** 广播会话列表变更 */
  const broadcastConversationChange = useCallback(() => {
    post({
      type: 'conversation_changed',
      timestamp: Date.now(),
    })
  }, [post])

  /**
   * 订阅广播事件。返回取消订阅函数。
   * 同一回调重复注册只生效一次（Set 幂等）。
   */
  const subscribe = useCallback((callback: Listener): (() => void) => {
    listenersRef.current.add(callback)
    return () => {
      listenersRef.current.delete(callback)
    }
  }, [])

  return useMemo(
    () => ({
      broadcastStreamStart,
      broadcastStreamChunk,
      broadcastStreamEnd,
      broadcastConversationChange,
      subscribe,
    }),
    [
      broadcastStreamStart,
      broadcastStreamChunk,
      broadcastStreamEnd,
      broadcastConversationChange,
      subscribe,
    ]
  )
}
