import '@testing-library/jest-dom/vitest'
import React, { StrictMode } from 'react'
import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '@/App'
import { resetAppInitializationStateForTests } from '@/shared/hooks/useAppInitialization'
import { useAuthStore } from '@/shared/store/authStore'
import { useChatStore } from '@/features/chat/store/chatStore'
import { useThemeStore } from '@/shared/store/themeStore'

const authApiMocks = vi.hoisted(() => ({
  getMe: vi.fn().mockResolvedValue({ data: { username: 'admin' } }),
}))

const preferenceMocks = vi.hoisted(() => ({
  loadServerPreferences: vi.fn().mockResolvedValue(undefined),
  syncPreferenceToServer: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
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
    useChatStore.setState({
      messages: [],
      isLoading: false,
      sessionId: 'default',
      conversations: [],
      conversationsTotal: 0,
      conversationsHasMore: false,
      outputMode: 'stream',
      selectedModel: '',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
      thinkingEnabled: false,
      thinkingDepth: 0,
    })
    useThemeStore.setState({ theme: 'light' })
  })

  it('initializes only once under StrictMode', async () => {
    render(
      <StrictMode>
        <App />
      </StrictMode>
    )

    await waitFor(() => {
      expect(useAuthStore.getState().isInitialized).toBe(true)
    })

    expect(authApiMocks.getMe).toHaveBeenCalledTimes(1)
    expect(preferenceMocks.loadServerPreferences).toHaveBeenCalledTimes(1)
  })
})
