/**
 * 跨标签页聊天广播副作用 Hook。
 *
 * 将 ChatPage 中与跨标签页广播相关的三个副作用集中管理：
 * 1. 订阅远程广播事件，应用到当前 store（防重复：当前标签页正在主动流式时跳过）
 * 2. 节流广播当前流式 chunk 到其他标签页（200ms 间隔或 50 字符增量阈值）
 * 3. 监听 streamingAssistantId 状态过渡，广播流式开始/结束事件
 *
 * 抽离目的：ChatPage 主组件只关心广播订阅的"是否启用"，
 * 不再承担具体的节流/状态过渡计算逻辑，便于独立测试与复用。
 */
import { useEffect, useRef } from 'react'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import type { ChatMessage } from '@/features/chat/types'
import type { ChatBroadcastEvent } from '@/features/chat/hooks/useChatBroadcast'

/** 节流广播的最小时间间隔（ms） */
const CHUNK_BROADCAST_MIN_INTERVAL_MS = 200

/** 节流广播的最小内容增量（字符数） */
const CHUNK_BROADCAST_MIN_DELTA_CHARS = 50

/** useChatBroadcastEffects 入参 */
export interface UseChatBroadcastEffectsParams {
  /** 当前流式助手消息 ID（null 表示未流式） */
  streamingAssistantId: string | null
  /** streamingAssistantId 的 ref 镜像，供订阅回调同步读取最新值 */
  streamingAssistantIdRef: React.MutableRefObject<string | null>
  /** 当前会话所有消息（用于读取流式消息内容做节流广播） */
  messages: ChatMessage[]
  /** 注册广播事件回调，返回取消订阅函数 */
  subscribe: (callback: (event: ChatBroadcastEvent) => void) => () => void
  /** 广播流式开始事件 */
  broadcastStreamStart: (sessionId: string, messageId: string, userMessage: string) => void
  /** 广播流式 chunk 事件 */
  broadcastStreamChunk: (
    sessionId: string,
    messageId: string,
    content: string,
    reasoning?: string
  ) => void
  /** 广播流式结束事件 */
  broadcastStreamEnd: (
    sessionId: string,
    messageId: string,
    finalContent: string,
    finalReasoning?: string
  ) => void
  /**
   * 标记当前流式是否需要广播到其他标签页的 ref。
   * 由调用方在 handleSend 中设置，用于判断是否发送 broadcastStreamStart。
   * 避免在 options 中注入 assistantMessageId 导致 useChatStream 误判
   * assistantMessageCreated=true，从而破坏重试与消息创建逻辑。
   */
  shouldBroadcastCurrentStreamRef: React.MutableRefObject<boolean>
}

/**
 * 跨标签页聊天广播副作用 Hook。
 *
 * 调用方仅需传入流式状态与广播方法，本 hook 内部管理节流状态与状态过渡检测。
 */
export function useChatBroadcastEffects({
  streamingAssistantId,
  streamingAssistantIdRef,
  messages,
  subscribe,
  broadcastStreamStart,
  broadcastStreamChunk,
  broadcastStreamEnd,
  shouldBroadcastCurrentStreamRef,
}: UseChatBroadcastEffectsParams): void {
  // 节流广播状态：记录上次广播的内容与时间戳
  const lastChunkBroadcastRef = useRef<{ content: string; time: number }>({
    content: '',
    time: 0,
  })
  // 上一次的 streamingAssistantId，用于检测状态过渡（null → 非空 / 非空 → null）
  const prevStreamingIdRef = useRef<string | null>(null)

  // 副作用 1：订阅远程广播事件，应用到当前 store
  // 防重复关键：若当前标签页正在主动流式该消息（streamingAssistantIdRef 与事件 messageId 一致），
  // 说明当前标签页是发起方，跳过应用远程事件，避免重复追加。
  useEffect(() => {
    const unsubscribe = subscribe((event: ChatBroadcastEvent) => {
      // 防重复：当前标签页正在主动流式该消息时，跳过远程事件
      if (
        streamingAssistantIdRef.current !== null &&
        event.type !== 'conversation_changed' &&
        event.messageId === streamingAssistantIdRef.current
      ) {
        return
      }
      switch (event.type) {
        case 'stream_start':
          useSessionStore.getState().applyRemoteStreamStart(
            event.sessionId,
            event.messageId,
            event.userMessage
          )
          break
        case 'stream_chunk':
          useSessionStore.getState().applyRemoteStreamChunk(
            event.sessionId,
            event.messageId,
            event.content,
            event.reasoning
          )
          break
        case 'stream_end':
          useSessionStore.getState().applyRemoteStreamEnd(
            event.sessionId,
            event.messageId,
            event.finalContent,
            event.finalReasoning
          )
          break
        case 'conversation_changed':
          useSessionStore.getState().applyRemoteConversationChange()
          break
      }
    })
    return unsubscribe
  }, [subscribe, streamingAssistantIdRef])

  // 副作用 2：节流广播流式 chunk
  // 监听当前流式助手消息的 content/reasoning_content 变化，
  // 按 200ms 间隔或 50 字符增量的阈值节流广播，避免高频 chunk 淹没其他标签页。
  useEffect(() => {
    if (!streamingAssistantId) return
    const currentMessage = messages.find((m) => m.id === streamingAssistantId)
    if (!currentMessage || currentMessage.role !== 'assistant') return

    const now = Date.now()
    const contentDelta = currentMessage.content.length - lastChunkBroadcastRef.current.content.length
    // 节流：距上次广播不足 200ms 且内容增量不足 50 字符时跳过
    if (now - lastChunkBroadcastRef.current.time < CHUNK_BROADCAST_MIN_INTERVAL_MS && contentDelta < CHUNK_BROADCAST_MIN_DELTA_CHARS) {
      return
    }

    // 使用 getState().sessionId 读取最新会话 ID，避免闭包捕获过期值
    const currentSessionId = useSessionStore.getState().sessionId
    if (currentSessionId === 'default') return

    broadcastStreamChunk(
      currentSessionId,
      streamingAssistantId,
      currentMessage.content,
      currentMessage.reasoning_content
    )
    lastChunkBroadcastRef.current = { content: currentMessage.content, time: now }
  }, [streamingAssistantId, messages, broadcastStreamChunk])

  // 副作用 3：流式开始/结束广播
  // 检测 streamingAssistantId 的状态过渡：
  // - null → 非空：流式开始，广播 stream_start（携带最后一条用户消息）
  // - 非空 → null：流式结束，广播 stream_end（携带最终内容）
  // 同时在流式开始时重置节流状态。
  useEffect(() => {
    const prevId = prevStreamingIdRef.current
    prevStreamingIdRef.current = streamingAssistantId

    if (prevId && !streamingAssistantId) {
      // 从非空变为 null：流式结束，广播最终内容
      const finalMessage = useSessionStore.getState().messages.find((m) => m.id === prevId)
      const currentSessionId = useSessionStore.getState().sessionId
      if (finalMessage && currentSessionId !== 'default') {
        broadcastStreamEnd(
          currentSessionId,
          prevId,
          finalMessage.content,
          finalMessage.reasoning_content
        )
      }
      // 重置节流状态，为下次流式做准备
      lastChunkBroadcastRef.current = { content: '', time: 0 }
      // 重置广播标记
      shouldBroadcastCurrentStreamRef.current = false
    } else if (!prevId && streamingAssistantId) {
      // 从 null 变为非空：流式开始
      // 重置节流状态，确保第一个 chunk 能立即广播
      lastChunkBroadcastRef.current = { content: '', time: 0 }
      // 仅在需要广播时（用户主动发送消息）发送 stream_start
      if (shouldBroadcastCurrentStreamRef.current) {
        const currentSessionId = useSessionStore.getState().sessionId
        if (currentSessionId !== 'default') {
          // 从 store 中读取最后一条用户消息作为广播内容
          const currentMessages = useSessionStore.getState().messages
          const lastUserMessage = [...currentMessages].reverse().find((m) => m.role === 'user')
          if (lastUserMessage) {
            broadcastStreamStart(currentSessionId, streamingAssistantId, lastUserMessage.content)
          }
        }
      }
    }
  }, [streamingAssistantId, broadcastStreamStart, broadcastStreamEnd, shouldBroadcastCurrentStreamRef])
}
