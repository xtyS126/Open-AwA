import '@testing-library/jest-dom/vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatPage from '@/features/chat/ChatPage'
import { BrowserRouter } from 'react-router-dom'
import { useChatStore } from '@/features/chat/store/chatStore'

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

vi.mock('@/shared/events/billingEvents', () => ({
  dispatchBillingUsageUpdated: vi.fn(),
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    updateConfiguration: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

describe('ChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
    useChatStore.setState({
      messages: [],
      isLoading: false,
      sessionId: 'session-1',
      conversations: [buildConversationSummary('session-1')],
      conversationsTotal: 1,
      conversationsHasMore: false,
      outputMode: 'stream',
      selectedModel: 'openai:gpt-4o-mini',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
    })
  })

  const renderChatPage = async () => {
    render(<BrowserRouter><ChatPage /></BrowserRouter>)
    await waitFor(() => expect(apiMocks.listSessions).toHaveBeenCalled())
    await waitFor(() => expect(apiMocks.getHistory).toHaveBeenCalled())
  }

  it('renders without crashing', async () => {
    await renderChatPage()
    expect(screen.getByText('AI 助手')).toBeInTheDocument()
  })

  it('在流式结构化事件中展示悬浮任务面板并支持展开工具详情', async () => {
    apiMocks.sendMessageStream.mockImplementation(async (_message, _sessionId, _provider, _model, onEvent) => {
      onEvent({
        type: 'status',
        phase: 'planning',
        message: '正在生成执行计划',
      })
      onEvent({
        type: 'plan',
        plan: {
          intent: 'analyse',
          steps: [
            {
              step: 1,
              action: 'mcp_tool_call',
              purpose: '读取配置文件',
            },
          ],
          requires_confirmation: false,
        },
      })
      onEvent({
        type: 'task',
        task: {
          step: 1,
          action: 'mcp_tool_call',
          purpose: '读取配置文件',
          status: 'running',
        },
      })
      onEvent({
        type: 'tool',
        tool: {
          kind: 'mcp',
          name: 'filesystem/read_file',
          status: 'completed',
          detail: '已完成 filesystem/read_file',
        },
      })
      onEvent({
        type: 'chunk',
        content: '已经读取完成。',
        reasoning_content: '先规划，再调用工具。',
      })
      onEvent({
        type: 'usage',
        usage: {
          provider: 'openai',
          model: 'gpt-4o-mini',
          input_tokens: 120,
          output_tokens: 36,
          total_cost: 0.0123,
          currency: 'USD',
          duration_ms: 245,
        },
      })
    })

    await renderChatPage()
    fireEvent.change(screen.getByPlaceholderText('type your question...'), {
      target: { value: '帮我检查配置文件' },
    })
    const sendBtn = screen.getAllByRole('button').find(btn => btn.classList.contains('btn-primary'))!
    fireEvent.click(sendBtn)

    await waitFor(() => expect(apiMocks.sendMessageStream).toHaveBeenCalled())
    const stepTitles = await screen.findAllByText('读取配置文件')
    expect(stepTitles.length).toBeGreaterThan(0)
    expect(screen.getAllByText('mcp').length).toBeGreaterThan(0)
    expect(screen.getAllByText('filesystem/read_file').length).toBeGreaterThan(0)
    expect(screen.getByText('已经读取完成。')).toBeInTheDocument()
    expect(screen.getByText('先规划，再调用工具。')).toBeInTheDocument()
    expect(screen.getAllByText(/\$0\.0123/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/245ms/).length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: /工具与执行详情/i }))
    expect(await screen.findByText('工具调用')).toBeInTheDocument()
    expect(screen.getByText('已完成 filesystem/read_file')).toBeInTheDocument()
    expect(screen.getByText('模型')).toBeInTheDocument()
    expect(screen.getAllByText('gpt-4o-mini').length).toBeGreaterThan(0)
  })

  it('在收到流式阶段事件时展示实时状态文本', async () => {
    let continueStream: (() => void) | null = null
    apiMocks.sendMessageStream.mockImplementation(
      async (_message, _sessionId, _provider, _model, onEvent) => new Promise<void>((resolve) => {
        onEvent({
          type: 'status',
          phase: 'understanding_request',
          message: '正在分析你的问题',
        })
        continueStream = () => {
          onEvent({
            type: 'chunk',
            content: '分析完成',
            reasoning_content: '',
          })
          resolve()
        }
      })
    )

    await renderChatPage()
    fireEvent.change(screen.getByPlaceholderText('type your question...'), {
      target: { value: '请先显示阶段状态' },
    })
    const sendBtn = screen.getAllByRole('button').find(btn => btn.classList.contains('btn-primary'))!
    await act(async () => {
      fireEvent.click(sendBtn)
    })

    expect(await screen.findByText('正在分析你的问题...')).toBeInTheDocument()

    await act(async () => {
      continueStream?.()
    })

    expect(await screen.findByText('分析完成')).toBeInTheDocument()
  })

  it('在首次流式失败且尚未返回内容时自动重试一次', async () => {
    let attempt = 0
    apiMocks.sendMessageStream.mockImplementation(async (_message, _sessionId, _provider, _model, onEvent) => {
      attempt += 1
      if (attempt === 1) {
        throw new Error('Failed to fetch')
      }
      onEvent({
        type: 'chunk',
        content: '重试成功',
        reasoning_content: '',
      })
    })

    await renderChatPage()
    fireEvent.change(screen.getByPlaceholderText('type your question...'), {
      target: { value: '请在失败后自动重试' },
    })
    const sendBtn = screen.getAllByRole('button').find(btn => btn.classList.contains('btn-primary'))!
    await act(async () => {
      fireEvent.click(sendBtn)
    })

    await waitFor(() => expect(apiMocks.sendMessageStream).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByText('重试成功')).toBeInTheDocument())
    expect(screen.queryByText(/请求失败：Failed to fetch/)).not.toBeInTheDocument()
  })
})
