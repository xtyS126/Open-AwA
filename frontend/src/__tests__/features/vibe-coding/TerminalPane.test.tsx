/**
 * TerminalPane 终端面板单元测试。
 *
 * 覆盖点：
 *   - 组件 mount 不抛异常（xterm 在 jsdom 无法正常渲染）
 *   - mount 时调用 createPtySession
 *   - 初始状态显示 "连接中..."
 *   - WebSocket 关闭后触发重连
 *
 * Mock：
 *   - @xterm/xterm：Terminal 类（open/onData/onResize/write/dispose/loadAddon）
 *   - @xterm/addon-fit：FitAddon 类（fit/dispose）
 *   - @/shared/api/terminalApi：createPtySession、closePtySession
 *   - @/shared/api/client：API_BASE_URL、getCachedApiKey
 *   - 全局 WebSocket：可控制的 mock 实例
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import TerminalPane from '@/features/vibe-coding/components/TerminalPane'

const PROJECT_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const PROJECT_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'

// 提升 mock 句柄，便于在 vi.mock 工厂内引用
const terminalMocks = vi.hoisted(() => ({
  // 跟踪每次 new Terminal() 创建的实例
  instances: [] as Array<{
    open: ReturnType<typeof vi.fn>
    onData: ReturnType<typeof vi.fn>
    onResize: ReturnType<typeof vi.fn>
    write: ReturnType<typeof vi.fn>
    dispose: ReturnType<typeof vi.fn>
    loadAddon: ReturnType<typeof vi.fn>
  }>,
}))

const apiMocks = vi.hoisted(() => ({
  createPtySession: vi.fn(),
  closePtySession: vi.fn(),
}))

// mock xterm.js Terminal 类，避免 jsdom 环境的 canvas 缺失
vi.mock('@xterm/xterm', () => {
  class TerminalMock {
    open = vi.fn()
    onData = vi.fn(() => ({ dispose: vi.fn() }))
    onResize = vi.fn(() => ({ dispose: vi.fn() }))
    write = vi.fn()
    dispose = vi.fn()
    loadAddon = vi.fn()

    constructor() {
      terminalMocks.instances.push(this)
    }
  }

  return { Terminal: TerminalMock }
})

// mock FitAddon 类
vi.mock('@xterm/addon-fit', () => {
  class FitAddonMock {
    fit = vi.fn()
    dispose = vi.fn()
  }

  return { FitAddon: FitAddonMock }
})

vi.mock('@/shared/api/terminalApi', () => ({
  createPtySession: apiMocks.createPtySession,
  closePtySession: apiMocks.closePtySession,
}))

vi.mock('@/shared/api/client', () => ({
  API_BASE_URL: '/api',
  getCachedApiKey: vi.fn(() => 'test-token'),
}))

/** Mock WebSocket 构造函数，支持事件回调注入 */
interface MockWebSocketInstance {
  url: string
  readyState: number
  onopen: (() => void) | null
  onclose: (() => void) | null
  onerror: (() => void) | null
  onmessage: ((event: { data: string }) => void) | null
  close: ReturnType<typeof vi.fn>
  send: ReturnType<typeof vi.fn>
}

describe('TerminalPane', () => {
  let wsInstances: MockWebSocketInstance[]
  let MockWebSocketCtor: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.clearAllMocks()
    terminalMocks.instances.length = 0
    wsInstances = []

    MockWebSocketCtor = vi.fn(function MockWebSocket(
      this: MockWebSocketInstance,
      url: string,
    ) {
      const inst: MockWebSocketInstance = {
        url,
        readyState: 0, // CONNECTING
        onopen: null,
        onclose: null,
        onerror: null,
        onmessage: null,
        close: vi.fn(),
        send: vi.fn(),
      }
      Object.assign(this, inst)
      wsInstances.push(this)
    })
    // 暴露 OPEN / CONNECTING 常量，源码中通过 WebSocket.OPEN 比较
    ;(MockWebSocketCtor as unknown as { OPEN: number }).OPEN = 1
    ;(MockWebSocketCtor as unknown as { CONNECTING: number }).CONNECTING = 0
    vi.stubGlobal('WebSocket', MockWebSocketCtor)

    // createPtySession 默认成功返回
    apiMocks.createPtySession.mockResolvedValue({
      ok: true,
      session_id: 'pty-test-session',
      project_id: PROJECT_A,
      cols: 80,
      rows: 24,
      shell: 'bash',
    })
    apiMocks.closePtySession.mockResolvedValue({ ok: true })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('renders without crashing', async () => {
    await act(async () => {
      render(<TerminalPane projectId={PROJECT_A} generation={1} onBindingChange={vi.fn()} />)
    })

    // 组件渲染后应出现状态栏文案（任意一种状态文字都可证明渲染成功）
    await waitFor(() => {
      expect(screen.getByText(/连接中|已连接|重连中|已断开|连接错误/)).toBeInTheDocument()
    })
  })

  it('creates pty session on mount', async () => {
    await act(async () => {
      render(<TerminalPane projectId={PROJECT_A} generation={1} onBindingChange={vi.fn()} />)
    })

    await waitFor(() => {
      expect(apiMocks.createPtySession).toHaveBeenCalledTimes(1)
    })
    // 终端只能提交服务端权威项目标识，不能提交 cwd 或 root。
    expect(apiMocks.createPtySession).toHaveBeenCalledWith({
      projectId: PROJECT_A,
      cols: 80,
      rows: 24,
    })
  })

  it('shows connecting status initially', async () => {
    await act(async () => {
      render(<TerminalPane projectId={PROJECT_A} generation={1} onBindingChange={vi.fn()} />)
    })

    // 初始状态为 "连接中..."（i18n: vibeCoding.terminal.connecting）
    await waitFor(() => {
      expect(screen.getByText('连接中...')).toBeInTheDocument()
    })
  })

  it('attempts reconnection on websocket close', async () => {
    // 使用真实 timers，但给足超时让重连（1s 退避）触发
    await act(async () => {
      render(<TerminalPane projectId={PROJECT_A} generation={1} onBindingChange={vi.fn()} />)
    })

    // 等待首次 WebSocket 创建完成
    await waitFor(() => {
      expect(wsInstances.length).toBeGreaterThanOrEqual(1)
    })

    // 触发 onopen 模拟连接成功，重置重连计数
    await act(async () => {
      wsInstances[0].readyState = 1 // OPEN
      wsInstances[0].onopen?.()
    })

    expect(screen.getByText('已连接')).toBeInTheDocument()

    // 触发 onclose 模拟服务端关闭，应进入重连调度
    await act(async () => {
      wsInstances[0].readyState = 3 // CLOSED
      wsInstances[0].onclose?.()
    })

    // 关闭后状态应切换为 "重连中..."
    expect(screen.getByText('重连中...')).toBeInTheDocument()

    // 等待重连定时器触发（基础延迟 1s + 余量），应创建第二个 WebSocket
    await waitFor(
      () => {
        expect(wsInstances.length).toBeGreaterThanOrEqual(2)
      },
      { timeout: 3000 }
    )
  }, 10000) // 给整个 test 10s 超时

  it('项目代次变化时关闭旧资源且清理迟到的旧创建响应', async () => {
    let resolveProjectA: ((value: {
      ok: boolean
      session_id: string
      project_id: string
    }) => void) | undefined
    const projectACreate = new Promise<{
      ok: boolean
      session_id: string
      project_id: string
    }>((resolve) => {
      resolveProjectA = resolve
    })
    apiMocks.createPtySession.mockImplementation(({ projectId }: { projectId: string }) => {
      if (projectId === PROJECT_A) return projectACreate
      return Promise.resolve({
        ok: true,
        session_id: 'pty-project-b',
        project_id: PROJECT_B,
      })
    })
    const onBindingChange = vi.fn()
    const view = render(
      <TerminalPane
        projectId={PROJECT_A}
        generation={1}
        onBindingChange={onBindingChange}
      />,
    )

    view.rerender(
      <TerminalPane
        projectId={PROJECT_B}
        generation={2}
        onBindingChange={onBindingChange}
      />,
    )

    await waitFor(() => {
      expect(onBindingChange).toHaveBeenCalledWith('pty-project-b')
    })

    await act(async () => {
      resolveProjectA?.({
        ok: true,
        session_id: 'pty-project-a-stale',
        project_id: PROJECT_A,
      })
      await projectACreate
    })

    await waitFor(() => {
      expect(apiMocks.closePtySession).toHaveBeenCalledWith('pty-project-a-stale')
    })
    expect(onBindingChange).not.toHaveBeenCalledWith('pty-project-a-stale')
    expect(wsInstances).toHaveLength(1)
  })
})
