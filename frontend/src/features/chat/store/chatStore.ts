import { create } from 'zustand'

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
  outputMode: (localStorage.getItem('chat_output_mode') as 'stream' | 'direct') || 'stream',
  selectedModel: localStorage.getItem('chat_selected_model') || '',
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
    localStorage.setItem('chat_output_mode', mode)
    set({ outputMode: mode })
  },

  setSelectedModel: (model) => {
    localStorage.setItem('chat_selected_model', model)
    set({ selectedModel: model })
  },

  setModelOptions: (options) => set({ modelOptions: options }),

  setModelLoading: (loading) => set({ modelLoading: loading }),

  setModelError: (error) => set({ modelError: error }),
}))
