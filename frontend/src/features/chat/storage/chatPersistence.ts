/**
 * 聊天消息持久化抽象层 (P1 IndexedDB 分层存储)。
 *
 * - localStorage: 仅保存活跃会话 ID + 会话摘要列表（轻量索引，< 10KB）
 * - IndexedDB:   按会话分桶保存完整消息记录（大量数据，异步存取）
 * - 内存:        流式过程中的临时态，不写盘
 *
 * 降级策略：IndexedDB 不可用时自动回退 localStorage。
 */
import { openDB, type IDBPDatabase } from 'idb'
import { safeGetJsonItem, safeSetJsonItem, safeGetItem, safeSetItem } from '@/shared/utils/safeStorage'

// ============================================================
// 常量
// ============================================================
const DB_NAME = 'openawa-chat'
const DB_VERSION = 1
const STORE_NAME = 'message-buckets'
const LS_ACTIVE_SESSION = 'chat_active_session_v1'
const LS_CONVERSATIONS = 'chat_conversations_v1'
const MAX_CACHED_MESSAGES = 200

// ============================================================
// IndexedDB 连接（懒初始化单例）
// ============================================================
let _dbPromise: Promise<IDBPDatabase | null> | null = null
let _dbFailTime = 0

function _getDB(): Promise<IDBPDatabase | null> {
  // P1 fix: 失败超过 30s 后允许重试，避免永久卡在降级模式
  if (_dbPromise) {
    if (_dbFailTime > 0 && Date.now() - _dbFailTime > 30_000) {
      _dbPromise = null  // 过期重试
    } else {
      return _dbPromise
    }
  }
  _dbPromise = openDB(DB_NAME, DB_VERSION, {
    upgrade(db) {
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME)
      }
    },
  }).then(db => {
    _dbFailTime = 0
    return db
  }).catch((e) => {
    _dbFailTime = Date.now()
    console.warn('[chatPersistence] IndexedDB 不可用，降级到 localStorage:', e)
    return null
  })
  return _dbPromise
}

// ============================================================
// 活跃会话 ID（localStorage 轻量索引）
// ============================================================
export function getActiveSessionId(): string {
  return safeGetItem(LS_ACTIVE_SESSION, '')
}

export function setActiveSessionId(id: string): void {
  safeSetItem(LS_ACTIVE_SESSION, id)
}

// ============================================================
// 会话摘要（localStorage）
// ============================================================
export function getConversationSummaries<T = unknown>(): T[] {
  return safeGetJsonItem<T[]>(LS_CONVERSATIONS, [])
}

export function setConversationSummaries<T = unknown>(items: T[]): void {
  // 最多保留 200 个会话摘要（与 MAX_CACHED_MESSAGES 对齐）
  safeSetJsonItem(LS_CONVERSATIONS, items.slice(0, 200))
}

// ============================================================
// 消息存取（IndexedDB 主存储）
// ============================================================

/** 异步从 IndexedDB 加载指定会话的消息 */
export async function loadMessages(sessionId: string): Promise<unknown[]> {
  if (!sessionId) return []
  const db = await _getDB()
  if (!db) {
    // 降级：从 localStorage 读取（兼容旧缓存）
    return _loadMessagesFromLS(sessionId)
  }
  try {
    const raw = await db.get(STORE_NAME, sessionId)
    if (!raw || !Array.isArray(raw)) return []
    return raw.slice(-MAX_CACHED_MESSAGES)
  } catch {
    return []
  }
}

/** 异步将消息写入 IndexedDB */
export async function saveMessages(sessionId: string, rawMessages: unknown[]): Promise<void> {
  if (!sessionId || sessionId === 'default') return
  const messages = Array.isArray(rawMessages) ? rawMessages.slice(-MAX_CACHED_MESSAGES) : []
  const db = await _getDB()
  if (!db) {
    _saveMessagesToLS(sessionId, messages)
    return
  }
  try {
    await db.put(STORE_NAME, messages, sessionId)
  } catch {
    _saveMessagesToLS(sessionId, messages)
  }
}

/** 异步从 IndexedDB 删除指定会话的消息 */
export async function removeMessages(sessionId: string): Promise<void> {
  if (!sessionId) return
  const db = await _getDB()
  if (!db) {
    _removeMessagesFromLS(sessionId)
    return
  }
  try {
    await db.delete(STORE_NAME, sessionId)
  } catch {
    _removeMessagesFromLS(sessionId)
  }
}

/** 获取所有缓存的会话 ID 列表（用于缓存管理） */
export async function getAllCachedSessionIds(): Promise<string[]> {
  const db = await _getDB()
  if (!db) return []
  try {
    return await db.getAllKeys(STORE_NAME) as string[]
  } catch {
    return []
  }
}

/** 清理超过 maxSessions 个会话的旧缓存 */
export async function pruneOldSessions(maxSessions: number = 50): Promise<void> {
  const db = await _getDB()
  if (!db) return
  // 获取所有缓存的会话及时间戳，按时间排序后删除最旧的
  const allKeys = await db.getAllKeys(STORE_NAME)
  if (allKeys.length <= maxSessions) return
  const entries: { key: string; updatedAt: number }[] = []
  for (const key of allKeys) {
    try {
      const record = await db.get(STORE_NAME, key)
      entries.push({ key: key as string, updatedAt: (record as any)?.timestamp || 0 })
    } catch { entries.push({ key: key as string, updatedAt: 0 }) }
  }
  entries.sort((a, b) => a.updatedAt - b.updatedAt)
  const toRemove = entries.slice(0, entries.length - maxSessions)
  for (const { key } of toRemove) {
    try { await db.delete(STORE_NAME, key) } catch { /* 忽略单条删除失败 */ }
  }
}

// ============================================================
// localStorage 降级实现
// ============================================================
const LS_MSGS_PREFIX = 'chat_msgs_v1_'

function _lsMsgKey(sessionId: string): string {
  return LS_MSGS_PREFIX + sessionId
}

function _loadMessagesFromLS(sessionId: string): unknown[] {
  const key = _lsMsgKey(sessionId)
  const raw = safeGetJsonItem<{ messages: unknown[] }>(key, { messages: [] })
  if (!raw || !Array.isArray(raw.messages)) return []
  return raw.messages.slice(-MAX_CACHED_MESSAGES)
}

function _saveMessagesToLS(sessionId: string, messages: unknown[]): void {
  safeSetJsonItem(_lsMsgKey(sessionId), { messages, updated_at: new Date().toISOString() })
}

function _removeMessagesFromLS(sessionId: string): void {
  try { localStorage.removeItem(_lsMsgKey(sessionId)) } catch { /* 静默处理 */ }
}
