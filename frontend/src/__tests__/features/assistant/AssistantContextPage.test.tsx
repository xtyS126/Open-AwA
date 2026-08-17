import '@testing-library/jest-dom/vitest'
import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AssistantContextPage from '@/features/assistant/AssistantContextPage'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { conversationAPI } from '@/shared/api/conversationApi'

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
  apiPost: vi.fn(),
  getRoles: vi.fn(),
  activateRole: vi.fn(),
  listWorkspaces: vi.fn(),
  getLongTerm: vi.fn(),
  listSpeakers: vi.fn(),
  loadSpeakers: vi.fn(),
}))

vi.mock('@/shared/api/client', () => ({
  api: {
    get: mocks.apiGet,
    patch: mocks.apiPatch,
    post: mocks.apiPost,
    put: vi.fn(),
    delete: vi.fn(),
  },
  // authStore 依赖 client 的这两个导出（登出清理注册链引入），mock 需补齐
  setUnauthorizedHandler: vi.fn(),
  clearCachedApiKey: vi.fn(),
}))

vi.mock('@/shared/api/rolesApi', () => ({
  getRoles: mocks.getRoles,
  activateRole: mocks.activateRole,
}))

vi.mock('@/features/workspace/workspaceApi', () => ({
  workspaceApi: {
    list: mocks.listWorkspaces,
  },
}))

vi.mock('@/shared/api/memoryApi', () => ({
  memoryAPI: {
    getLongTerm: mocks.getLongTerm,
  },
}))

vi.mock('@/features/tts/ttsApi', () => ({
  ttsApi: {
    listSpeakers: mocks.listSpeakers,
  },
}))

vi.mock('@/features/tts/store/ttsStore', () => ({
  useTtsStore: {
    getState: () => ({ loadSpeakers: mocks.loadSpeakers }),
  },
}))

const roles = [
  { id: 'role-1', name: '通用助手', description: '处理日常任务' },
  { id: 'role-2', name: '代码搭档', description: '专注工程协作' },
]

const workspaces = [
  { id: 'default', name: '默认项目', description: '默认工作区', is_enabled: true },
  { id: 'workspace-2', name: '研究项目', description: '长期研究资料', is_enabled: true },
]

const memories = Array.from({ length: 21 }, (_, index) => ({
  id: index + 1,
  content: `知识条目 ${index + 1}`,
  importance: 0.5,
  confidence: 0.8,
}))

const speakers = [
  { speaker_id: 'speaker-1', name: '清朗声线', status: 'ready', language: 'zh', is_cloned: false },
  { speaker_id: 'speaker-2', name: '温暖声线', status: 'ready', language: 'zh', is_cloned: true },
]

function makeContext(overrides: Record<string, unknown> = {}) {
  return {
    session_id: 'session-42',
    role_id: null,
    workspace_id: 'default',
    selected_memory_ids: [],
    speaker_id: null,
    ...overrides,
  }
}

function arrangeSuccessfulLoads(context = makeContext()) {
  mocks.apiGet.mockResolvedValue({ data: context })
  mocks.apiPatch.mockImplementation((_url: string, payload: Record<string, unknown>) =>
    Promise.resolve({ data: { session_id: 'session-42', ...payload } }),
  )
  mocks.getRoles.mockResolvedValue(roles)
  mocks.listWorkspaces.mockResolvedValue({ workspaces })
  mocks.getLongTerm.mockResolvedValue({ data: memories })
  mocks.listSpeakers.mockResolvedValue({ speakers, total: speakers.length })
}

describe('conversationAPI 助手上下文契约', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('使用会话级 GET 与 PATCH 相对路径', async () => {
    const payload = {
      role_id: 'role-2',
      workspace_id: 'workspace-2',
      selected_memory_ids: [2],
      speaker_id: 'speaker-2',
    }
    mocks.apiGet.mockResolvedValue({ data: makeContext(payload) })
    mocks.apiPatch.mockResolvedValue({ data: makeContext(payload) })

    await conversationAPI.getAssistantContext('session 42')
    await conversationAPI.updateAssistantContext('session 42', payload)

    expect(mocks.apiGet).toHaveBeenCalledWith('/conversations/session%2042/assistant-context')
    expect(mocks.apiPatch).toHaveBeenCalledWith(
      '/conversations/session%2042/assistant-context',
      payload,
    )
  })
})

describe('AssistantContextPage', () => {
  /** 创建测试用 QueryClient：关闭重试与 staleTime，确保每次 mount 都重新发起查询 */
  function createTestQueryClient() {
    return new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: 0,
          gcTime: 0,
        },
      },
    })
  }

  /** 包裹 QueryClientProvider 的渲染辅助函数 */
  function renderWithQueryClient(ui: React.ReactNode) {
    const testQueryClient = createTestQueryClient()
    return {
      ...render(
        <QueryClientProvider client={testQueryClient}>
          {ui}
        </QueryClientProvider>,
      ),
      queryClient: testQueryClient,
    }
  }

  beforeEach(() => {
    vi.clearAllMocks()
    useSessionStore.setState({ sessionId: 'session-42' })
    arrangeSuccessfulLoads()
  })

  it('StrictMode 重放时每类首载请求只发送一次', async () => {
    const testQueryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: 60 * 1000,
        },
      },
    })

    render(
      <QueryClientProvider client={testQueryClient}>
        <StrictMode>
          <AssistantContextPage />
        </StrictMode>
      </QueryClientProvider>,
    )

    await screen.findByRole('group', { name: '角色上下文' })
    await waitFor(() => {
      expect([
        mocks.apiGet.mock.calls.length,
        mocks.getRoles.mock.calls.length,
        mocks.listWorkspaces.mock.calls.length,
        mocks.getLongTerm.mock.calls.length,
        mocks.listSpeakers.mock.calls.length,
      ]).toEqual([1, 1, 1, 1, 1])
    })
  })

  it('没有活动会话时显示提示，且不加载资源或创建会话', () => {
    useSessionStore.setState({ sessionId: 'default' })

    renderWithQueryClient(<AssistantContextPage />)

    expect(screen.getByText('请先选择或创建一个会话')).toBeInTheDocument()
    expect(mocks.apiGet).not.toHaveBeenCalled()
    expect(mocks.apiPost).not.toHaveBeenCalled()
    expect(mocks.getRoles).not.toHaveBeenCalled()
    expect(mocks.listWorkspaces).not.toHaveBeenCalled()
    expect(mocks.getLongTerm).not.toHaveBeenCalled()
    expect(mocks.listSpeakers).not.toHaveBeenCalled()
  })

  it('独立加载四类资源并回填会话已有选择', async () => {
    arrangeSuccessfulLoads(makeContext({
      role_id: 'role-2',
      workspace_id: 'workspace-2',
      selected_memory_ids: [2],
      speaker_id: 'speaker-2',
    }))

    renderWithQueryClient(<AssistantContextPage />)

    const roleGroup = await screen.findByRole('group', { name: '角色上下文' })
    const workspaceGroup = screen.getByRole('group', { name: '项目上下文' })
    const memoryGroup = screen.getByRole('group', { name: '知识上下文' })
    const speakerGroup = screen.getByRole('group', { name: '声音偏好' })

    expect(await within(roleGroup).findByRole('radio', { name: /代码搭档/ })).toBeChecked()
    expect(await within(workspaceGroup).findByRole('radio', { name: /研究项目/ })).toBeChecked()
    expect(await within(memoryGroup).findByRole('checkbox', { name: '知识条目 2' })).toBeChecked()
    expect(await within(speakerGroup).findByRole('radio', { name: /温暖声线/ })).toBeChecked()
    expect(mocks.apiGet).toHaveBeenCalledWith('/conversations/session-42/assistant-context')
    expect(mocks.getRoles).toHaveBeenCalledTimes(1)
    expect(mocks.listWorkspaces).toHaveBeenCalledTimes(1)
    expect(mocks.getLongTerm).toHaveBeenCalledTimes(1)
    expect(mocks.listSpeakers).toHaveBeenCalledTimes(1)
    expect(mocks.activateRole).not.toHaveBeenCalled()
    expect(mocks.loadSpeakers).not.toHaveBeenCalled()
  })

  it('单个分区加载失败时保留其余分区', async () => {
    mocks.getRoles.mockRejectedValue(new Error('角色服务不可用'))

    renderWithQueryClient(<AssistantContextPage />)

    const roleGroup = await screen.findByRole('group', { name: '角色上下文' })
    expect(await within(roleGroup).findByRole('alert')).toHaveTextContent('角色加载失败')
    expect(await screen.findByRole('radio', { name: /研究项目/ })).toBeInTheDocument()
    expect(await screen.findByRole('checkbox', { name: '知识条目 1' })).toBeInTheDocument()
    expect(await screen.findByRole('radio', { name: /清朗声线/ })).toBeInTheDocument()
  })

  it('知识选择最多允许二十条', async () => {
    renderWithQueryClient(<AssistantContextPage />)

    const memoryGroup = await screen.findByRole('group', { name: '知识上下文' })
    await within(memoryGroup).findByRole('checkbox', { name: '知识条目 1' })
    for (let index = 1; index <= 20; index += 1) {
      fireEvent.click(within(memoryGroup).getByRole('checkbox', { name: `知识条目 ${index}` }))
    }

    const twentyFirst = within(memoryGroup).getByRole('checkbox', { name: '知识条目 21' })
    expect(twentyFirst).toBeDisabled()
    expect(twentyFirst).not.toBeChecked()
    expect(within(memoryGroup).getByText('已选择 20 / 20')).toBeInTheDocument()
  })

  it('保存当前四类选择并发送完整上下文载荷', async () => {
    const { queryClient } = renderWithQueryClient(<AssistantContextPage />)

    fireEvent.click(await screen.findByRole('radio', { name: /代码搭档/ }))
    fireEvent.click(screen.getByRole('radio', { name: /研究项目/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: '知识条目 2' }))
    fireEvent.click(screen.getByRole('radio', { name: /温暖声线/ }))
    fireEvent.click(screen.getByRole('button', { name: '保存上下文' }))

    await waitFor(() => {
      expect(mocks.apiPatch).toHaveBeenCalledWith(
        '/conversations/session-42/assistant-context',
        {
          role_id: 'role-2',
          workspace_id: 'workspace-2',
          selected_memory_ids: [2],
          speaker_id: 'speaker-2',
        },
      )
    })
    expect(await screen.findByText('上下文已保存')).toBeInTheDocument()
    expect(queryClient.getQueryData([
      'conversations',
      'session-42',
      'assistant-context',
    ])).toEqual(makeContext({
      role_id: 'role-2',
      workspace_id: 'workspace-2',
      selected_memory_ids: [2],
      speaker_id: 'speaker-2',
    }))
  })

  it('保存失败时保留选择并显示可访问错误', async () => {
    mocks.apiPatch.mockRejectedValue(new Error('保存服务不可用'))
    renderWithQueryClient(<AssistantContextPage />)

    const roleOption = await screen.findByRole('radio', { name: /代码搭档/ })
    fireEvent.click(roleOption)
    fireEvent.click(screen.getByRole('button', { name: '保存上下文' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('保存上下文失败')
    expect(roleOption).toBeChecked()
  })
})
