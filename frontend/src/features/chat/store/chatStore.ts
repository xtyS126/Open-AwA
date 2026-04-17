import { create } from 'zustand'
import { safeGetItem, safeSetItem } from '@/shared/utils/safeStorage'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning_content?: string
  timestamp: Date
}

// 模型配置项，用于全局模型选择
export interface ModelOption {
  id: string
  provider: string
  model: string
  display_name: string
}

interface ChatState {
  messages: Message[]
  isLoading: boolean
  sessionId: string
  outputMode: 'stream' | 'direct'
  // 全局模型选择状态
  selectedModel: string
  modelOptions: ModelOption[]
  modelLoading: boolean
  modelError: string | null
  addMessage: (role: 'user' | 'assistant', content: string, reasoning_content?: string) => void
  updateLastMessage: (content: string, reasoning_content?: string) => void
  setMessages: (messages: Message[]) => void
  setLoading: (loading: boolean) => void
  clearMessages: () => void
  setSessionId: (id: string) => void
  setOutputMode: (mode: 'stream' | 'direct') => void
  setSelectedModel: (model: string) => void
  setModelOptions: (options: ModelOption[]) => void
  setModelLoading: (loading: boolean) => void
  setModelError: (error: string | null) => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isLoading: false,
  sessionId: 'default',
  outputMode: (safeGetItem('chat_output_mode', 'stream') as 'stream' | 'direct'),
  selectedModel: safeGetItem('chat_selected_model', ''),
  modelOptions: [],
  modelLoading: false,
  modelError: null,
  
  addMessage: (role, content, reasoning_content) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: crypto.randomUUID(),
          role,
          content,
          reasoning_content,
          timestamp: new Date(),
        },
      ],
    })),
  
  updateLastMessage: (content, reasoning_content) =>
    set((state) => {
      if (state.messages.length === 0) return state
      const newMessages = [...state.messages]
      const lastMessage = newMessages[newMessages.length - 1]
      
      if (lastMessage.role === 'assistant') {
        lastMessage.content += content
        if (reasoning_content) {
          lastMessage.reasoning_content = (lastMessage.reasoning_content || '') + reasoning_content
        }
      }
      return { messages: newMessages }
    }),
  
  setMessages: (messages) => set({ messages }),
  
  setLoading: (loading) => set({ isLoading: loading }),
  
  clearMessages: () => set({ messages: [] }),
  
  setSessionId: (id) => set({ sessionId: id }),

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
}))
