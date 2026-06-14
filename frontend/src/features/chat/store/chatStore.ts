import { create } from 'zustand'
import { safeGetItem, safeSetItem } from '@/shared/utils/safeStorage'
import { syncPreferenceToServer } from '@/shared/utils/preferenceSync'
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

// 模型配置项，用于全局模型选择
export interface ModelOption {
  id: string
  provider: string
  model: string
  display_name: string
}

interface PreferenceMutationOptions {
  syncToServer?: boolean
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
  /** 当前进行中的工具调用 ID 列表 */
  activeToolCalls: string[]
  setActiveToolCalls: (toolIds: string[]) => void
  addActiveToolCall: (toolId: string) => void
  removeActiveToolCall: (toolId: string) => void
  resetActiveToolCalls: () => void
  addMessage: (role: 'user' | 'assistant', content: string, reasoning_content?: string, id?: string, isError?: boolean) => string
  updateLastMessage: (content: string, reasoning_content?: string) => void
  setMessages: (messages: ChatMessage[]) => void
  updateMessage: (messageId: string, updater: (msg: ChatMessage) => ChatMessage) => void
  loadCachedMessages: (sessionId: string) => void
  /** P1: 将当前会话消息显式刷入 IndexedDB（消息完成/会话切换时调用） */
  flushMessages: () => void
  setLoading: (loading: boolean) => void
  clearMessages: () => void
  setSessionId: (id: string) => void
  setConversations: (items: ConversationSessionSummary[], total?: number, hasMore?: boolean) => void
  upsertConversation: (item: ConversationSessionSummary) => void
  removeConversation: (sessionId: string) => void
  setOutputMode: (mode: 'stream' | 'direct', options?: PreferenceMutationOptions) => void
  setSelectedModel: (model: string, options?: PreferenceMutationOptions) => void
  setModelOptions: (options: ModelOption[]) => void
  setModelLoading: (loading: boolean) => void
  setModelError: (error: string | null) => void
  setThinkingEnabled: (enabled: boolean, options?: PreferenceMutationOptions) => void
  setThinkingDepth: (depth: number, options?: PreferenceMutationOptions) => void
  /** 固定的对话历史 ID 列表 */
  pinnedConversations: string[]
  pinConversation: (sessionId: string) => void
  unpinConversation: (sessionId: string) => void
}

const initialSessionId = getActiveSessionId() || 'default'

const initialSelectedModel = safeGetItem('chat_selected_model', '')
const isInitialReasoner = initialSelectedModel.toLowerCase().includes('reasoner') || initialSelectedModel.toLowerCase().includes('r1') || initialSelectedModel.toLowerCase().includes('o1') || initialSelectedModel.toLowerCase().includes('o3')

/** 加载请求序列号，用于防止异步加载竞态：只有最新请求的结果才会写入 state */
let loadSequenceNumber = 0

export const useChatStore = create<ChatState>((set) => ({
  // P1: 消息为空，由 ChatPage 在路由进入时通过 loadMessages() 异步加载
  messages: [],
  isLoading: false,
  sessionId: initialSessionId,
  conversations: getConversationSummaries() as ConversationSessionSummary[],
  conversationsTotal: getConversationSummaries().length,
  conversationsHasMore: false,
  outputMode: (safeGetItem('chat_output_mode', 'stream') as 'stream' | 'direct'),
  selectedModel: initialSelectedModel,
  modelOptions: [],
  modelLoading: false,
  modelError: null,
  thinkingEnabled: safeGetItem('chat_thinking_enabled', isInitialReasoner ? 'true' : 'false') === 'true',
  thinkingDepth: Number(safeGetItem('chat_thinking_depth', '0')) || 0,
  activeToolCalls: [],

  addMessage: (role, content, reasoning_content, id, isError) => {
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
            ...(isError ? { isError: true } : {}),
          },
        ]
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
          reasoning_content: (state.thinkingEnabled && reasoning_content)
            ? (lastMessage.reasoning_content || '') + reasoning_content
            : lastMessage.reasoning_content,
        }
        const newMessages = [...state.messages.slice(0, -1), updatedMessage]
        return { messages: newMessages }
      }
      return state
    }),

  setMessages: (messages) => set({ messages }),

  updateMessage: (messageId: string, updater: (msg: ChatMessage) => ChatMessage) =>
    set((state) => {
      const nextMessages = state.messages.map((msg) =>
        msg.id === messageId ? updater(msg) : msg
      )
      return { messages: nextMessages }
    }),

  loadCachedMessages: (sessionId) => {
    // P1: 异步加载由 ChatPage 处理，这里同步设为空然后由调用方异步填充
    const seq = ++loadSequenceNumber
    set({ messages: [] })
    loadMessages(sessionId).then((msgs) => {
      // 仅当此请求仍为最新时才写入 state，防止竞态
      if (seq === loadSequenceNumber) {
        const currentId = useChatStore.getState().sessionId
        if (currentId === sessionId && Array.isArray(msgs) && msgs.length > 0) {
          set({ messages: msgs as ChatMessage[] })
        }
      }
    })
  },

  setLoading: (loading) => set({ isLoading: loading }),

  clearMessages: () => set({ messages: [] }),

  // P1: 将当前会话消息显式写入 IndexedDB（消息完成/会话切换/页面隐藏时调用）
  flushMessages: () => {
    const state = useChatStore.getState()
    if (state.sessionId && state.sessionId !== 'default' && state.messages.length > 0) {
      saveMessages(state.sessionId, state.messages)
    }
  },

  setSessionId: (id) => {
    setActiveSessionId(id)
    // P1: 先设空，异步加载
    const seq = ++loadSequenceNumber
    set({ sessionId: id, messages: [] })
    loadMessages(id).then((msgs) => {
      // 仅当此请求仍为最新时才写入 state，防止竞态
      if (seq === loadSequenceNumber) {
        const currentId = useChatStore.getState().sessionId
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
      const existingIndex = state.conversations.findIndex((entry) => entry.session_id === item.session_id)
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
      const nextItems = state.conversations.filter((item) => item.session_id !== sessionId)
      removeMessages(sessionId)
      setConversationSummaries(nextItems)
      return {
        conversations: nextItems,
        conversationsTotal: Math.max(0, state.conversationsTotal - 1),
      }
    }),

  setOutputMode: (mode, options) => {
    set({ outputMode: mode })
    safeSetItem('chat_output_mode', mode)
    if (options?.syncToServer !== false) {
      syncPreferenceToServer('outputMode', mode)
    }
  },

  setSelectedModel: (model, options) => {
    set({ selectedModel: model })
    safeSetItem('chat_selected_model', model)
    if (options?.syncToServer !== false) {
      syncPreferenceToServer('selectedModel', model)
    }
    // 如果选择了推理模型，自动开启思考模式（仅当用户未显式关闭时）
    const isReasoner = model.toLowerCase().includes('reasoner') || model.toLowerCase().includes('r1') || model.toLowerCase().includes('o1') || model.toLowerCase().includes('o3')
    if (isReasoner && safeGetItem('chat_thinking_enabled', '') !== 'false') {
      set({ thinkingEnabled: true })
      safeSetItem('chat_thinking_enabled', 'true')
    }
  },

  setModelOptions: (options) => set({ modelOptions: options }),

  setModelLoading: (loading) => set({ modelLoading: loading }),

  setModelError: (error) => set({ modelError: error }),

  setThinkingEnabled: (enabled, options) => {
    set({ thinkingEnabled: enabled })
    safeSetItem('chat_thinking_enabled', enabled ? 'true' : 'false')
    if (options?.syncToServer !== false) {
      syncPreferenceToServer('thinkingEnabled', enabled)
    }
  },
  setThinkingDepth: (depth, options) => {
    const validDepth = Math.max(0, Math.min(5, depth))
    set({ thinkingDepth: validDepth })
    safeSetItem('chat_thinking_depth', String(validDepth))
    if (options?.syncToServer !== false) {
      syncPreferenceToServer('thinkingDepth', validDepth)
    }
  },

  setActiveToolCalls: (toolIds) => set({ activeToolCalls: toolIds }),
  addActiveToolCall: (toolId) => set((state) => ({
    activeToolCalls: state.activeToolCalls.includes(toolId)
      ? state.activeToolCalls
      : [...state.activeToolCalls, toolId]
  })),
  removeActiveToolCall: (toolId) => set((state) => ({
    activeToolCalls: state.activeToolCalls.filter(id => id !== toolId)
  })),
  resetActiveToolCalls: () => set({ activeToolCalls: [] }),

  pinnedConversations: (() => {
    try {
      const stored = safeGetItem('chat_pinned_conversations', '[]');
      return JSON.parse(stored) as string[];
    } catch { return []; }
  })(),

  pinConversation: (sessionId) =>
    set((state) => {
      if (state.pinnedConversations.includes(sessionId)) return state;
      if (state.pinnedConversations.length >= 10) return state;
      const next = [sessionId, ...state.pinnedConversations];
      safeSetItem('chat_pinned_conversations', JSON.stringify(next));
      return { pinnedConversations: next };
    }),

  unpinConversation: (sessionId) =>
    set((state) => {
      const next = state.pinnedConversations.filter((id) => id !== sessionId);
      safeSetItem('chat_pinned_conversations', JSON.stringify(next));
      return { pinnedConversations: next };
    }),
}))
