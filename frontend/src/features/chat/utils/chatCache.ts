import { safeGetJsonItem, safeSetJsonItem } from '@/shared/utils/safeStorage'
import type { ChatMessage, ConversationSessionSummary } from '@/features/chat/types'

const CHAT_CACHE_STORAGE_KEY = 'chat_cache_v1'
const CHAT_CACHE_VERSION = 1
const MAX_CACHED_MESSAGES = 200
const MAX_CACHED_CONVERSATIONS = 100

interface SerializedChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning_content?: string
  timestamp: string
}

interface SerializedConversationBucket {
  updated_at: string
  messages: SerializedChatMessage[]
}

interface ChatCachePayload {
  version: number
  activeSessionId: string
  conversations: ConversationSessionSummary[]
  messageBuckets: Record<string, SerializedConversationBucket>
}

const defaultPayload = (): ChatCachePayload => ({
  version: CHAT_CACHE_VERSION,
  activeSessionId: '',
  conversations: [],
  messageBuckets: {},
})

function isValidIsoDate(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value))
}

function isValidConversationSummary(value: unknown): value is ConversationSessionSummary {
  if (!value || typeof value !== 'object') {
    return false
  }

  const item = value as Record<string, unknown>
  return (
    typeof item.session_id === 'string' &&
    typeof item.user_id === 'string' &&
    typeof item.title === 'string' &&
    typeof item.summary === 'string' &&
    typeof item.last_message_preview === 'string' &&
    typeof item.message_count === 'number' &&
    isValidIsoDate(item.created_at) &&
    isValidIsoDate(item.updated_at)
  )
}

function isValidSerializedMessage(value: unknown): value is SerializedChatMessage {
  if (!value || typeof value !== 'object') {
    return false
  }
  const item = value as Record<string, unknown>
  return (
    typeof item.id === 'string' &&
    (item.role === 'user' || item.role === 'assistant') &&
    typeof item.content === 'string' &&
    isValidIsoDate(item.timestamp)
  )
}

function normalizeConversationList(conversations: unknown): ConversationSessionSummary[] {
  if (!Array.isArray(conversations)) {
    return []
  }
  return conversations.filter(isValidConversationSummary).slice(0, MAX_CACHED_CONVERSATIONS)
}

function normalizeMessageBuckets(rawBuckets: unknown): Record<string, SerializedConversationBucket> {
  if (!rawBuckets || typeof rawBuckets !== 'object') {
    return {}
  }

  const nextBuckets: Record<string, SerializedConversationBucket> = {}
  for (const [sessionId, value] of Object.entries(rawBuckets as Record<string, unknown>)) {
    if (!sessionId || !value || typeof value !== 'object') {
      continue
    }
    const bucket = value as Record<string, unknown>
    if (!Array.isArray(bucket.messages)) {
      continue
    }
    nextBuckets[sessionId] = {
      updated_at: isValidIsoDate(bucket.updated_at) ? bucket.updated_at : new Date().toISOString(),
      messages: bucket.messages.filter(isValidSerializedMessage).slice(-MAX_CACHED_MESSAGES),
    }
  }
  return nextBuckets
}

function readChatCache(): ChatCachePayload {
  const raw = safeGetJsonItem<Partial<ChatCachePayload>>(CHAT_CACHE_STORAGE_KEY, defaultPayload())
  if (!raw || raw.version !== CHAT_CACHE_VERSION) {
    return defaultPayload()
  }

  return {
    version: CHAT_CACHE_VERSION,
    activeSessionId: typeof raw.activeSessionId === 'string' ? raw.activeSessionId : '',
    conversations: normalizeConversationList(raw.conversations),
    messageBuckets: normalizeMessageBuckets(raw.messageBuckets),
  }
}

function writeChatCache(payload: ChatCachePayload): void {
  safeSetJsonItem(CHAT_CACHE_STORAGE_KEY, payload)
}

function serializeMessages(messages: ChatMessage[]): SerializedChatMessage[] {
  return messages.slice(-MAX_CACHED_MESSAGES).map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    reasoning_content: message.reasoning_content,
    timestamp: message.timestamp.toISOString(),
  }))
}

function deserializeMessages(messages: SerializedChatMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    reasoning_content: message.reasoning_content,
    timestamp: new Date(message.timestamp),
  }))
}

export function getActiveConversationId(): string {
  return readChatCache().activeSessionId
}

export function setActiveConversationId(sessionId: string): void {
  const payload = readChatCache()
  payload.activeSessionId = sessionId
  writeChatCache(payload)
}

export function getCachedConversationSummaries(): ConversationSessionSummary[] {
  return readChatCache().conversations
}

export function setCachedConversationSummaries(conversations: ConversationSessionSummary[]): void {
  const payload = readChatCache()
  payload.conversations = normalizeConversationList(conversations)
  writeChatCache(payload)
}

export function getCachedConversationMessages(sessionId: string): ChatMessage[] {
  if (!sessionId) {
    return []
  }
  const bucket = readChatCache().messageBuckets[sessionId]
  if (!bucket) {
    return []
  }
  return deserializeMessages(bucket.messages)
}

export function setCachedConversationMessages(sessionId: string, messages: ChatMessage[]): void {
  if (!sessionId || sessionId === 'default') {
    return
  }
  const payload = readChatCache()
  payload.messageBuckets[sessionId] = {
    updated_at: new Date().toISOString(),
    messages: serializeMessages(messages),
  }
  writeChatCache(payload)
}

export function deleteCachedConversationMessages(sessionId: string): void {
  if (!sessionId) {
    return
  }
  const payload = readChatCache()
  delete payload.messageBuckets[sessionId]
  writeChatCache(payload)
}