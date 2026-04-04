import { create } from 'zustand'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

interface ChatState {
  messages: Message[]
  isLoading: boolean
  sessionId: string
  addMessage: (role: 'user' | 'assistant', content: string) => void
  setMessages: (messages: Message[]) => void
  setLoading: (loading: boolean) => void
  clearMessages: () => void
  setSessionId: (id: string) => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isLoading: false,
  sessionId: 'default',
  
  addMessage: (role, content) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: Date.now().toString(),
          role,
          content,
          timestamp: new Date(),
        },
      ],
    })),
  
  setMessages: (messages) => set({ messages }),
  
  setLoading: (loading) => set({ isLoading: loading }),
  
  clearMessages: () => set({ messages: [] }),
  
  setSessionId: (id) => set({ sessionId: id }),
}))
