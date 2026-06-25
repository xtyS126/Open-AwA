/**
 * 会话相关状态 Store（分域拆分自 chatStore）。
 *
 * 负责 messages、isLoading、sessionId、conversations、pinnedConversations 状态管理。
 * updateLastMessage 会跨域读取 preferenceStore 的 thinkingEnabled 状态。
 */
import { create } from 'zustand'
import { safeGetItem } from '@/shared/utils/safeStorage'
import { persistPinnedConversations } from '@/shared/store/chatStoreEffects'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'
import {
  getActiveSessionId,
  setActiveSessionId,
  getConversationSummaries,
  setConversationSummaries,
  loadMessages,
  saveMessages,
  removeMessages,
} from '@/features/chat/storage/chatPersistence'
import type { ChatMessage, ConversationSessionSummary } from '@/features/chat/types'

interface SessionState {
  /** 当前会话的消息列表 */
  messages: ChatMessage[]
  /** 是否正在加载/发送中 */
  isLoading: boolean
  /** 当前会话 ID */
  sessionId: string
  /** 会话摘要列表 */
  conversations: ConversationSessionSummary[]
  /** 会话总数 */
  conversationsTotal: number
  /** 是否还有更多会话可加载 */
  conversationsHasMore: boolean
  /** 固定的对话历史 ID 列表 */
  pinnedConversations: string[]
  addMessage: (
    role: 'user' | 'assistant',
    content: string,
    reasoning_content?: string,
    id?: string,
    isError?: boolean
  ) => string
  updateLastMessage: (content: string, reasoning_content?: string) => void
  setMessages: (messages: ChatMessage[]) => void
  updateMessage: (messageId: string, updater: (msg: ChatMessage) => ChatMessage) => void
  loadCachedMessages: (sessionId: string) => void
  /** 将当前会话消息显式刷入 IndexedDB（消息完成/会话切换时调用） */
  flushMessages: () => void
  setLoading: (loading: boolean) => void
  clearMessages: () => void
  setSessionId: (id: string) => void
  setConversations: (
    items: ConversationSessionSummary[],
    total?: number,
    hasMore?: boolean
  ) => void
  upsertConversation: (item: ConversationSessionSummary) => void
  removeConversation: (sessionId: string) => void
  pinConversation: (sessionId: string) => void
  unpinConversation: (sessionId: string) => void
}

const initialSessionId = getActiveSessionId() || 'default'

/** 加载请求序列号，用于防止异步加载竞态：只有最新请求的结果才会写入 state */
let loadSequenceNumber = 0

/** 从 localStorage 读取固定的对话 ID 列表 */
function loadPinnedConversations(): string[] {
  try {
    const stored = safeGetItem('chat_pinned_conversations', '[]')
    return JSON.parse(stored) as string[]
  } catch {
    return []
  }
}

export const useSessionStore = create<SessionState>((set) => ({
  // 消息为空，由 ChatPage 在路由进入时通过 loadMessages() 异步加载
  messages: [],
  isLoading: false,
  sessionId: initialSessionId,
  conversations: getConversationSummaries() as ConversationSessionSummary[],
  conversationsTotal: getConversationSummaries().length,
  conversationsHasMore: false,
  pinnedConversations: loadPinnedConversations(),

  addMessage: (role, content, reasoning_content, id, isError) => {
    const messageId = id || crypto.randomUUID()
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: messageId,
          role,
          content,
          reasoning_content,
          timestamp: new Date(),
          ...(isError ? { isError: true } : {}),
        },
      ],
    }))
    return messageId
  },

  updateLastMessage: (content, reasoning_content) =>
    set((state) => {
      if (state.messages.length === 0) return state
      const lastMessage = state.messages[state.messages.length - 1]

      if (lastMessage.role === 'assistant') {
        // 跨域读取 preferenceStore 的 thinkingEnabled 状态
        const thinkingEnabled = usePreferenceStore.getState().thinkingEnabled
        // 创建新对象而非修改原对象，保持 Zustand 不可变性
        const updatedMessage = {
          ...lastMessage,
          content: lastMessage.content + content,
          reasoning_content:
            thinkingEnabled && reasoning_content
              ? (lastMessage.reasoning_content || '') + reasoning_content
              : lastMessage.reasoning_content,
        }
        const newMessages = [...state.messages.slice(0, -1), updatedMessage]
        return { messages: newMessages }
      }
      return state
    }),

  setMessages: (messages) => set({ messages }),

  updateMessage: (messageId, updater) =>
    set((state) => {
      const nextMessages = state.messages.map((msg) =>
        msg.id === messageId ? updater(msg) : msg
      )
      return { messages: nextMessages }
    }),

  loadCachedMessages: (sessionId) => {
    // 异步加载由 ChatPage 处理，这里同步设为空然后由调用方异步填充
    const seq = ++loadSequenceNumber
    set({ messages: [] })
    void loadMessages(sessionId).then((msgs) => {
      // 仅当此请求仍为最新时才写入 state，防止竞态
      if (seq === loadSequenceNumber) {
        const currentId = useSessionStore.getState().sessionId
        if (currentId === sessionId && Array.isArray(msgs) && msgs.length > 0) {
          set({ messages: msgs as ChatMessage[] })
        }
      }
    })
  },

  setLoading: (loading) => set({ isLoading: loading }),

  clearMessages: () => set({ messages: [] }),

  // 将当前会话消息显式写入 IndexedDB（消息完成/会话切换/页面隐藏时调用）
  flushMessages: () => {
    const state = useSessionStore.getState()
    if (state.sessionId && state.sessionId !== 'default' && state.messages.length > 0) {
      void saveMessages(state.sessionId, state.messages)
    }
  },

  setSessionId: (id) => {
    setActiveSessionId(id)
    // 先设空，异步加载
    const seq = ++loadSequenceNumber
    set({ sessionId: id, messages: [] })
    void loadMessages(id).then((msgs) => {
      // 仅当此请求仍为最新时才写入 state，防止竞态
      if (seq === loadSequenceNumber) {
        const currentId = useSessionStore.getState().sessionId
        if (currentId === id && Array.isArray(msgs) && msgs.length > 0) {
          set({ messages: msgs as ChatMessage[] })
        }
      }
    })
  },

  setConversations: (items, total, hasMore) => {
    setConversationSummaries(items)
    set({
      conversations: items,
      conversationsTotal: total ?? items.length,
      conversationsHasMore: hasMore ?? false,
    })
  },

  upsertConversation: (item) =>
    set((state) => {
      const existingIndex = state.conversations.findIndex(
        (entry) => entry.session_id === item.session_id
      )
      const nextItems = [...state.conversations]
      if (existingIndex >= 0) {
        nextItems[existingIndex] = item
      } else {
        nextItems.unshift(item)
      }
      setConversationSummaries(nextItems)
      return {
        conversations: nextItems,
        conversationsTotal: Math.max(state.conversationsTotal, nextItems.length),
      }
    }),

  removeConversation: (sessionId) =>
    set((state) => {
      const nextItems = state.conversations.filter(
        (item) => item.session_id !== sessionId
      )
      void removeMessages(sessionId)
      setConversationSummaries(nextItems)
      return {
        conversations: nextItems,
        conversationsTotal: Math.max(0, state.conversationsTotal - 1),
      }
    }),

  pinConversation: (sessionId) =>
    set((state) => {
      if (state.pinnedConversations.includes(sessionId)) return state
      // 最多固定 10 个对话
      if (state.pinnedConversations.length >= 10) return state
      const next = [sessionId, ...state.pinnedConversations]
      persistPinnedConversations(next)
      return { pinnedConversations: next }
    }),

  unpinConversation: (sessionId) =>
    set((state) => {
      const next = state.pinnedConversations.filter((id) => id !== sessionId)
      persistPinnedConversations(next)
      return { pinnedConversations: next }
    }),
}))
