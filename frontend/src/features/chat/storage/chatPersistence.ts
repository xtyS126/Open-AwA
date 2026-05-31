/**
 * 消息持久化抽象层。
 *
 * P0: 提供统一的存取接口，当前以 localStorage 为底层实现。
 * P1 将迁移大消息桶到 IndexedDB，本模块提供稳定的上层 API。
 */
import { safeGetJsonItem, safeSetJsonItem } from '@/shared/utils/safeStorage'

const PERSISTENCE_KEY = 'chat_msg_store_v1'

interface MessageBucket {
  updated_at: string
  messages: unknown[]
}

interface PersistenceStore {
  buckets: Record<string, MessageBucket>
}

/**
 * 从持久化存储读取指定会话的消息桶。
 */
export function loadMessages(sessionId: string): unknown[] {
  if (!sessionId) return []
  const store = safeGetJsonItem<PersistenceStore>(PERSISTENCE_KEY, { buckets: {} })
  const bucket = store.buckets?.[sessionId]
  if (!bucket || !Array.isArray(bucket.messages)) return []
  return bucket.messages
}

/**
 * 将消息桶写入持久化存储。
 * 写入是同步的，调用方应在非热路径（消息完成后、会话切换时）调用。
 */
export function saveMessages(sessionId: string, messages: unknown[]): void {
  if (!sessionId || sessionId === 'default') return
  const store = safeGetJsonItem<PersistenceStore>(PERSISTENCE_KEY, { buckets: {} })
  store.buckets[sessionId] = {
    updated_at: new Date().toISOString(),
    messages,
  }
  safeSetJsonItem(PERSISTENCE_KEY, store)
}

/**
 * 从持久化存储删除指定会话的消息桶。
 */
export function removeMessages(sessionId: string): void {
  if (!sessionId) return
  const store = safeGetJsonItem<PersistenceStore>(PERSISTENCE_KEY, { buckets: {} })
  delete store.buckets[sessionId]
  safeSetJsonItem(PERSISTENCE_KEY, store)
}
