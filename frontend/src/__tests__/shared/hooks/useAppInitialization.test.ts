import '@testing-library/jest-dom/vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// 使用 vi.hoisted 提前建立 mock 引用，避免循环依赖
const apiMocks = vi.hoisted(() => ({
  getMe: vi.fn(),
  getInitStatus: vi.fn(),
}))

const clientMocks = vi.hoisted(() => ({
  getCachedApiKey: vi.fn(() => ''),
  refreshCsrfToken: vi.fn(() => Promise.resolve()),
}))

const preferenceSyncMocks = vi.hoisted(() => ({
  loadServerPreferences: vi.fn(() => Promise.resolve()),
}))

const preloadMocks = vi.hoisted(() => ({
  preloadModelOptions: vi.fn(() => Promise.resolve()),
}))

vi.mock('@/shared/api/authApi', () => ({
  authAPI: {
    getMe: apiMocks.getMe,
  },
}))

vi.mock('@/shared/api/opsApi', () => ({
  systemAPI: {
    getInitStatus: apiMocks.getInitStatus,
  },
}))

vi.mock('@/shared/api/client', () => ({
  getCachedApiKey: clientMocks.getCachedApiKey,
  persistApiKey: vi.fn(),
  clearCachedApiKey: vi.fn(),
  refreshCsrfToken: clientMocks.refreshCsrfToken,
  setUnauthorizedHandler: vi.fn(),
}))

vi.mock('@/shared/utils/preferenceSync', () => ({
  loadServerPreferences: preferenceSyncMocks.loadServerPreferences,
}))

vi.mock('@/features/chat/utils/preloadModelOptions', () => ({
  preloadModelOptions: preloadMocks.preloadModelOptions,
}))

// 模拟 logger，避免测试输出噪声
vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}))

import { useAppInitialization, resetAppInitializationStateForTests } from '@/shared/hooks/useAppInitialization'
import { useAuthStore } from '@/shared/store/authStore'

/* 每个测试独立的 QueryClient 实例，避免缓存污染（useAppInitialization 已改用 useQuery） */
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
      },
    },
  })
}

function renderHookWithQueryClient<T>(hook: () => T) {
  const queryClient = createTestQueryClient()
  // 使用 createElement 避免 .ts 文件中 JSX 解析错误
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children)
  return renderHook(hook, { wrapper })
}

describe('useAppInitialization - 模型选项预加载', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.getInitStatus.mockResolvedValue({ data: { data: { initialized: true } } })
    // 重置模块级初始化缓存，避免跨用例污染
    resetAppInitializationStateForTests()
    // 重置 authStore
    useAuthStore.setState({ user: null, apiKey: null, isAuthenticated: false, isInitialized: false })
    // 清空 localStorage，避免 rehydrateStores 读取旧值
    window.localStorage.clear()
    window.sessionStorage.clear()
    clientMocks.refreshCsrfToken.mockResolvedValue(undefined)
  })

  it('无法确认初始化状态时不继续认证流程', async () => {
    clientMocks.getCachedApiKey.mockReturnValue('cached-api-key')
    apiMocks.getInitStatus.mockRejectedValueOnce(new Error('服务不可达'))

    renderHookWithQueryClient(() => useAppInitialization())

    await waitFor(() => {
      expect(useAuthStore.getState().isInitialized).toBe(true)
    })

    expect(useAuthStore.getState().isSystemInitialized).toBeNull()
    expect(apiMocks.getMe).not.toHaveBeenCalled()
  })

  it('认证成功后延迟调用 preloadModelOptions（不阻塞首屏）', async () => {
    // 模拟缓存了 API Key
    clientMocks.getCachedApiKey.mockReturnValue('cached-api-key')
    // 模拟 /auth/me 返回成功
    apiMocks.getMe.mockResolvedValue({
      data: { username: 'admin', nickname: '管理员' },
    })

    // preload 改为延迟动态导入执行（避免挤占首秒关键路径），用假定时器推进
    vi.useFakeTimers()
    try {
      renderHookWithQueryClient(() => useAppInitialization())

      // 推进异步初始化（微任务）与延迟定时器（1500ms）
      await vi.advanceTimersByTimeAsync(2000)

      // 初始化状态应立即发布（不被 preload 阻塞）
      expect(useAuthStore.getState().isInitialized).toBe(true)
      // 延迟后应调用 preloadModelOptions
      expect(preloadMocks.preloadModelOptions).toHaveBeenCalledTimes(1)
      // 应设置认证状态
      expect(useAuthStore.getState().isAuthenticated).toBe(true)
      expect(useAuthStore.getState().user?.username).toBe('admin')
    } finally {
      vi.useRealTimers()
    }
  })

  it('恢复缓存认证时等待 CSRF 初始化完成后再发布已认证状态', async () => {
    let resolveCsrf: (() => void) | undefined
    clientMocks.getCachedApiKey.mockReturnValue('cached-api-key')
    apiMocks.getMe.mockResolvedValue({ data: { username: 'admin' } })
    clientMocks.refreshCsrfToken.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveCsrf = resolve
    }))

    renderHookWithQueryClient(() => useAppInitialization())

    await waitFor(() => expect(clientMocks.refreshCsrfToken).toHaveBeenCalledTimes(1))
    expect(useAuthStore.getState().isAuthenticated).toBe(false)

    resolveCsrf?.()
    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(true))
  })

  it('preloadModelOptions 失败不阻塞登录流程（isInitialized 仍为 true）', async () => {
    clientMocks.getCachedApiKey.mockReturnValue('cached-api-key')
    apiMocks.getMe.mockResolvedValue({
      data: { username: 'admin' },
    })
    // 模拟 preloadModelOptions reject：preload 已改为延迟异步执行且与初始化流程解耦，
    // 其失败不应影响认证状态与初始化完成标志
    preloadMocks.preloadModelOptions.mockRejectedValueOnce(new Error('network error'))

    vi.useFakeTimers()
    try {
      renderHookWithQueryClient(() => useAppInitialization())

      // 推进异步初始化（微任务）与延迟定时器（1500ms）
      await vi.advanceTimersByTimeAsync(2000)

      // isInitialized=true 表示应用初始化流程完成，未被 preloadModelOptions 阻塞
      expect(useAuthStore.getState().isInitialized).toBe(true)
      // preload 失败与认证流程解耦：认证状态保持，不会被登出
      expect(useAuthStore.getState().isAuthenticated).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('无缓存 apiKey 时不调用 preloadModelOptions', async () => {
    // 无缓存 API Key
    clientMocks.getCachedApiKey.mockReturnValue('')
    apiMocks.getMe.mockResolvedValue({
      data: { username: 'admin' },
    })

    renderHookWithQueryClient(() => useAppInitialization())

    await waitFor(() => {
      expect(useAuthStore.getState().isInitialized).toBe(true)
    })

    // 无 API Key 直接返回未认证，不应调用 authAPI.getMe / preloadModelOptions
    expect(apiMocks.getMe).not.toHaveBeenCalled()
    expect(preloadMocks.preloadModelOptions).not.toHaveBeenCalled()
    // 应执行 logout（未认证）
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })
})
