// [Fix] 消费方使用 shallow equalityFn，改用 createWithEqualityFn 消除 zustand 弃用警告
import { createWithEqualityFn } from 'zustand/traditional';
import { clearCachedApiKey, setUnauthorizedHandler } from '@/shared/api/client'
import { resetAppInitializationCache } from '@/shared/hooks/appInitializationCache'

// 登出清理注册表：各业务 store（chat/inbox 等）在模块加载时通过 registerLogoutHandler
// 注册自己的重置逻辑，authStore 登出时统一执行。
// 这样 authStore 无需静态 import 这些业务 store，避免把整条 chat 模块链
// （sessionStore/toolCallStore/inboxStore/inboxStream 及其依赖）拉入首屏关键路径
// （HAR 抓包证实：/assistant/context 首秒因此多加载约 8 个无关模块）。
const logoutHandlers = new Set<() => void>()

/**
 * 注册一个登出清理处理器。由各业务 store 在模块加载时调用。
 * 登出时 authStore 会执行所有已注册处理器，清除跨账号可见的业务状态。
 * 若某业务 store 从未加载（其状态不存在），则不会注册，也无需清理。
 */
export function registerLogoutHandler(handler: () => void): void {
  logoutHandlers.add(handler)
}

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
  /** APP 模式：尚未选择局域网后端，需进入服务器选择页 */
  needsServerSelection: boolean
  setAuth: (user: User | null, apiKey: string | null) => void
  setInitialized: (initialized: boolean) => void
  setSystemInitialized: (initialized: boolean | null) => void
  setNeedsServerSelection: (needs: boolean) => void
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
  needsServerSelection: false,

  setAuth: (user, apiKey) => {
    set({ user, apiKey, isAuthenticated: !!user })
  },

  setInitialized: (initialized) => set({ isInitialized: initialized }),

  setSystemInitialized: (initialized) => set({ isSystemInitialized: initialized }),

  setNeedsServerSelection: (needs) => set({ needsServerSelection: needs }),

  logout: () => {
    clearCachedApiKey()
    resetAppInitializationCache()
    // 执行所有已注册的业务 store 登出清理（chat/inbox 等）。
    // 注册表模式：authStore 不静态依赖业务 store，避免首屏加载整条 chat 模块链。
    logoutHandlers.forEach((handler) => handler())
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
