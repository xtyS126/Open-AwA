import '@testing-library/jest-dom/vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterTestProvider as BrowserRouter } from '@/shared/routing/testing'
import ChatPage from '@/features/chat/ChatPage'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useModelStore } from '@/features/chat/store/modelStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'

const apiMocks = vi.hoisted(() => ({
  sendMessageStream: vi.fn(),
  sendMessage: vi.fn(),
  getHistory: vi.fn(),
  listSessions: vi.fn(),
  createSession: vi.fn(),
  renameSession: vi.fn(),
  deleteSession: vi.fn(),
  restoreSession: vi.fn(),
  batchDeleteSessions: vi.fn(),
}))

const taskRuntimeMocks = vi.hoisted(() => ({
  getAgent: vi.fn(),
  stopAgent: vi.fn(),
  getTranscript: vi.fn(),
}))

function buildConversationSummary(sessionId: string) {
  return {
    session_id: sessionId,
    user_id: 'user-1',
    title: '新对话',
    summary: '',
    last_message_preview: '',
    last_message_role: null,
    message_count: 0,
    created_at: '2026-04-19T00:00:00Z',
    updated_at: '2026-04-19T00:00:00Z',
    last_message_at: null,
    deleted_at: null,
    restored_at: null,
    purge_after: null,
    conversation_metadata: {},
  }
}

async function setViewportWidth(width: number) {
  await act(async () => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      writable: true,
      value: width,
    })
    window.dispatchEvent(new Event('resize'))
  })
}

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  weixinAPI: { getConfig: vi.fn().mockResolvedValue({ data: {} }) },
  authAPI: { getMe: vi.fn().mockResolvedValue({ data: {} }) },
  billingAPI: { getSummary: vi.fn().mockResolvedValue({ data: {} }) },
  chatAPI: {
    getHistory: apiMocks.getHistory,
    sendMessageStream: apiMocks.sendMessageStream,
    sendMessage: apiMocks.sendMessage,
  },
  conversationAPI: {
    listSessions: apiMocks.listSessions,
    createSession: apiMocks.createSession,
    renameSession: apiMocks.renameSession,
    deleteSession: apiMocks.deleteSession,
    restoreSession: apiMocks.restoreSession,
    batchDeleteSessions: apiMocks.batchDeleteSessions,
    getRecordsPreview: vi.fn().mockResolvedValue({ data: { records: [], count: 0 } }),
  },
  modelsAPI: { getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }) },
  memoryAPI: { getShortTerm: vi.fn().mockResolvedValue({ data: [] }), getLongTerm: vi.fn().mockResolvedValue({ data: [] }) },
  experiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  fileExperiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  skillsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  promptsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  logsAPI: { query: vi.fn().mockResolvedValue({ data: { records: [], total: 0 } }) },
  behaviorAPI: { getStats: vi.fn().mockResolvedValue({ data: {} }) },
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/shared/api/taskRuntimeApi', () => ({
  getAgent: taskRuntimeMocks.getAgent,
  stopAgent: taskRuntimeMocks.stopAgent,
  getTranscript: taskRuntimeMocks.getTranscript,
}))

vi.mock('@/shared/events/billingEvents', () => ({
  dispatchBillingUsageUpdated: vi.fn(),
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    updateConfiguration: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

describe('ChatPage responsive sidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    if (!HTMLElement.prototype.scrollIntoView) {
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
        value: vi.fn(),
        writable: true,
      })
    }

    apiMocks.listSessions.mockResolvedValue({
      data: {
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        has_more: false,
      },
    })
    apiMocks.createSession.mockResolvedValue({ data: buildConversationSummary('session-1') })
    apiMocks.renameSession.mockResolvedValue({ data: buildConversationSummary('session-1') })
    apiMocks.deleteSession.mockResolvedValue({ data: { ...buildConversationSummary('session-1'), deleted_at: '2026-04-20T00:00:00Z' } })
    apiMocks.restoreSession.mockResolvedValue({ data: buildConversationSummary('session-1') })
    apiMocks.batchDeleteSessions.mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 0, has_more: false } })
    apiMocks.getHistory.mockResolvedValue({ data: [] })
    taskRuntimeMocks.getAgent.mockResolvedValue({
      agent: {
        agent_id: 'agt-1',
        agent_type: 'planner',
        state: 'completed',
        run_mode: 'background',
        isolation_mode: 'inherit',
      },
    })
    taskRuntimeMocks.stopAgent.mockResolvedValue({ ok: true, agent_id: 'agt-1', status: 'stopped' })
    taskRuntimeMocks.getTranscript.mockResolvedValue({ agent_id: 'agt-1', transcript: [], entry_count: 0 })
    useSessionStore.setState({
      messages: [],
      isLoading: false,
      sessionId: 'session-1',
      conversations: [buildConversationSummary('session-1')],
      conversationsTotal: 1,
      conversationsHasMore: false,
    })
    useModelStore.setState({
      selectedModel: 'openai:gpt-4o-mini',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
    })
    usePreferenceStore.setState({
      outputMode: 'stream',
    })
  })

  it('closes on compact viewport and reopens on desktop resize', async () => {
    await setViewportWidth(1280)

    render(<BrowserRouter><ChatPage /></BrowserRouter>)

    await waitFor(() => expect(apiMocks.listSessions).toHaveBeenCalled())
    await waitFor(() => expect(apiMocks.getHistory).toHaveBeenCalled())

    const sidebar = screen.getByLabelText('聊天历史侧边栏')
    expect(sidebar.className).not.toMatch(/closed/)

    await setViewportWidth(768)
    await waitFor(() => expect(sidebar.className).toMatch(/closed/))

    await setViewportWidth(1280)
    await waitFor(() => expect(sidebar.className).not.toMatch(/closed/))
  })
})
