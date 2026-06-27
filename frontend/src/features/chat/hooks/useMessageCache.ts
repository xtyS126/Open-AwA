import { useCallback } from 'react'
import type { AssistantExecutionMeta, AssistantMessageSegment, ChatMessage } from '@/features/chat/types'
import {
  getActiveConversationId,
  getCachedConversationMessages,
} from '@/features/chat/utils/chatCache'
import {
  createEmptyExecutionMeta,
  applyTaskUpdate,
  applyToolUpdate,
  hasExecutionMeta,
} from '@/features/chat/utils/executionMeta'
import { useSessionStore } from '@/features/chat/store/sessionStore'

/**
 * 从消息分段中构建执行元数据。
 * 遍历所有 thought 类型的分段，提取意图、任务步骤、工具事件和用量信息。
 */
function buildMessageMetaFromSegments(
  segments: AssistantMessageSegment[] | undefined
): AssistantExecutionMeta | undefined {
  if (!segments || segments.length === 0) {
    return undefined
  }

  let meta = createEmptyExecutionMeta()
  for (const segment of segments) {
    if (segment.kind !== 'thought') {
      continue
    }
    if (segment.intent) {
      meta.intent = segment.intent
    }
    for (const step of segment.steps) {
      meta = applyTaskUpdate(meta, step as unknown as Record<string, unknown>)
    }
    for (const tool of segment.toolEvents) {
      meta = applyToolUpdate(meta, tool as unknown as Record<string, unknown>)
    }
    if (segment.usage) {
      meta.usage = segment.usage
    }
  }

  return hasExecutionMeta(meta) ? meta : undefined
}

/**
 * 从消息列表中构建执行元数据映射。
 * 优先从分段构建，否则从 toolEvents 构建。
 */
function buildMessageMetaFromMessages(messages: ChatMessage[]): Record<string, AssistantExecutionMeta> {
  const restoredMeta: Record<string, AssistantExecutionMeta> = {}

  for (const message of messages) {
    if (message.role !== 'assistant') {
      continue
    }

    const segmentMeta = buildMessageMetaFromSegments(message.segments)
    if (segmentMeta) {
      restoredMeta[message.id] = segmentMeta
      continue
    }

    if (message.toolEvents && message.toolEvents.length > 0) {
      restoredMeta[message.id] = {
        steps: [],
        toolEvents: message.toolEvents,
      }
    }
  }

  return restoredMeta
}

/**
 * 合并服务器历史与缓存消息。
 * 保留缓存中的 reasoning_content、toolEvents、segments 等本地增强字段。
 *
 * 匹配策略：以 (role, content) 作为消息指纹，按内容匹配而非按数组索引匹配。
 * 这样即使某条消息的 content 在远程与缓存间存在细微差异（流式累积版本 vs 后端存储版本），
 * 也不会破坏后续消息的匹配，避免缓存中靠后的用户消息（如第二轮提问）被整体丢弃。
 * 缓存中未被远程匹配的消息（如尚未持久化的乐观插入消息）会追加到结果尾部，避免丢失。
 */
function mergeServerHistoryWithCached(
  remoteMessages: ChatMessage[],
  cachedMessages: ChatMessage[]
): ChatMessage[] {
  if (remoteMessages.length === 0) {
    return cachedMessages
  }

  // 构建 (role, content) -> 缓存索引列表的映射，支持重复内容的消息各取一份
  const cacheIndicesByKey = new Map<string, number[]>()
  cachedMessages.forEach((msg, index) => {
    const key = `${msg.role}:${msg.content}`
    const list = cacheIndicesByKey.get(key)
    if (list) {
      list.push(index)
    } else {
      cacheIndicesByKey.set(key, [index])
    }
  })

  const usedCacheIndices = new Set<number>()

  const mergedMessages = remoteMessages.map((remoteMessage) => {
    const key = `${remoteMessage.role}:${remoteMessage.content}`
    const indices = cacheIndicesByKey.get(key)
    if (!indices || indices.length === 0) {
      return remoteMessage
    }

    // 取第一个未使用的缓存索引，保证重复内容消息各自匹配
    const cacheIndex = indices.find((i) => !usedCacheIndices.has(i))
    if (cacheIndex === undefined) {
      return remoteMessage
    }
    usedCacheIndices.add(cacheIndex)

    const cachedMessage = cachedMessages[cacheIndex]
    if (remoteMessage.role !== 'assistant') {
      return remoteMessage
    }

    return {
      ...remoteMessage,
      reasoning_content: remoteMessage.reasoning_content ?? cachedMessage.reasoning_content,
      toolEvents: remoteMessage.toolEvents?.length ? remoteMessage.toolEvents : cachedMessage.toolEvents,
      segments: remoteMessage.segments?.length ? remoteMessage.segments : cachedMessage.segments,
    }
  })

  // 追加缓存中未匹配的消息（如尚未持久化的乐观插入消息），保持缓存原始顺序
  const extraCached = cachedMessages.filter((_, index) => !usedCacheIndices.has(index))

  return [...mergedMessages, ...extraCached]
}

/**
 * 获取本地消息用于恢复。
 * 优先从当前 store 获取，否则从 IndexedDB 缓存获取。
 */
function getLocalMessagesForRestore(targetSessionId: string): ChatMessage[] {
  const state = useSessionStore.getState()
  if (state.sessionId === targetSessionId && state.messages.length > 0) {
    return state.messages
  }

  return getCachedConversationMessages(targetSessionId)
}

export interface UseMessageCacheReturn {
  /** 获取本地消息用于恢复 */
  getLocalMessagesForRestore: (sessionId: string) => ChatMessage[]
  /** 从消息列表构建执行元数据映射 */
  buildMessageMetaFromMessages: (messages: ChatMessage[]) => Record<string, AssistantExecutionMeta>
  /** 合并服务器历史与缓存消息 */
  mergeServerHistoryWithCached: (remote: ChatMessage[], cached: ChatMessage[]) => ChatMessage[]
  /** 刷新对话缓存到 IndexedDB */
  flushConversationCache: () => void
  /** 获取当前活跃的会话 ID */
  getActiveConversationId: () => string | undefined
}

/**
 * 管理消息缓存相关的逻辑。
 *
 * 提供消息的本地缓存读取、服务器历史合并、执行元数据恢复等功能。
 */
export function useMessageCache(): UseMessageCacheReturn {
  /** 刷新对话缓存到 IndexedDB */
  const flushConversationCache = useCallback(() => {
    // 使用 store 内置的 flushMessages（内部调用 IndexedDB saveMessages）
    useSessionStore.getState().flushMessages()
  }, [])

  return {
    getLocalMessagesForRestore,
    buildMessageMetaFromMessages,
    mergeServerHistoryWithCached,
    flushConversationCache,
    getActiveConversationId,
  }
}
