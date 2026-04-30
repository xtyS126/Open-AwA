import { create } from 'zustand'
import { safeGetItem, safeSetItem } from '@/shared/utils/safeStorage'
import {
  deleteCachedConversationMessages,
  getActiveConversationId,
  getCachedConversationMessages,
  getCachedConversationSummaries,
  setActiveConversationId,
  setCachedConversationMessages,
  setCachedConversationSummaries,
} from '@/features/chat/utils/chatCache'
import type { ChatMessage, ConversationSessionSummary } from '@/features/chat/types'

// 模型配置项，用于全局模型选择
export interface ModelOption {
  id: string
  provider: string
  model: string
  display_name: string
}

interface ChatState {
  messages: ChatMessage[]
  isLoading: boolean
  sessionId: string
  conversations: ConversationSessionSummary[]
  conversationsTotal: number
  conversationsHasMore: boolean
  outputMode: 'stream' | 'direct'
  // 全局模型选择状态
  selectedModel: string
  modelOptions: ModelOption[]
  modelLoading: boolean
  modelError: string | null
  // 思考模式状态
  thinkingEnabled: boolean
  thinkingDepth: number
  addMessage: (role: 'user' | 'assistant', content: string, reasoning_content?: string, id?: string) => string
  updateLastMessage: (content: string, reasoning_content?: string) => void
  setMessages: (messages: ChatMessage[]) => void
  loadCachedMessages: (sessionId: string) => void
  setLoading: (loading: boolean) => void
  clearMessages: () => void
  setSessionId: (id: string) => void
  setConversations: (items: ConversationSessionSummary[], total?: number, hasMore?: boolean) => void
  upsertConversation: (item: ConversationSessionSummary) => void
  removeConversation: (sessionId: string) => void
  setOutputMode: (mode: 'stream' | 'direct') => void
  setSelectedModel: (model: string) => void
  setModelOptions: (options: ModelOption[]) => void
  setModelLoading: (loading: boolean) => void
  setModelError: (error: string | null) => void
  setThinkingEnabled: (enabled: boolean) => void
  setThinkingDepth: (depth: number) => void
}

const initialSessionId = getActiveConversationId() || 'default'

export const useChatStore = create<ChatState>((set) => ({
  messages: getCachedConversationMessages(initialSessionId),
  isLoading: false,
  sessionId: initialSessionId,
  conversations: getCachedConversationSummaries(),
  conversationsTotal: getCachedConversationSummaries().length,
  conversationsHasMore: false,
  outputMode: (safeGetItem('chat_output_mode', 'stream') as 'stream' | 'direct'),
  selectedModel: safeGetItem('chat_selected_model', ''),
  modelOptions: [],
  modelLoading: false,
  modelError: null,
  thinkingEnabled: false,
  thinkingDepth: 0,

  addMessage: (role, content, reasoning_content, id) => {
    const messageId = id || crypto.randomUUID()
    set((state) => ({
      messages: (() => {
        const nextMessages = [
          ...state.messages,
          {
            id: messageId,
            role,
            content,
            reasoning_content,
            timestamp: new Date(),
          },
        ]
        setCachedConversationMessages(state.sessionId, nextMessages)
        return nextMessages
      })(),
    }))
    return messageId
  },

  updateLastMessage: (content, reasoning_content) =>
    set((state) => {
      if (state.messages.length === 0) return state
      const lastMessage = state.messages[state.messages.length - 1]

      if (lastMessage.role === 'assistant') {
        // 创建新对象而非修改原对象，保持 Zustand 不可变性
        const updatedMessage = {
          ...lastMessage,
          content: lastMessage.content + content,
          reasoning_content: reasoning_content
            ? (lastMessage.reasoning_content || '') + reasoning_content
            : lastMessage.reasoning_content,
        }
        const newMessages = [...state.messages.slice(0, -1), updatedMessage]
        setCachedConversationMessages(state.sessionId, newMessages)
        return { messages: newMessages }
      }
      return state
    }),

  setMessages: (messages) =>
    set((state) => {
      setCachedConversationMessages(state.sessionId, messages)
      return { messages }
    }),

  loadCachedMessages: (sessionId) =>
    set({ messages: getCachedConversationMessages(sessionId) }),

  setLoading: (loading) => set({ isLoading: loading }),

  clearMessages: () =>
    set((state) => {
      setCachedConversationMessages(state.sessionId, [])
      return { messages: [] }
    }),

  setSessionId: (id) => {
    setActiveConversationId(id)
    set({ sessionId: id, messages: getCachedConversationMessages(id) })
  },

  setConversations: (items, total, hasMore) => {
    setCachedConversationSummaries(items)
    set({
      conversations: items,
      conversationsTotal: total ?? items.length,
      conversationsHasMore: hasMore ?? false,
    })
  },

  upsertConversation: (item) =>
    set((state) => {
      const existingIndex = state.conversations.findIndex((entry) => entry.session_id === item.session_id)
      const nextItems = [...state.conversations]
      if (existingIndex >= 0) {
        nextItems[existingIndex] = item
      } else {
        nextItems.unshift(item)
      }
      setCachedConversationSummaries(nextItems)
      return {
        conversations: nextItems,
        conversationsTotal: Math.max(state.conversationsTotal, nextItems.length),
      }
    }),

  removeConversation: (sessionId) =>
    set((state) => {
      const nextItems = state.conversations.filter((item) => item.session_id !== sessionId)
      deleteCachedConversationMessages(sessionId)
      setCachedConversationSummaries(nextItems)
      return {
        conversations: nextItems,
        conversationsTotal: Math.max(0, state.conversationsTotal - 1),
      }
    }),

  setOutputMode: (mode) => {
    set({ outputMode: mode })
    safeSetItem('chat_output_mode', mode)
  },

  setSelectedModel: (model) => {
    set({ selectedModel: model })
    safeSetItem('chat_selected_model', model)
  },

  setModelOptions: (options) => set({ modelOptions: options }),

  setModelLoading: (loading) => set({ modelLoading: loading }),

  setModelError: (error) => set({ modelError: error }),

  setThinkingEnabled: (enabled) => set({ thinkingEnabled: enabled }),
  setThinkingDepth: (depth) => set({ thinkingDepth: Math.max(0, Math.min(5, depth)) }),
}))
