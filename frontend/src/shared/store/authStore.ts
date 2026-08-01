// [Fix] 消费方使用 shallow equalityFn，改用 createWithEqualityFn 消除 zustand 弃用警告
import { createWithEqualityFn } from 'zustand/traditional';
import { clearCachedApiKey, setUnauthorizedHandler } from '@/shared/api/client'
import { resetAppInitializationCache } from '@/shared/hooks/appInitializationCache'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useModelStore } from '@/features/chat/store/modelStore'
import { useToolCallStore } from '@/features/chat/store/toolCallStore'
import { useInboxStore } from '@/features/inbox/store/inboxStore'
import { resetInboxStreamForLogout } from '@/features/inbox/inboxStream'

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
  setSystemInitialized: (initialized: boolean | null) => void
  logout: () => void
  /** 更新当前用户的部分字段（用于头像上传、昵称修改后即时反映） */
  updateUser: (partial: Partial<User>) => void
}

export const useAuthStore = createWithEqualityFn<AuthState>((set) => ({
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
    clearCachedApiKey()
    resetAppInitializationCache()
    useSessionStore.getState().resetForLogout()
    useModelStore.getState().resetForLogout()
    useToolCallStore.getState().resetActiveToolCalls()
    useInboxStore.getState().resetForLogout()
    resetInboxStreamForLogout()
    set({ user: null, apiKey: null, isAuthenticated: false })
  },

  updateUser: (partial) => {
    set((state) => ({
      user: state.user ? { ...state.user, ...partial } : null,
    }))
  },
}))

setUnauthorizedHandler(() => {
  useAuthStore.getState().logout()
})
