/**
 * Vibe Coding 主页面项目隔离测试。
 *
 * 覆盖工作台项目门禁、project_id API 契约、切换代际隔离，以及 RuntimeDock
 * 单一所有权。测试不挂载真实终端或文件预览组件。
 */
import '@testing-library/jest-dom/vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { RouterTestProvider as BrowserRouter } from '@/shared/routing/testing'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import VibeCodingPage from '@/features/vibe-coding/VibeCodingPage'
import { useWorkbenchProjectStore } from '@/features/workbench/store/workbenchProjectStore'
import { useWorkbenchRuntimeStore } from '@/features/workbench/store/workbenchRuntimeStore'
import { asWorkbenchProjectId } from '@/features/workbench/workbenchTypes'

const acpApiMocks = vi.hoisted(() => ({
  listAgents: vi.fn(),
  listSessions: vi.fn(),
  createSession: vi.fn(),
  closeSession: vi.fn(),
  getOpenCodeStatus: vi.fn(),
  installOpenCode: vi.fn(),
}))

const notificationsApiMocks = vi.hoisted(() => ({
  listNotifications: vi.fn(),
}))

vi.mock('@/shared/api/acpApi', () => ({
  listAgents: acpApiMocks.listAgents,
  listSessions: acpApiMocks.listSessions,
  createSession: acpApiMocks.createSession,
  closeSession: acpApiMocks.closeSession,
  getOpenCodeStatus: acpApiMocks.getOpenCodeStatus,
  installOpenCode: acpApiMocks.installOpenCode,
}))

vi.mock('@/shared/api/notificationsApi', () => ({
  listNotifications: notificationsApiMocks.listNotifications,
}))

class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onmessage: ((event: { data: string }) => void) | null = null
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  readyState = 0

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  close() {
    this.readyState = 2
  }
}

const PROJECT_A = asWorkbenchProjectId('project-a')
const PROJECT_B = asWorkbenchProjectId('project-b')

const projects = [
  {
    id: PROJECT_A,
    displayName: '项目甲',
    isEnabled: true,
    createdAt: '2026-08-15T00:00:00Z',
    updatedAt: '2026-08-15T00:00:00Z',
    lastOpenedAt: null,
  },
  {
    id: PROJECT_B,
    displayName: '项目乙',
    isEnabled: true,
    createdAt: '2026-08-15T00:00:00Z',
    updatedAt: '2026-08-15T00:00:00Z',
    lastOpenedAt: null,
  },
]

function setCurrentProject(projectId: typeof PROJECT_A | null, generation: number): void {
  useWorkbenchProjectStore.setState({
    projects,
    currentProjectId: projectId,
    switchGeneration: generation,
    phase: projectId ? 'ready' : 'no-selection',
  })
  if (projectId) {
    useWorkbenchRuntimeStore.getState().activateProject(projectId, generation)
  }
}

function renderPage() {
  return render(<BrowserRouter><VibeCodingPage /></BrowserRouter>)
}

describe('VibeCodingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    MockEventSource.instances.length = 0
    useWorkbenchRuntimeStore.getState().resetAll()
    setCurrentProject(PROJECT_A, 1)

    acpApiMocks.listAgents.mockResolvedValue({
      agents: [
        {
          id: 'claude_code',
          name: 'Claude Code',
          command: 'claude',
          enabled: true,
          available: true,
        },
      ],
      count: 1,
    })
    acpApiMocks.listSessions.mockResolvedValue({
      sessions: [
        {
          session_id: 'sess-a',
          agent: 'claude_code',
          project_id: PROJECT_A,
          created_at: '2026-08-15T00:00:00Z',
        },
      ],
      count: 1,
    })
    acpApiMocks.createSession.mockResolvedValue({
      session_id: 'sess-new',
      project_id: PROJECT_A,
      config_options: [],
    })
    acpApiMocks.closeSession.mockResolvedValue({ closed: true })
    acpApiMocks.getOpenCodeStatus.mockResolvedValue({
      project_id: PROJECT_A,
      package_json_exists: true,
      project_installed: false,
      available: false,
      command: 'opencode',
    })
    acpApiMocks.installOpenCode.mockResolvedValue({
      project_id: PROJECT_A,
      package_json_exists: true,
      project_installed: true,
      available: true,
      command: 'opencode',
      installed: true,
      audit_passed: true,
      output: 'installed',
    })
    notificationsApiMocks.listNotifications.mockResolvedValue({
      notifications: [],
      count: 0,
    })
    vi.stubGlobal('EventSource', MockEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('没有可用工作台项目时显示门禁且不发送 ACP 请求', async () => {
    setCurrentProject(null, 2)

    renderPage()

    expect(screen.getByText('请先选择一个可用的工作台项目')).toBeInTheDocument()
    await act(async () => Promise.resolve())
    expect(acpApiMocks.listAgents).not.toHaveBeenCalled()
    expect(acpApiMocks.listSessions).not.toHaveBeenCalled()
    expect(acpApiMocks.getOpenCodeStatus).not.toHaveBeenCalled()
  })

  it('只显示项目安全字段并按当前项目加载会话', async () => {
    renderPage()

    expect(await screen.findByText('项目甲')).toBeInTheDocument()
    expect(await screen.findByText('claude_code')).toBeInTheDocument()
    expect(acpApiMocks.listSessions).toHaveBeenCalledWith(PROJECT_A)
    expect(screen.queryByLabelText('ACP 工作目录')).not.toBeInTheDocument()
    expect(screen.queryByText(/\/tmp\/|D:\\/)).not.toBeInTheDocument()
  })

  it('创建和关闭会话时始终携带当前项目 ID', async () => {
    renderPage()
    await screen.findByText('claude_code')

    fireEvent.click(screen.getByText('创建会话'))
    await waitFor(() => {
      expect(acpApiMocks.createSession).toHaveBeenCalledWith(
        PROJECT_A,
        'claude_code',
        expect.any(AbortSignal),
      )
    })

    const closeButtons = screen.getAllByRole('button', { name: '关闭' })
    fireEvent.click(closeButtons[0])
    await waitFor(() => {
      expect(acpApiMocks.closeSession).toHaveBeenCalledWith(PROJECT_A, 'sess-a')
    })
  })

  it('OpenCode 状态和安装请求使用当前项目 ID', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    acpApiMocks.listAgents.mockResolvedValueOnce({
      agents: [{
        id: 'opencode',
        name: 'OpenCode',
        command: 'opencode',
        enabled: true,
        available: true,
      }],
      count: 1,
    })

    renderPage()

    await waitFor(() => {
      expect(acpApiMocks.getOpenCodeStatus).toHaveBeenCalledWith(PROJECT_A)
    })
    fireEvent.click(await screen.findByText('安装 OpenCode'))
    await waitFor(() => {
      expect(acpApiMocks.installOpenCode).toHaveBeenCalledWith(PROJECT_A)
    })
  })

  it('切换项目后丢弃旧 generation 的会话响应', async () => {
    let resolveProjectA: ((value: unknown) => void) | undefined
    acpApiMocks.listSessions.mockImplementation((projectId: string) => {
      if (projectId === PROJECT_A) {
        return new Promise((resolve) => {
          resolveProjectA = resolve
        })
      }
      return Promise.resolve({
        sessions: [{
          session_id: 'sess-b',
          agent: 'codex',
          project_id: PROJECT_B,
          created_at: '2026-08-15T01:00:00Z',
        }],
        count: 1,
      })
    })

    renderPage()
    await waitFor(() => expect(acpApiMocks.listSessions).toHaveBeenCalledWith(PROJECT_A))

    act(() => setCurrentProject(PROJECT_B, 2))

    expect(await screen.findByText('项目乙')).toBeInTheDocument()
    expect(await screen.findByText('codex')).toBeInTheDocument()
    await act(async () => {
      resolveProjectA?.({
        sessions: [{
          session_id: 'stale-a',
          agent: 'stale-agent',
          project_id: PROJECT_A,
          created_at: '2026-08-15T00:00:00Z',
        }],
        count: 1,
      })
      await Promise.resolve()
    })

    expect(screen.queryByText('stale-agent')).not.toBeInTheDocument()
    expect(screen.getByText('codex')).toBeInTheDocument()
  })

  it('切换项目时中止在途创建请求', async () => {
    let capturedSignal: AbortSignal | undefined
    acpApiMocks.createSession.mockImplementation(
      (_projectId: string, _agent: string, signal: AbortSignal) => {
        capturedSignal = signal
        return new Promise(() => undefined)
      },
    )

    renderPage()
    await screen.findByText('claude_code')
    fireEvent.click(screen.getByText('创建会话'))
    await waitFor(() => expect(capturedSignal).toBeDefined())

    act(() => setCurrentProject(PROJECT_B, 2))

    expect(capturedSignal?.aborted).toBe(true)
  })

  it('A 到 B 再回 A 时恢复各项目的 Agent 与会话选择', async () => {
    acpApiMocks.listAgents.mockResolvedValue({
      agents: [
        {
          id: 'claude_code',
          name: 'Claude Code',
          command: 'claude',
          enabled: true,
          available: true,
        },
        {
          id: 'codex',
          name: 'Codex',
          command: 'codex',
          enabled: true,
          available: true,
        },
      ],
      count: 2,
    })
    acpApiMocks.listSessions.mockImplementation((projectId: string) => Promise.resolve({
      sessions: projectId === PROJECT_A
        ? [{
            session_id: 'sess-a',
            agent: 'codex',
            project_id: PROJECT_A,
            created_at: '2026-08-15T00:00:00Z',
          }]
        : [{
            session_id: 'sess-b',
            agent: 'claude_code',
            project_id: PROJECT_B,
            created_at: '2026-08-15T01:00:00Z',
          }],
      count: 1,
    }))

    renderPage()
    const agentSelector = await screen.findByRole('combobox')
    await screen.findByText('sess-a')
    fireEvent.change(agentSelector, { target: { value: 'codex' } })
    fireEvent.click(screen.getByText('sess-a'))
    await waitFor(() => {
      expect(useWorkbenchRuntimeStore.getState().projects[PROJECT_A]?.selectedSessionId)
        .toBe('sess-a')
    })

    act(() => setCurrentProject(PROJECT_B, 2))
    expect(await screen.findByText('项目乙')).toBeInTheDocument()
    await screen.findByText('sess-b')

    act(() => setCurrentProject(PROJECT_A, 3))
    expect(await screen.findByText('项目甲')).toBeInTheDocument()
    await screen.findByText('sess-a')

    expect(agentSelector).toHaveValue('codex')
    expect(useWorkbenchRuntimeStore.getState().projects[PROJECT_A]?.selectedSessionId)
      .toBe('sess-a')
  })

  it('不再挂载第二套终端和文件预览 owner', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/features/vibe-coding/VibeCodingPage.tsx'),
      'utf8',
    )

    expect(source).not.toContain("from './components/TerminalPane'")
    expect(source).not.toContain("from './components/FilePreviewPane'")
    expect(source).not.toContain('<TerminalPane')
    expect(source).not.toContain('<FilePreviewPane')
    expect(source).not.toContain('previewPort')
    expect(source).not.toContain('projectCwd')
  })
})
