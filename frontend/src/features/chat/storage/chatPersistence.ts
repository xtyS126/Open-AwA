/**
 * 聊天消息持久化抽象层 (P1 IndexedDB 分层存储)。
 *
 * - localStorage: 仅保存活跃会话 ID + 会话摘要列表（轻量索引，< 10KB）
 * - IndexedDB:   按会话分桶保存完整消息记录（大量数据，异步存取）
 * - 内存:        流式过程中的临时态，不写盘
 *
 * 无降级：IndexedDB 不可用时消息缓存显式失败（console.error + 状态暴露），
 * 由页面提示"本地缓存不可用"，历史消息交由服务端恢复路径接管。
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
/** IndexedDB 可用性标记：供页面感知"本地消息缓存不可用"状态 */
let _dbAvailable = true

/** 查询当前 IndexedDB 缓存是否可用（供 store/页面感知持久化失败状态） */
export function isChatPersistenceAvailable(): boolean {
  return _dbAvailable
}

function _getDB(): Promise<IDBPDatabase | null> {
  // 失败超过 30s 后允许重试，避免永久失效后无法恢复
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
    _dbAvailable = true
    return db
  }).catch((e) => {
    _dbFailTime = Date.now()
    _dbAvailable = false
    // 显式暴露失败：不降级到 localStorage（5MB 上限会丢数据），页面可感知缓存不可用
    console.error('[chatPersistence] IndexedDB 不可用，本地消息缓存不可用，历史消息将由服务端恢复:', e)
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

/** 异步从 IndexedDB 加载指定会话的消息。IndexedDB 不可用或读取失败时显式抛出，不静默返回空。 */
export async function loadMessages(sessionId: string): Promise<unknown[]> {
  if (!sessionId) return []
  const db = await _getDB()
  if (!db) {
    throw new Error('本地消息缓存不可用（IndexedDB 打开失败），历史消息将由服务端恢复')
  }
  const raw = await db.get(STORE_NAME, sessionId)
  if (!raw || !Array.isArray(raw)) return []
  return raw.slice(-MAX_CACHED_MESSAGES)
}

/** 异步将消息写入 IndexedDB。写入失败显式记录错误（不静默丢弃，也不降级到 localStorage）。 */
export async function saveMessages(sessionId: string, rawMessages: unknown[]): Promise<void> {
  if (!sessionId || sessionId === 'default') return
  const messages = Array.isArray(rawMessages) ? rawMessages.slice(-MAX_CACHED_MESSAGES) : []
  const db = await _getDB()
  if (!db) {
    console.error('[chatPersistence] 消息未持久化：IndexedDB 不可用，消息仅存在于内存，刷新后需从服务端恢复')
    return
  }
  try {
    await db.put(STORE_NAME, messages, sessionId)
  } catch (error) {
    console.error('[chatPersistence] 消息写入 IndexedDB 失败:', error)
  }
}

/** 异步从 IndexedDB 删除指定会话的消息。删除失败显式记录错误。 */
export async function removeMessages(sessionId: string): Promise<void> {
  if (!sessionId) return
  const db = await _getDB()
  if (!db) {
    console.error('[chatPersistence] 无法删除会话缓存：IndexedDB 不可用')
    return
  }
  try {
    await db.delete(STORE_NAME, sessionId)
  } catch (error) {
    console.error('[chatPersistence] 删除会话缓存失败:', error)
  }
}
