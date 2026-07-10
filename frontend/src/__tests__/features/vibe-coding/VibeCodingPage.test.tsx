/**
 * VibeCodingPage 主页面单元测试。
 *
 * 覆盖点：
 *   - 三栏布局渲染（标题 / AgentSelector / SegmentedControl / FilePreviewPane）
 *   - 加载并显示 agents 列表
 *   - 加载并显示 sessions 列表
 *   - 加载并显示 notifications 列表
 *   - 点击创建会话按钮调用 createSession
 *   - 点击 SegmentedControl 切换 ACP / 终端面板
 *
 * Mock：
 *   - @/shared/api/acpApi：listAgents / listSessions / createSession / closeSession
 *   - @/shared/api/notificationsApi：listNotifications
 *   - @/features/vibe-coding/components/TerminalPane：渲染为简单占位（避免 xterm + WebSocket 集成复杂度，TerminalPane 已有独立测试覆盖）
 *   - 全局 EventSource：mock 为简单实现，不真正连接
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import VibeCodingPage from '@/features/vibe-coding/VibeCodingPage'

// 提升 mock 句柄
const acpApiMocks = vi.hoisted(() => ({
  listAgents: vi.fn(),
  listSessions: vi.fn(),
  createSession: vi.fn(),
  closeSession: vi.fn(),
}))

const notificationsApiMocks = vi.hoisted(() => ({
  listNotifications: vi.fn(),
}))

// mock TerminalPane 为简单占位 —— 该组件依赖 xterm.js 与 WebSocket，
// 在 jsdom 集成环境会引入不必要的复杂度。TerminalPane 已有独立测试覆盖。
vi.mock('@/features/vibe-coding/components/TerminalPane', () => ({
  default: ({ cwd }: { cwd: string }) => (
    <div data-testid="terminal-pane-mock">terminal:{cwd}</div>
  ),
}))

vi.mock('@/shared/api/acpApi', () => ({
  listAgents: acpApiMocks.listAgents,
  listSessions: acpApiMocks.listSessions,
  createSession: acpApiMocks.createSession,
  closeSession: acpApiMocks.closeSession,
}))

vi.mock('@/shared/api/notificationsApi', () => ({
  listNotifications: notificationsApiMocks.listNotifications,
}))

// mock useBreakpoint 返回桌面端布局，使测试与桌面端三栏布局期望对齐。
// jsdom 默认未实现 window.matchMedia，useBreakpoint 会回落到 xs（isMobile=true），
// 导致渲染移动端布局而测试期望桌面端 segmented control。
vi.mock('@/shared/hooks/useBreakpoint', () => ({
  useBreakpoint: () => ({
    breakpoint: 'xl',
    isMobile: false,
    isTablet: false,
    isDesktop: true,
  }),
}))

/** 构造 mock EventSource，记录实例并提供事件触发能力 */
class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onmessage: ((event: { data: string }) => void) | null = null
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

describe('VibeCodingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    MockEventSource.instances.length = 0

    // 默认 mock 返回值：2 个 agent（1 可用 / 1 不可用）+ 1 个会话 + 1 条通知
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
          available: false,
        },
      ],
      count: 2,
    })
    acpApiMocks.listSessions.mockResolvedValue({
      sessions: [
        {
          session_id: 'sess-1',
          agent: 'claude_code',
          cwd: '/tmp/work',
          created_at: '2026-06-27T00:00:00Z',
        },
      ],
      count: 1,
    })
    acpApiMocks.createSession.mockResolvedValue({
      session_id: 'sess-new',
      config_options: [],
    })
    acpApiMocks.closeSession.mockResolvedValue({ closed: true })

    notificationsApiMocks.listNotifications.mockResolvedValue({
      notifications: [
        {
          id: 'notif-1',
          title: '构建完成',
          body: 'vibe-coding 模块构建成功',
          notification_type: 'success',
          created_at: '2026-06-27T00:00:00Z',
        },
      ],
      count: 1,
    })

    vi.stubGlobal('EventSource', MockEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders three-column layout correctly', async () => {
    render(<BrowserRouter><VibeCodingPage /></BrowserRouter>)

    // 等待初始数据加载完成
    await waitFor(() => {
      expect(acpApiMocks.listAgents).toHaveBeenCalled()
    })

    // 标题（i18n: vibeCoding.title）
    expect(screen.getByText('Vibe Coding')).toBeInTheDocument()
    // 左栏：AgentSelector 渲染（通过 label 关联的 select 元素定位，避免与 option 文案冲突）
    expect(screen.getByLabelText('选择 Agent')).toBeInTheDocument()
    // 中栏：SegmentedControl 两个 tab（i18n: vibeCoding.acpPanel / terminalPanel）
    expect(screen.getByText('ACP 会话')).toBeInTheDocument()
    expect(screen.getByText('终端')).toBeInTheDocument()
    // 右栏：FilePreviewPane 的路径输入框 placeholder
    expect(screen.getByPlaceholderText('输入文件绝对路径')).toBeInTheDocument()
  })

  it('loads and displays agents list', async () => {
    render(<BrowserRouter><VibeCodingPage /></BrowserRouter>)

    // 等待 listAgents 调用完成
    await waitFor(() => {
      expect(acpApiMocks.listAgents).toHaveBeenCalledTimes(1)
    })

    // 下拉框中应包含两个 agent 名称
    // Claude Code 可用，Codex 不可用并标注 "未安装"
    const select = screen.getByLabelText('选择 Agent') as HTMLSelectElement
    expect(select).toBeInTheDocument()

    const options = Array.from(select.options)
    const claudeOption = options.find((o) => o.value === 'claude_code')
    const codexOption = options.find((o) => o.value === 'codex')
    expect(claudeOption).toBeDefined()
    expect(claudeOption?.textContent).toContain('Claude Code')
    expect(claudeOption?.disabled).toBe(false)
    expect(codexOption).toBeDefined()
    expect(codexOption?.textContent).toContain('Codex')
    expect(codexOption?.textContent).toContain('未安装')
    expect(codexOption?.disabled).toBe(true)

    // 默认应选中第一个可用 agent
    expect(select.value).toBe('claude_code')
  })

  it('loads and displays sessions list', async () => {
    render(<BrowserRouter><VibeCodingPage /></BrowserRouter>)

    // 等待会话列表加载并渲染
    await waitFor(() => {
      expect(acpApiMocks.listSessions).toHaveBeenCalledTimes(1)
    })
    // 会话项应显示 agent 名称（claude_code）
    expect(await screen.findByText('claude_code')).toBeInTheDocument()
  })

  it('loads and displays notifications', async () => {
    render(<BrowserRouter><VibeCodingPage /></BrowserRouter>)

    // 等待通知列表加载并渲染
    await waitFor(() => {
      expect(notificationsApiMocks.listNotifications).toHaveBeenCalledTimes(1)
    })
    // 通知标题应显示
    expect(await screen.findByText('构建完成')).toBeInTheDocument()
    // 通知正文应显示
    expect(screen.getByText('vibe-coding 模块构建成功')).toBeInTheDocument()
  })

  it('creates new session on button click', async () => {
    render(<BrowserRouter><VibeCodingPage /></BrowserRouter>)

    // 等待初始加载完成，确保默认 agent 已被选中
    await waitFor(() => {
      expect(acpApiMocks.listAgents).toHaveBeenCalledTimes(1)
    })

    // 点击 "创建会话" 按钮（i18n: vibeCoding.createSession）
    const createBtn = await screen.findByText('创建会话')
    await act(async () => {
      fireEvent.click(createBtn)
    })

    // 验证 createSession 被以选中的 agent 调用
    await waitFor(() => {
      expect(acpApiMocks.createSession).toHaveBeenCalledWith('claude_code', '.')
    })
  })

  it('switches between acp and terminal panes', async () => {
    render(<BrowserRouter><VibeCodingPage /></BrowserRouter>)

    // 等待初始加载完成
    await waitFor(() => {
      expect(acpApiMocks.listAgents).toHaveBeenCalledTimes(1)
    })

    // 初始状态：ACP tab 被选中，TerminalPane 不渲染
    const acpTab = screen.getByText('ACP 会话').closest('button') as HTMLElement
    const terminalTab = screen.getByText('终端').closest('button') as HTMLElement
    expect(acpTab.getAttribute('aria-selected')).toBe('true')
    expect(terminalTab.getAttribute('aria-selected')).toBe('false')
    expect(screen.queryByTestId('terminal-pane-mock')).not.toBeInTheDocument()

    // 点击 "终端" tab 切换面板
    await act(async () => {
      fireEvent.click(terminalTab)
    })

    // 切换后：terminal tab 被选中，TerminalPane mock 渲染
    expect(terminalTab.getAttribute('aria-selected')).toBe('true')
    expect(acpTab.getAttribute('aria-selected')).toBe('false')
    expect(screen.getByTestId('terminal-pane-mock')).toBeInTheDocument()

    // 切回 ACP 面板
    await act(async () => {
      fireEvent.click(acpTab)
    })
    expect(acpTab.getAttribute('aria-selected')).toBe('true')
    expect(terminalTab.getAttribute('aria-selected')).toBe('false')
    expect(screen.queryByTestId('terminal-pane-mock')).not.toBeInTheDocument()
  })
})
