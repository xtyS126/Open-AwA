import { safeGetJsonItem, safeSetJsonItem } from '@/shared/utils/safeStorage'
import type {
  AssistantMessageSegment,
  ChatMessage,
  ConversationSessionSummary,
  ToolEventMeta,
} from '@/features/chat/types'

const CHAT_CACHE_STORAGE_KEY = 'chat_cache_v1'
const CHAT_CACHE_VERSION = 1
const MAX_CACHED_MESSAGES = 200
const MAX_CACHED_CONVERSATIONS = 100
const MESSAGE_CACHE_THROTTLE_MS = 1000

interface SerializedToolEvent {
  id: string
  kind: string
  name: string
  status: string
  detail?: string
  input?: Record<string, unknown>
  output?: unknown
  sequence?: number
  startedAt?: number
  completedAt?: number
}

interface SerializedChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning_content?: string
  timestamp: string
  toolEvents?: SerializedToolEvent[]
  segments?: AssistantMessageSegment[]
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

function serializeToolEvents(events: ToolEventMeta[] | undefined): SerializedToolEvent[] | undefined {
  if (!events || events.length === 0) return undefined
  return events.map((e) => ({
    id: e.id,
    kind: e.kind,
    name: e.name,
    status: e.status,
    detail: e.detail,
    input: e.input,
    output: e.output,
    sequence: e.sequence,
    startedAt: e.startedAt,
    completedAt: e.completedAt,
  }))
}

function deserializeToolEvents(events: SerializedToolEvent[] | undefined): ToolEventMeta[] | undefined {
  if (!events || events.length === 0) return undefined
  return events.map((e) => ({
    id: e.id,
    kind: e.kind,
    name: e.name,
    status: e.status as ToolEventMeta['status'],
    detail: e.detail,
    input: e.input,
    output: e.output,
    sequence: e.sequence,
    startedAt: e.startedAt,
    completedAt: e.completedAt,
  }))
}

function serializeMessages(messages: ChatMessage[]): SerializedChatMessage[] {
  return messages.slice(-MAX_CACHED_MESSAGES).map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    reasoning_content: message.reasoning_content,
    timestamp: message.timestamp.toISOString(),
    toolEvents: serializeToolEvents(message.toolEvents),
    segments: message.segments,
  }))
}

function deserializeMessages(messages: SerializedChatMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    reasoning_content: message.reasoning_content,
    timestamp: new Date(message.timestamp),
    toolEvents: deserializeToolEvents(message.toolEvents),
    segments: Array.isArray(message.segments) ? message.segments : undefined,
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

let _lastMessageCacheWrite = 0

export function setCachedConversationMessages(sessionId: string, messages: ChatMessage[]): void {
  if (!sessionId || sessionId === 'default') {
    return
  }
  const now = Date.now()
  if (now - _lastMessageCacheWrite < MESSAGE_CACHE_THROTTLE_MS) {
    return
  }
  _lastMessageCacheWrite = now
  const payload = readChatCache()
  payload.messageBuckets[sessionId] = {
    updated_at: new Date().toISOString(),
    messages: serializeMessages(messages),
  }
  writeChatCache(payload)
}

export function flushCachedConversationMessages(sessionId: string, messages: ChatMessage[]): void {
  if (!sessionId || sessionId === 'default') {
    return
  }
  const payload = readChatCache()
  payload.messageBuckets[sessionId] = {
    updated_at: new Date().toISOString(),
    messages: serializeMessages(messages),
  }
  writeChatCache(payload)
  _lastMessageCacheWrite = Date.now()
}

export function deleteCachedConversationMessages(sessionId: string): void {
  if (!sessionId) {
    return
  }
  const payload = readChatCache()
  delete payload.messageBuckets[sessionId]
  writeChatCache(payload)
}
