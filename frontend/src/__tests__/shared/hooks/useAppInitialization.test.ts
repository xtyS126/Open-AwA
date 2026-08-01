import '@testing-library/jest-dom/vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

vi.mock('@/shared/api/api', () => ({
  authAPI: {
    getMe: apiMocks.getMe,
  },
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

    renderHook(() => useAppInitialization())

    await waitFor(() => {
      expect(useAuthStore.getState().isInitialized).toBe(true)
    })

    expect(useAuthStore.getState().isSystemInitialized).toBeNull()
    expect(apiMocks.getMe).not.toHaveBeenCalled()
  })

  it('认证成功后调用 preloadModelOptions', async () => {
    // 模拟缓存了 API Key
    clientMocks.getCachedApiKey.mockReturnValue('cached-api-key')
    // 模拟 /auth/me 返回成功
    apiMocks.getMe.mockResolvedValue({
      data: { username: 'admin', nickname: '管理员' },
    })

    const { result } = renderHook(() => useAppInitialization())

    // 等待异步初始化完成
    await waitFor(() => {
      expect(useAuthStore.getState().isInitialized).toBe(true)
    })

    // 认证成功后应调用 preloadModelOptions
    expect(preloadMocks.preloadModelOptions).toHaveBeenCalledTimes(1)

    // 应设置认证状态
    expect(result.current).toBeUndefined() // hook 返回值无意义，仅用于触发 effect
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
    expect(useAuthStore.getState().user?.username).toBe('admin')
  })

  it('恢复缓存认证时等待 CSRF 初始化完成后再发布已认证状态', async () => {
    let resolveCsrf: (() => void) | undefined
    clientMocks.getCachedApiKey.mockReturnValue('cached-api-key')
    apiMocks.getMe.mockResolvedValue({ data: { username: 'admin' } })
    clientMocks.refreshCsrfToken.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveCsrf = resolve
    }))

    renderHook(() => useAppInitialization())

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
    // 模拟 preloadModelOptions reject 的极端情况（源码内部已 try/catch，
    // 但若因意外原因抛错，useAppInitialization 的外层 catch 会兜底，
    // 仍应设置 isInitialized=true 让应用进入可用状态，不卡死在初始化中）
    preloadMocks.preloadModelOptions.mockRejectedValueOnce(new Error('network error'))

    renderHook(() => useAppInitialization())

    // 即使 preloadModelOptions 抛错，初始化流程仍应完成（不卡死）
    await waitFor(() => {
      expect(useAuthStore.getState().isInitialized).toBe(true)
    }, { timeout: 2000 })

    // isInitialized=true 表示应用初始化流程完成，未被 preloadModelOptions 阻塞
    expect(useAuthStore.getState().isInitialized).toBe(true)
    // 由于 preloadModelOptions 抛错被外层 catch 捕获，isAuthenticated 为 false（兜底降级）
    // 但应用不会卡死，用户会看到登录页，可以重新登录
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })

  it('无缓存 apiKey 时不调用 preloadModelOptions', async () => {
    // 无缓存 API Key
    clientMocks.getCachedApiKey.mockReturnValue('')
    apiMocks.getMe.mockResolvedValue({
      data: { username: 'admin' },
    })

    renderHook(() => useAppInitialization())

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
