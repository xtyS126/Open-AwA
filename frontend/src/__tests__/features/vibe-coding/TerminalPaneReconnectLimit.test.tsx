/**
 * TerminalPane WebSocket 重连上限单元测试。
 *
 * 覆盖点：
 *   - 连续失败超过 MAX_RECONNECT_ATTEMPTS（10 次）后停止重连
 *   - 超限后状态切换为 'error'
 *   - 超限后显示用户友好的失败提示文案
 *   - 超限后不再创建新的 WebSocket 实例
 *
 * Mock：
 *   - @xterm/xterm、@xterm/addon-fit：避免 jsdom canvas 缺失
 *   - @/shared/api/terminalApi：createPtySession、closePtySession
 *   - @/shared/api/client：API_BASE_URL、getCachedApiKey
 *   - 全局 WebSocket：可控制的 mock 实例
 *   - 使用 vi.useFakeTimers 加速多次重连定时器，配合 advanceTimersByTimeAsync 自动 flush 微任务
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import TerminalPane from '@/features/vibe-coding/components/TerminalPane'

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'

const terminalMocks = vi.hoisted(() => ({
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

vi.mock('@xterm/xterm', () => ({
  Terminal: class MockTerminal {
    constructor() {
      const instance = {
        open: vi.fn(),
        onData: vi.fn(() => ({ dispose: vi.fn() })),
        onResize: vi.fn(() => ({ dispose: vi.fn() })),
        write: vi.fn(),
        dispose: vi.fn(),
        loadAddon: vi.fn(),
      }
      terminalMocks.instances.push(instance)
      return instance
    }
  },
}))

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class MockFitAddon {
    fit = vi.fn()
    dispose = vi.fn()
  },
}))

vi.mock('@/shared/api/terminalApi', () => ({
  createPtySession: apiMocks.createPtySession,
  closePtySession: apiMocks.closePtySession,
}))

vi.mock('@/shared/api/client', () => ({
  API_BASE_URL: '/api',
  getCachedApiKey: vi.fn(() => 'test-token'),
}))

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

describe('TerminalPane 重连上限', () => {
  let wsInstances: MockWebSocketInstance[]

  beforeEach(() => {
    vi.clearAllMocks()
    terminalMocks.instances.length = 0
    wsInstances = []

    class MockWebSocket implements MockWebSocketInstance {
      static readonly OPEN = 1
      static readonly CONNECTING = 0

      url: string
      readyState = 0
      onopen: (() => void) | null = null
      onclose: (() => void) | null = null
      onerror: (() => void) | null = null
      onmessage: ((event: { data: string }) => void) | null = null
      close = vi.fn()
      send = vi.fn()

      constructor(url: string) {
        this.url = url
        wsInstances.push(this)
      }
    }
    vi.stubGlobal('WebSocket', MockWebSocket)

    apiMocks.createPtySession.mockResolvedValue({
      ok: true,
      session_id: 'pty-reconnect-test',
      project_id: PROJECT_ID,
      cols: 80,
      rows: 24,
      shell: 'bash',
    })
    apiMocks.closePtySession.mockResolvedValue({ ok: true })

    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('连续失败超过 10 次后停止重连并切换为 error 状态', async () => {
    await act(async () => {
      render(<TerminalPane projectId={PROJECT_ID} generation={1} onBindingChange={vi.fn()} />)
      // 推进 microtask 让 createPtySession 异步解析 + connectWebSocket 执行
      await vi.advanceTimersByTimeAsync(0)
    })

    // 至少 1 个 WebSocket（首次连接）已创建
    expect(wsInstances.length).toBeGreaterThanOrEqual(1)

    // 模拟首次连接成功（重置 reconnectAttemptsRef = 0）
    await act(async () => {
      wsInstances[0].readyState = 1
      wsInstances[0].onopen?.()
      await vi.advanceTimersByTimeAsync(0)
    })

    // 循环触发 10 次"连接失败 → 重连调度 → 定时器触发 → 新连接"
    // 每次循环：currentWs.onclose → scheduleReconnect(attempts=N) → 创建 ws (N+1)
    // 第 11 次 onclose 时 attempts=10 触发上限，停止重连
    const maxReconnectAttempts = 10
    let currentWs = wsInstances[0]

    for (let i = 0; i < maxReconnectAttempts; i += 1) {
      await act(async () => {
        currentWs.readyState = 3
        currentWs.onclose?.()
        // 推进定时器触发新连接创建（指数退避最大 30s，35s 足够）
        await vi.advanceTimersByTimeAsync(35000)
      })

      // 每次重连都创建新的 ws（前 10 次都未达上限）
      const nextWs = wsInstances[wsInstances.length - 1]
      expect(nextWs).not.toBe(currentWs)
      nextWs.readyState = 3
      currentWs = nextWs
    }

    // 此时已创建 1（首次）+ 10（重连）= 11 个 ws，reconnectAttemptsRef=10
    // 触发第 11 个 ws 的 onclose：进入上限分支，不再创建新 ws
    await act(async () => {
      currentWs.readyState = 3
      currentWs.onclose?.()
      await vi.advanceTimersByTimeAsync(35000)
    })

    // 验证：达到上限后，创建的 WebSocket 总数为 11（首次 + 10 次重连），未创建第 12 个
    expect(wsInstances.length).toBe(maxReconnectAttempts + 1)

    // 验证：状态切换为 error（i18n 中 vibeCoding.terminal.error = "连接错误"）
    expect(screen.getByText(/连接错误/)).toBeInTheDocument()

    // 验证：UI 显示友好失败提示
    expect(screen.getByText(/已重连 10 次仍失败/)).toBeInTheDocument()
  }, 30000)

  it('重连过程中任意一次连接成功应重置重连计数', async () => {
    await act(async () => {
      render(<TerminalPane projectId={PROJECT_ID} generation={1} onBindingChange={vi.fn()} />)
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(wsInstances.length).toBeGreaterThanOrEqual(1)

    // 首次连接失败 → 触发重连定时器
    await act(async () => {
      wsInstances[0].readyState = 3
      wsInstances[0].onclose?.()
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(wsInstances.length).toBe(2)

    // 第一次重连成功
    await act(async () => {
      wsInstances[1].readyState = 1
      wsInstances[1].onopen?.()
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(screen.getByText('已连接')).toBeInTheDocument()

    // 现在再次失败，重连计数应从 0 开始
    await act(async () => {
      wsInstances[1].readyState = 3
      wsInstances[1].onclose?.()
      await vi.advanceTimersByTimeAsync(2000)
    })

    // 状态切换为重连中
    expect(screen.getByText('重连中...')).toBeInTheDocument()
    // 应当能继续重连（计数已重置）
    expect(wsInstances.length).toBe(3)
  }, 15000)
})
