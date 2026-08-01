/**
 * 会话相关状态 Store（分域拆分自 chatStore）。
 *
 * 负责 messages、isLoading、sessionId、conversations、pinnedConversations 状态管理。
 * updateLastMessage 会跨域读取 preferenceStore 的 thinkingEnabled 状态。
 */
// [Fix] 消费方使用 shallow equalityFn（ChatPage useSessionStore(s, shallow)），
// zustand v4.5+ 要求此类 Store 改用 createWithEqualityFn 创建以消除弃用警告
import { createWithEqualityFn } from 'zustand/traditional'
import { safeGetItem } from '@/shared/utils/safeStorage'
import { persistPinnedConversations } from '@/features/chat/store/chatStoreEffects'
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
  /**
   * 会话列表版本号：跨标签页广播会话变更时自增，
   * useConversationHistory 监听该字段变化后重新加载会话列表。
   */
  conversationsVersion: number
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
  resetForLogout: () => void
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
  /**
   * 应用远程标签页广播的流式开始事件。
   * 仅当当前会话与事件会话一致时生效；若用户消息或助手消息已存在则跳过，避免重复。
   */
  applyRemoteStreamStart: (
    sessionId: string,
    messageId: string,
    userMessage: string
  ) => void
  /**
   * 应用远程标签页广播的流式 chunk 事件。
   * 仅当当前会话与事件会话一致时生效。
   * 注意：广播携带的是当前累计的完整内容（非增量），因此这里采用整体替换而非追加，
   * 避免节流丢帧导致的内容缺失或重复拼接。
   */
  applyRemoteStreamChunk: (
    sessionId: string,
    messageId: string,
    content: string,
    reasoning?: string
  ) => void
  /**
   * 应用远程标签页广播的流式结束事件。
   * 仅当当前会话与事件会话一致时生效；设置最终内容并清除加载状态。
   */
  applyRemoteStreamEnd: (
    sessionId: string,
    messageId: string,
    finalContent: string,
    finalReasoning?: string
  ) => void
  /**
   * 应用远程标签页广播的会话列表变更事件。
   * 仅自增 conversationsVersion，由 useConversationHistory 监听后重新加载。
   */
  applyRemoteConversationChange: () => void
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

export const useSessionStore = createWithEqualityFn<SessionState>((set, get) => ({
  // 消息为空，由 ChatPage 在路由进入时通过 loadMessages() 异步加载
  messages: [],
  isLoading: false,
  sessionId: initialSessionId,
  conversations: getConversationSummaries() as ConversationSessionSummary[],
  conversationsTotal: getConversationSummaries().length,
  conversationsHasMore: false,
  pinnedConversations: loadPinnedConversations(),
  conversationsVersion: 0,

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

  resetForLogout: () => {
    ++loadSequenceNumber
    setActiveSessionId('default')
    setConversationSummaries([])
    persistPinnedConversations([])
    set({
      messages: [],
      isLoading: false,
      sessionId: 'default',
      conversations: [],
      conversationsTotal: 0,
      conversationsHasMore: false,
      pinnedConversations: [],
      conversationsVersion: 0,
    })
  },

  // 将当前会话消息显式写入 IndexedDB（消息完成/会话切换/页面隐藏时调用）
  flushMessages: () => {
    const state = useSessionStore.getState()
    if (state.sessionId && state.sessionId !== 'default' && state.messages.length > 0) {
      void saveMessages(state.sessionId, state.messages)
    }
  },

  setSessionId: (id) => {
    setActiveSessionId(id)
    // 不再 set({ messages: [] }) 清空消息，保留旧消息直到新数据到达，
    // 避免 StrictMode dev 双 mount 或快速切换会话时出现空白闪烁。
    // IndexedDB 加载完成后由 loadSequenceNumber 防护再 set({ messages })。
    // 服务端历史（useChatConversationActions 的 loadHistory）到达后也会调用 setMessages，
    // 两条路径都受 loadSequenceNumber 与 cancelled 标志保护，不会出现脏数据。
    const seq = ++loadSequenceNumber
    set({ sessionId: id })
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

  applyRemoteStreamStart: (sessionId, messageId, userMessage) => {
    const state = get()
    // 仅当当前会话与事件会话一致时生效
    if (state.sessionId !== sessionId) return

    // 防重复：若助手消息已存在，说明 stream_start 已应用过，整体跳过
    const assistantExists = state.messages.some((msg) => msg.id === messageId)
    if (assistantExists) return

    // 防重复：若最后一条消息是内容相同的用户消息，跳过添加用户消息
    const lastMessage = state.messages[state.messages.length - 1]
    const userMessageExists =
      lastMessage && lastMessage.role === 'user' && lastMessage.content === userMessage

    const nextMessages: ChatMessage[] = [...state.messages]
    if (!userMessageExists) {
      nextMessages.push({
        id: crypto.randomUUID(),
        role: 'user',
        content: userMessage,
        timestamp: new Date(),
      })
    }
    // 追加空助手消息，后续 chunk/end 通过 messageId 更新
    nextMessages.push({
      id: messageId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
    })

    set({ messages: nextMessages, isLoading: true })
  },

  applyRemoteStreamChunk: (sessionId, messageId, content, reasoning) => {
    const state = get()
    if (state.sessionId !== sessionId) return

    // 广播携带的是当前累计的完整内容，采用整体替换避免节流丢帧导致的内容缺失或重复拼接
    set((current) => ({
      messages: current.messages.map((msg) =>
        msg.id === messageId && msg.role === 'assistant'
          ? {
              ...msg,
              content,
              ...(reasoning !== undefined ? { reasoning_content: reasoning } : {}),
            }
          : msg
      ),
    }))
  },

  applyRemoteStreamEnd: (sessionId, messageId, finalContent, finalReasoning) => {
    const state = get()
    if (state.sessionId !== sessionId) return

    set((current) => ({
      messages: current.messages.map((msg) =>
        msg.id === messageId && msg.role === 'assistant'
          ? {
              ...msg,
              content: finalContent,
              ...(finalReasoning !== undefined
                ? { reasoning_content: finalReasoning }
                : {}),
            }
          : msg
      ),
      isLoading: false,
    }))
  },

  applyRemoteConversationChange: () => {
    set((state) => ({
      conversationsVersion: (state.conversationsVersion || 0) + 1,
    }))
  },
}))
