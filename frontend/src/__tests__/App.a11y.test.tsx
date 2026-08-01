/**
 * App 全局无障碍自动化测试 — 使用 axe-core 检测 WCAG 违规。
 */
import '@testing-library/jest-dom/vitest'
import React, { StrictMode } from 'react'
import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import App from '@/App'
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

describe('App 全局无障碍 (axe-core)', () => {
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

  it('未登录状态下渲染无 WCAG 违规', async () => {
    const { container } = render(
      <StrictMode>
        <App />
      </StrictMode>
    )

    await waitFor(() => {
      expect(useAuthStore.getState().isInitialized).toBe(true)
    }, { timeout: 5000 })

    // jsdom 不实现 Canvas，颜色对比度由真实浏览器验收覆盖。
    const results = await axe.run(container, {
      rules: {
        'color-contrast': { enabled: false },
      },
    })
    const violations = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious'
    )
    if (violations.length > 0) {
      const messages = violations.map(
        (v) => `[${v.impact}] ${v.help}: ${v.nodes.map((n) => n.html).join('; ')}`
      )
      throw new Error(`WCAG violations found:\n${messages.join('\n')}`)
    }
  })
})
