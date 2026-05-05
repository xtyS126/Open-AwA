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

describe('ChatPage', () => {
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
        type: 'chunk',
        content: '',
        reasoning_content: '先规划，再调用工具。',
      })
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
        reasoning_content: '',
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
    fireEvent.click(await screen.findByText(/思维链/))
    const stepTitles = await screen.findAllByText('读取配置文件')
    expect(stepTitles.length).toBeGreaterThan(0)
    expect(screen.getAllByText('filesystem/read_file').length).toBeGreaterThan(0)
    expect(screen.getByText('已经读取完成。')).toBeInTheDocument()
    expect(screen.getByText('先规划，再调用工具。')).toBeInTheDocument()
    expect(screen.getByText('工具调用')).toBeInTheDocument()
    expect(screen.getByText('用量信息')).toBeInTheDocument()
    expect(screen.getByText(/\$0\.0123/)).toBeInTheDocument()
    expect(screen.getByText(/245ms/)).toBeInTheDocument()
  })

  it('为后台子代理建立独立同步，并在全部结束后一次性拉取 transcript', async () => {
    const streamMessages: string[] = []
    const continuationPayloads: Array<Record<string, unknown> | undefined> = []

    taskRuntimeMocks.getAgent
      .mockResolvedValueOnce({
        agent: {
          agent_id: 'agt-1',
          agent_type: 'planner',
          state: 'completed',
          run_mode: 'background',
          isolation_mode: 'inherit',
          summary: '规划完成',
        },
      })
      .mockResolvedValueOnce({
        agent: {
          agent_id: 'agt-2',
          agent_type: 'coder',
          state: 'completed',
          run_mode: 'background',
          isolation_mode: 'inherit',
          summary: '编码完成',
        },
      })

    taskRuntimeMocks.getTranscript
      .mockResolvedValueOnce({
        agent_id: 'agt-1',
        transcript: [{ message: '子代理一完整输出' }],
        entry_count: 1,
      })
      .mockResolvedValueOnce({
        agent_id: 'agt-2',
        transcript: [{ message: '子代理二完整输出' }],
        entry_count: 1,
      })

    apiMocks.sendMessageStream.mockImplementation(async (message, _sessionId, _provider, _model, onEvent, _onError, _requestOptions, executionOptions) => {
      streamMessages.push(String(message))
      continuationPayloads.push((executionOptions as { continuation?: Record<string, unknown> } | undefined)?.continuation)

      if (streamMessages.length === 1) {
        onEvent({
          type: 'chunk',
          content: '',
          reasoning_content: '准备分派两个子代理。',
        })
        onEvent({
          type: 'subagent_start',
          agent_id: 'agt-1',
          agent_type: 'planner',
          description: '规划任务',
        })
        onEvent({
          type: 'subagent_start',
          agent_id: 'agt-2',
          agent_type: 'coder',
          description: '编码任务',
        })
        onEvent({
          type: 'status',
          phase: 'waiting_subagents',
          message: '子代理已创建，等待运行结果',
        })
        return
      }

      onEvent({
        type: 'chunk',
        content: '主代理继续完成。',
        reasoning_content: '',
      })
    })

    await renderChatPage()
    fireEvent.change(screen.getByPlaceholderText('type your question...'), {
      target: { value: '执行两个子任务' },
    })
    const sendBtn = screen.getAllByRole('button').find(btn => btn.classList.contains('btn-primary'))!
    fireEvent.click(sendBtn)

    await waitFor(() => expect(apiMocks.sendMessageStream).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText(/思维链/)).toBeInTheDocument())
    await waitFor(() => expect(taskRuntimeMocks.getAgent).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(taskRuntimeMocks.getTranscript).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(apiMocks.sendMessageStream).toHaveBeenCalledTimes(2))
    expect(taskRuntimeMocks.getAgent).toHaveBeenNthCalledWith(1, 'agt-1')
    expect(taskRuntimeMocks.getAgent).toHaveBeenNthCalledWith(2, 'agt-2')
    expect(taskRuntimeMocks.getTranscript).toHaveBeenNthCalledWith(1, 'agt-1')
    expect(taskRuntimeMocks.getTranscript).toHaveBeenNthCalledWith(2, 'agt-2')
    expect(streamMessages[1]).toContain('请基于刚刚完成的子代理输出继续完成上一轮任务')
    expect(continuationPayloads[1]).toEqual({
      source: 'subagent',
      aggregated_context: 'Subagent 子代理: planner: 子代理一完整输出\n\nSubagent 子代理: coder: 子代理二完整输出',
      merge_with_last_assistant: true,
    })
    expect(screen.queryByText('请基于刚刚完成的子代理输出继续完成上一轮任务，并直接给出后续分析或最终答复。')).not.toBeInTheDocument()
    expect(screen.getByText('主代理继续完成。')).toBeInTheDocument()
  })

  it('遇到伪子代理 id 时只使用回退日志聚合，不请求 transcript', async () => {
    const continuationPayloads: Array<Record<string, unknown> | undefined> = []

    apiMocks.sendMessageStream.mockImplementation(async (_message, _sessionId, _provider, _model, onEvent, _onError, _requestOptions, executionOptions) => {
      continuationPayloads.push((executionOptions as { continuation?: Record<string, unknown> } | undefined)?.continuation)

      if (continuationPayloads.length === 1) {
        onEvent({
          type: 'subagent_start',
          agent_id: 'sub_deadbeef',
          agent_type: 'planner',
          description: '规划任务',
        })
        onEvent({
          type: 'agent_message',
          agent_id: 'sub_deadbeef',
          agent_type: 'planner',
          message: '回退日志输出',
        })
        onEvent({
          type: 'subagent_stop',
          agent_id: 'sub_deadbeef',
          agent_type: 'planner',
          state: 'completed',
          summary: '规划完成',
        })
        return
      }

      onEvent({
        type: 'chunk',
        content: '续流完成。',
        reasoning_content: '',
      })
    })

    await renderChatPage()
    fireEvent.change(screen.getByPlaceholderText('type your question...'), {
      target: { value: '执行一个伪子任务' },
    })
    const sendBtn = screen.getAllByRole('button').find(btn => btn.classList.contains('btn-primary'))!
    fireEvent.click(sendBtn)

    await waitFor(() => expect(apiMocks.sendMessageStream).toHaveBeenCalledTimes(2))
    expect(taskRuntimeMocks.getTranscript).not.toHaveBeenCalled()
    expect(continuationPayloads[1]).toEqual({
      source: 'subagent',
      aggregated_context: 'Subagent 子代理: planner: 规划任务\n回退日志输出\n规划完成',
      merge_with_last_assistant: true,
    })
    expect(screen.getByText('续流完成。')).toBeInTheDocument()
  })

  it('前台子代理事件流不触发 runtime 轮询并直接渲染摘要', async () => {
    apiMocks.sendMessageStream.mockImplementation(async (_message, _sessionId, _provider, _model, onEvent) => {
      onEvent({
        type: 'tool',
        tool: {
          id: 'call-subagent-1',
          kind: 'task',
          name: 'task_spawn_agent',
          status: 'running',
          detail: '前台子代理执行中',
        },
      })
      onEvent({
        type: 'subagent_start',
        agent_id: 'agt-foreground-1',
        agent_type: 'planner',
        description: '前台规划任务',
        run_mode: 'foreground',
      })
      onEvent({
        type: 'agent_message',
        agent_id: 'agt-foreground-1',
        agent_type: 'planner',
        message: '子代理实时输出',
      })
      onEvent({
        type: 'subagent_stop',
        agent_id: 'agt-foreground-1',
        agent_type: 'planner',
        state: 'completed',
        summary: '子代理摘要',
        run_mode: 'foreground',
      })
      onEvent({
        type: 'tool',
        tool: {
          id: 'call-subagent-1',
          kind: 'task',
          name: 'task_spawn_agent',
          status: 'completed',
          detail: '子代理摘要',
          output: {
            agent_id: 'agt-foreground-1',
            run_mode: 'foreground',
            summary: '子代理摘要',
          },
        },
      })
      onEvent({
        type: 'chunk',
        content: '主代理完成回复。',
        reasoning_content: '',
      })
    })

    await renderChatPage()
    fireEvent.change(screen.getByPlaceholderText('type your question...'), {
      target: { value: '执行一个前台子任务' },
    })
    const sendBtn = screen.getAllByRole('button').find(btn => btn.classList.contains('btn-primary'))!
    fireEvent.click(sendBtn)

    await waitFor(() => expect(apiMocks.sendMessageStream).toHaveBeenCalled())
    expect(taskRuntimeMocks.getAgent).not.toHaveBeenCalled()
    expect(taskRuntimeMocks.getTranscript).not.toHaveBeenCalled()

    fireEvent.click(await screen.findByText(/思维链/))
    expect(await screen.findByText('子代理执行')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('子代理摘要').length).toBeGreaterThan(0))
    expect(screen.getByText('主代理完成回复。')).toBeInTheDocument()
  })

  it('按回复边界拆分多轮思维链与回复段', async () => {
    apiMocks.sendMessageStream.mockImplementation(async (_message, _sessionId, _provider, _model, onEvent) => {
      onEvent({
        type: 'chunk',
        content: '',
        reasoning_content: '先思考第一轮。',
      })
      onEvent({
        type: 'tool',
        tool: {
          id: 'tool-1',
          kind: 'mcp',
          name: 'filesystem/read_file',
          status: 'completed',
          detail: '读取完成',
        },
      })
      onEvent({
        type: 'chunk',
        content: '第一轮回复。',
        reasoning_content: '',
      })
      onEvent({
        type: 'chunk',
        content: '',
        reasoning_content: '继续思考第二轮。',
      })
      onEvent({
        type: 'tool',
        tool: {
          id: 'tool-2',
          kind: 'mcp',
          name: 'filesystem/list_dir',
          status: 'completed',
          detail: '列举完成',
        },
      })
      onEvent({
        type: 'chunk',
        content: '第二轮回复-A',
        reasoning_content: '',
      })
      onEvent({
        type: 'chunk',
        content: '第二轮回复-B',
        reasoning_content: '',
      })
    })

    await renderChatPage()
    fireEvent.change(screen.getByPlaceholderText('type your question...'), {
      target: { value: '请演示多轮工具调用' },
    })
    const sendBtn = screen.getAllByRole('button').find(btn => btn.classList.contains('btn-primary'))!
    fireEvent.click(sendBtn)

    await waitFor(() => expect(apiMocks.sendMessageStream).toHaveBeenCalled())
    const thoughtHeaders = await screen.findAllByText(/思维链/)
    thoughtHeaders.forEach((header) => {
      fireEvent.click(header)
    })
    expect(await screen.findByText('先思考第一轮。')).toBeInTheDocument()
    expect(screen.getByText('第一轮回复。')).toBeInTheDocument()
    expect(screen.getByText('继续思考第二轮。')).toBeInTheDocument()
    expect(screen.getByText('第二轮回复-A第二轮回复-B')).toBeInTheDocument()
    expect(screen.getAllByText('思维链').length).toBeGreaterThanOrEqual(2)
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

    expect(await screen.findByText(/正在分析你的问题/)).toBeInTheDocument()

    await act(async () => {
      continueStream?.()
    })

    expect(await screen.findByText('分析完成')).toBeInTheDocument()
  })

  it('服务端历史缺少思维链字段时保留本地缓存中的思考与工具记录', async () => {
    useChatStore.setState({
      messages: [
        {
          id: 'cached-user-1',
          role: 'user',
          content: '帮我执行多轮调用',
          timestamp: new Date('2026-04-19T00:00:00Z'),
        },
        {
          id: 'cached-assistant-1',
          role: 'assistant',
          content: '最终回复。',
          reasoning_content: '先分析再调用工具。',
          timestamp: new Date('2026-04-19T00:00:05Z'),
          segments: [
            {
              id: 'thought-1',
              kind: 'thought',
              reasoningContent: '先分析再调用工具。',
              toolEvents: [
                {
                  id: 'tool-1',
                  kind: 'mcp',
                  name: 'filesystem/read_file',
                  status: 'completed',
                  detail: '读取完成',
                },
              ],
              steps: [],
              status: 'completed',
            },
            {
              id: 'reply-1',
              kind: 'reply',
              content: '最终回复。',
            },
          ],
        },
      ],
    })
    apiMocks.getHistory.mockResolvedValue({
      data: [
        {
          id: '101',
          role: 'user',
          content: '帮我执行多轮调用',
          timestamp: '2026-04-19T00:00:00Z',
        },
        {
          id: '102',
          role: 'assistant',
          content: '最终回复。',
          timestamp: '2026-04-19T00:00:05Z',
        },
      ],
    })

    await renderChatPage()
    fireEvent.click(await screen.findByText(/思维链/))

    expect(screen.getByText('先分析再调用工具。')).toBeInTheDocument()
    expect(screen.getByText('filesystem/read_file')).toBeInTheDocument()
    expect(screen.getByText('最终回复。')).toBeInTheDocument()
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
