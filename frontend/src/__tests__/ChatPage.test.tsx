import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import ChatPage from '@/features/chat/ChatPage'
import { BrowserRouter } from 'react-router-dom'
import { useChatStore } from '@/features/chat/store/chatStore'

if (!HTMLElement.prototype.scrollIntoView) {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    value: () => {},
    writable: true
  })
}

const apiMocks = vi.hoisted(() => ({
  sendMessageStream: vi.fn(),
  sendMessage: vi.fn(),
  getHistory: vi.fn(),
  listSessions: vi.fn(),
  createSession: vi.fn(),
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

vi.mock('@/shared/api/api', () => ({
  chatAPI: {
    getHistory: apiMocks.getHistory,
    sendMessageStream: apiMocks.sendMessageStream,
    sendMessage: apiMocks.sendMessage,
  },
  conversationAPI: {
    listSessions: apiMocks.listSessions,
    createSession: apiMocks.createSession,
    renameSession: vi.fn(),
    deleteSession: vi.fn(),
    restoreSession: vi.fn(),
    batchDeleteSessions: vi.fn(),
    getRecordsPreview: vi.fn().mockResolvedValue({ data: { records: [], count: 0 } }),
  },
  pluginsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  weixinAPI: { getConfig: vi.fn().mockResolvedValue({ data: {} }) },
  authAPI: { getMe: vi.fn().mockResolvedValue({ data: {} }) },
  billingAPI: { getSummary: vi.fn().mockResolvedValue({ data: {} }) },
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
    error: vi.fn(),
    warning: vi.fn(),
  }
}))

vi.mock('@/shared/events/billingEvents', () => ({
  dispatchBillingUsageUpdated: vi.fn(),
}))

describe('ChatPage', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    apiMocks.getHistory.mockResolvedValue({ data: [] })
    apiMocks.listSessions.mockResolvedValue({
      data: {
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        has_more: false,
      },
    })
    apiMocks.createSession.mockResolvedValue({ data: buildConversationSummary('session-basic') })
    useChatStore.setState({
      messages: [],
      isLoading: false,
      sessionId: 'session-basic',
      conversations: [buildConversationSummary('session-basic')],
      conversationsTotal: 1,
      conversationsHasMore: false,
      outputMode: 'stream',
      selectedModel: 'openai:gpt-4',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  const renderChatPage = async () => {
    render(<BrowserRouter><ChatPage /></BrowserRouter>)
    await waitFor(() => expect(apiMocks.listSessions).toHaveBeenCalled())
    await waitFor(() => expect(apiMocks.getHistory).toHaveBeenCalled())
  }

  describe('Basic Rendering', () => {
    it('should render chat page with header', async () => {
      await renderChatPage()
      expect(screen.getByText('AI 助手')).toBeInTheDocument()
    })

    it('should render output mode selector', async () => {
      await renderChatPage()
      expect(screen.getByText('流式传输')).toBeInTheDocument()
      expect(screen.getByText('直接输出')).toBeInTheDocument()
    })

    it('should render new conversation button', async () => {
      await renderChatPage()
      expect(screen.getAllByRole('button', { name: '新对话' })[0]).toBeInTheDocument()
    })

    it('should render empty state message', async () => {
      await renderChatPage()
      expect(screen.getByText('Hello! How can I help you?')).toBeInTheDocument()
    })

    it('should render input field and send button', async () => {
      await renderChatPage()
      expect(screen.getByPlaceholderText('type your question...')).toBeInTheDocument()
      // 发送按钮现在是图标，通过 role 查找
      const buttons = screen.getAllByRole('button')
      expect(buttons.length).toBeGreaterThan(0)
    })
  })

  describe('Model Selector Migration', () => {
    it('should not render model dropdown (migrated to settings)', async () => {
      await renderChatPage()
      // 聊天页当前仅保留输出模式和历史排序两个选择器，不再提供模型下拉框
      const selects = screen.getAllByRole('combobox')
      expect(selects.length).toBe(2)
    })

    it('should display current model name from global store', async () => {
      await renderChatPage()
      // 当前选中模型名称应在 header 以紧凑标签显示
      expect(screen.getByText('gpt-4')).toBeInTheDocument()
    })
  })

  describe('User Interaction', () => {
    it('should create a conversation when clicking new conversation button', async () => {
      await renderChatPage()
      fireEvent.click(screen.getAllByRole('button', { name: '新对话' })[0])
      await waitFor(() => expect(apiMocks.createSession).toHaveBeenCalled())
    })

    it('should disable send button when input is empty', async () => {
      await renderChatPage()
      // 发送按钮是 btn-primary 样式的按钮
      const buttons = screen.getAllByRole('button')
      const sendBtn = buttons.find(btn => btn.classList.contains('btn-primary'))
      expect(sendBtn).toBeDefined()
      expect(sendBtn).toBeDisabled()
    })
  })
})
