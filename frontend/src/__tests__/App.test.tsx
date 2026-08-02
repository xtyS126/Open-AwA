import '@testing-library/jest-dom/vitest'
import React, { StrictMode } from 'react'
import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '@/App'
import { router } from '@/router'
import { resetAppInitializationStateForTests } from '@/shared/hooks/useAppInitialization'
import { useAuthStore } from '@/shared/store/authStore'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useModelStore } from '@/features/chat/store/modelStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'
import { useThemeStore } from '@/shared/store/themeStore'

const authApiMocks = vi.hoisted(() => ({
  getMe: vi.fn().mockResolvedValue({ data: { username: 'admin' } }),
}))

const preferenceMocks = vi.hoisted(() => ({
  loadServerPreferences: vi.fn().mockResolvedValue(undefined),
  syncPreferenceToServer: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  systemAPI: { getInitStatus: vi.fn().mockResolvedValue({ data: { data: { initialized: true } } }) },
  pluginsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  weixinAPI: { getConfig: vi.fn().mockResolvedValue({ data: {} }) },
  authAPI: { getMe: authApiMocks.getMe },
  billingAPI: { getSummary: vi.fn().mockResolvedValue({ data: {} }) },
  chatAPI: { getHistory: vi.fn().mockResolvedValue({ data: [] }) },
  modelsAPI: { getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }) },
  memoryAPI: { getShortTerm: vi.fn().mockResolvedValue({ data: [] }), getLongTerm: vi.fn().mockResolvedValue({ data: [] }) },
  experiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  fileExperiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  skillsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  promptsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  logsAPI: { query: vi.fn().mockResolvedValue({ data: { records: [], total: 0 } }) },
  behaviorAPI: { getStats: vi.fn().mockResolvedValue({ data: {} }) },
  conversationAPI: { getRecordsPreview: vi.fn().mockResolvedValue({ data: { records: [], count: 0 } }) }
}))

vi.mock('@/shared/utils/preferenceSync', () => ({
  loadServerPreferences: preferenceMocks.loadServerPreferences,
  syncPreferenceToServer: preferenceMocks.syncPreferenceToServer,
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    updateConfiguration: vi.fn().mockResolvedValue({ data: {} })
  }
}))

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    resetAppInitializationStateForTests()
    useAuthStore.setState({
      user: null,
      token: null,
      isAuthenticated: false,
      isInitialized: false,
    })
    useSessionStore.setState({
      messages: [],
      isLoading: false,
      sessionId: 'default',
      conversations: [],
      conversationsTotal: 0,
      conversationsHasMore: false,
    })
    useModelStore.setState({
      selectedModel: '',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
    })
    usePreferenceStore.setState({
      outputMode: 'stream',
      thinkingEnabled: false,
      thinkingDepth: 0,
    })
    useThemeStore.setState({ theme: 'light' })
  })

  it('renders without crashing under StrictMode', async () => {
    render(
      <StrictMode>
        <App />
      </StrictMode>
    )

    await waitFor(() => {
      // App 初始化后 auth store 应完成初始化
      expect(useAuthStore.getState().isInitialized).toBe(true)
    }, { timeout: 5000 })
  })

  it('未登录根路径重定向到登录页后停止重复解析', async () => {
    await router.navigate({ to: '/', replace: true })
    let resolvedCount = 0
    let unsubscribe = () => {}
    const runawayNavigation = new Promise<never>((_resolve, reject) => {
      unsubscribe = router.subscribe('onResolved', () => {
        resolvedCount += 1
        if (resolvedCount > 5) {
          unsubscribe()
          reject(new Error(`路由重复解析超过上限：${resolvedCount}`))
        }
      })
    })

    render(
      <StrictMode>
        <App />
      </StrictMode>
    )

    try {
      await Promise.race([
        (async () => {
          await waitFor(() => {
            expect(useAuthStore.getState().isInitialized).toBe(true)
          }, { timeout: 5000 })
          await waitFor(() => {
            expect(router.state.location.pathname).toBe('/login')
          }, { timeout: 5000 })
          await new Promise((resolve) => window.setTimeout(resolve, 50))
        })(),
        runawayNavigation,
      ])
      expect(resolvedCount).toBeLessThanOrEqual(5)
    } finally {
      unsubscribe()
    }
  })
})
