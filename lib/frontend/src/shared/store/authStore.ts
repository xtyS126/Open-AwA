import { create } from 'zustand'

interface User {
  id?: string
  username: string
  nickname?: string | null
  avatar_url?: string | null
  email?: string | null
  phone?: string | null
  role?: string
}

interface AuthState {
  user: User | null
  apiKey: string | null
  isAuthenticated: boolean
  isInitialized: boolean
  /** 系统是否已完成首次部署初始化（owner 用户已创建） */
  isSystemInitialized: boolean | null
  setAuth: (user: User | null, apiKey: string | null) => void
  setInitialized: (initialized: boolean) => void
  setSystemInitialized: (initialized: boolean) => void
  logout: () => void
  /** 更新当前用户的部分字段（用于头像上传、昵称修改后即时反映） */
  updateUser: (partial: Partial<User>) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  apiKey: null,
  isAuthenticated: false,
  isInitialized: false,
  isSystemInitialized: null,

  setAuth: (user, apiKey) => {
    set({ user, apiKey, isAuthenticated: !!user })
  },

  setInitialized: (initialized) => set({ isInitialized: initialized }),

  setSystemInitialized: (initialized) => set({ isSystemInitialized: initialized }),

  logout: () => {
    set({ user: null, apiKey: null, isAuthenticated: false })
  },

  updateUser: (partial) => {
    set((state) => ({
      user: state.user ? { ...state.user, ...partial } : null,
    }))
  },
}))
