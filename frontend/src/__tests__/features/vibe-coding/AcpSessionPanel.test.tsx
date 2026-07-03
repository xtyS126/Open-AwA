/**
 * AcpSessionPanel ACP 会话面板单元测试。
 *
 * 覆盖点：
 *   - sessionId=null 时空状态展示
 *   - 选中会话后输入区渲染
 *   - text 事件累积到输出区
 *   - permission 事件弹出 PermissionDialog
 *   - error 事件展示错误框
 *
 * Mock：
 *   - @/shared/api/client：API_BASE_URL、getCachedApiKey
 *   - @/shared/api/acpApi：respondPermission、cancelTurn
 *   - 全局 fetch：返回 ReadableStream 模拟 SSE 数据流
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import AcpSessionPanel from '@/features/vibe-coding/components/AcpSessionPanel'

// 提升的 mock 句柄
const acpApiMocks = vi.hoisted(() => ({
  respondPermission: vi.fn(),
  cancelTurn: vi.fn(),
}))

// 使用 importActual 保留 api（axios 实例）导出，仅覆盖测试需要的字段
// 否则 acpApi.ts 经由 api.ts 间接引用 ./client 的 api 时会因缺失导出而报错
vi.mock('@/shared/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/shared/api/client')>(
    '@/shared/api/client'
  )
  return {
    ...actual,
    API_BASE_URL: '/api',
    getCachedApiKey: vi.fn(() => 'test-token'),
  }
})

vi.mock('@/shared/api/acpApi', async () => {
  const actual = await vi.importActual<typeof import('@/shared/api/acpApi')>('@/shared/api/acpApi')
  return {
    ...actual,
    respondPermission: acpApiMocks.respondPermission,
    cancelTurn: acpApiMocks.cancelTurn,
  }
})

/** 将字符串数组编码为 SSE 帧字节流 */
function encodeSseFrames(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame))
      }
      controller.close()
    },
  })
}

/** 构造一个 SSE 帧 */
function sseFrame(eventType: string, data: unknown): string {
  return `event: ${eventType}\ndata: ${JSON.stringify(data)}\n\n`
}

describe('AcpSessionPanel', () => {
  const originalFetch = globalThis.fetch

  afterEach(() => {
    // 恢复 fetch，避免污染其他测试套件
    globalThis.fetch = originalFetch
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    acpApiMocks.respondPermission.mockResolvedValue({ status: 'ok' })
    acpApiMocks.cancelTurn.mockResolvedValue({ cancelled: true })
  })

  it('renders empty state when no session selected', () => {
    render(<AcpSessionPanel sessionId={null} cwd="." />)

    // 空状态文案来自 i18n: vibeCoding.acp.noSession
    expect(screen.getByText('请先选择或创建会话')).toBeInTheDocument()
    // 不应渲染输入区 textarea
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('renders input area when session selected', () => {
    render(<AcpSessionPanel sessionId="sess-1" cwd="/tmp/work" />)

    // textarea 应渲染，placeholder 来自 i18n
    const textarea = screen.getByPlaceholderText(
      '输入 prompt，回车发送（Shift+Enter 换行）'
    )
    expect(textarea).toBeInTheDocument()
    // 发送按钮应渲染，文案 "发送"
    expect(screen.getByText('发送')).toBeInTheDocument()
    // 工作目录顶栏应展示 cwd
    expect(screen.getByText('/tmp/work')).toBeInTheDocument()
  })

  it('handles text events and accumulates output', async () => {
    // mock fetch 返回 text 事件流
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      body: encodeSseFrames([
        sseFrame('text', { text: 'world' }),
        sseFrame('result', { status: 'completed' }),
      ]),
      json: async () => ({}),
    })
    globalThis.fetch = mockFetch as unknown as typeof fetch

    render(<AcpSessionPanel sessionId="sess-1" cwd="." />)

    // 输入 prompt 并点击发送
    const textarea = screen.getByPlaceholderText(
      '输入 prompt，回车发送（Shift+Enter 换行）'
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: 'hello' } })

    const sendButton = screen.getByText('发送').closest('button') as HTMLElement
    await act(async () => {
      fireEvent.click(sendButton)
    })

    // 验证 fetch 被以正确的 URL 与 body 调用
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/acp/sessions/sess-1/prompt',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
            Authorization: 'Bearer test-token',
          }),
          body: JSON.stringify({ prompt: 'hello' }),
        })
      )
    })

    // 输出区应同时显示用户输入与 agent 文本输出
    await waitFor(() => {
      expect(screen.getByText('hello')).toBeInTheDocument()
      expect(screen.getByText('world')).toBeInTheDocument()
    })
  })

  it('shows permission dialog on permission event', async () => {
    // mock fetch 返回 permission 事件
    const permissionData = {
      tool_name: 'bash',
      tool_kind: 'execute',
      target: '/tmp',
      action: 'run',
      command: 'ls /tmp',
      options: [
        { id: 'allow', label: '允许', kind: 'allow' },
        { id: 'deny', label: '拒绝', kind: 'deny' },
      ],
    }
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      body: encodeSseFrames([sseFrame('permission', permissionData)]),
      json: async () => ({}),
    })
    globalThis.fetch = mockFetch as unknown as typeof fetch

    render(<AcpSessionPanel sessionId="sess-1" cwd="." />)

    const textarea = screen.getByPlaceholderText(
      '输入 prompt，回车发送（Shift+Enter 换行）'
    )
    fireEvent.change(textarea, { target: { value: 'run cmd' } })
    await act(async () => {
      fireEvent.click(screen.getByText('发送').closest('button') as HTMLElement)
    })

    // PermissionDialog 应弹出，显示工具名与目标
    await waitFor(() => {
      expect(screen.getByText('bash')).toBeInTheDocument()
      expect(screen.getByText('/tmp')).toBeInTheDocument()
      // 选项按钮渲染
      expect(screen.getByText('允许')).toBeInTheDocument()
    })
  })

  it('handles error event gracefully', async () => {
    // mock fetch 返回 error 事件
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      body: encodeSseFrames([sseFrame('error', { message: 'agent 异常退出' })]),
      json: async () => ({}),
    })
    globalThis.fetch = mockFetch as unknown as typeof fetch

    render(<AcpSessionPanel sessionId="sess-1" cwd="." />)

    const textarea = screen.getByPlaceholderText(
      '输入 prompt，回车发送（Shift+Enter 换行）'
    )
    fireEvent.change(textarea, { target: { value: 'go' } })
    await act(async () => {
      fireEvent.click(screen.getByText('发送').closest('button') as HTMLElement)
    })

    // 错误事件应在输出区展示
    await waitFor(() => {
      expect(screen.getByText('agent 异常退出')).toBeInTheDocument()
    })
  })
})
