/**
 * ACP 会话面板的项目隔离与流式交互测试。
 */
import '@testing-library/jest-dom/vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AcpSessionPanel from '@/features/vibe-coding/components/AcpSessionPanel'

const acpApiMocks = vi.hoisted(() => ({
  createPromptRequest: vi.fn((projectId: string, prompt: string) => ({
    project_id: projectId,
    prompt,
  })),
  respondPermission: vi.fn(),
  cancelTurn: vi.fn(),
}))

vi.mock('@/shared/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/shared/api/client')>(
    '@/shared/api/client',
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
    createPromptRequest: acpApiMocks.createPromptRequest,
    respondPermission: acpApiMocks.respondPermission,
    cancelTurn: acpApiMocks.cancelTurn,
  }
})

function encodeSseFrames(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    },
  })
}

function sseFrame(eventType: string, data: unknown): string {
  return `event: ${eventType}\ndata: ${JSON.stringify(data)}\n\n`
}

const defaultProps = {
  projectId: 'project-a',
  generation: 1,
  sessionId: 'sess-1',
}

describe('AcpSessionPanel', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.clearAllMocks()
    acpApiMocks.respondPermission.mockResolvedValue({ status: 'ok' })
    acpApiMocks.cancelTurn.mockResolvedValue({ cancelled: true })
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.unstubAllGlobals()
  })

  it('没有会话时显示空状态', () => {
    render(<AcpSessionPanel {...defaultProps} sessionId={null} />)

    expect(screen.getByText('请先选择或创建会话')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('选中会话时不显示工作目录或项目根路径', () => {
    render(<AcpSessionPanel {...defaultProps} />)

    expect(screen.getByPlaceholderText('输入 prompt，回车发送（Shift+Enter 换行）')).toBeInTheDocument()
    expect(screen.queryByText('/tmp/work')).not.toBeInTheDocument()
    expect(screen.queryByText('工作目录')).not.toBeInTheDocument()
  })

  it('通过 createPromptRequest 发送包含 project_id 的 prompt', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      body: encodeSseFrames([
        sseFrame('text', { text: 'world' }),
        sseFrame('result', { status: 'completed' }),
      ]),
      json: async () => ({}),
    })
    globalThis.fetch = mockFetch as unknown as typeof fetch

    render(<AcpSessionPanel {...defaultProps} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hello' } })
    fireEvent.click(screen.getByText('发送').closest('button') as HTMLElement)

    await waitFor(() => {
      expect(acpApiMocks.createPromptRequest).toHaveBeenCalledWith('project-a', 'hello')
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/acp/sessions/sess-1/prompt',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ project_id: 'project-a', prompt: 'hello' }),
        }),
      )
    })
    expect(await screen.findByText('world')).toBeInTheDocument()
  })

  it('权限响应携带 projectId 和 sessionId', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: encodeSseFrames([sseFrame('permission', {
        tool_name: 'bash',
        options: [{ id: 'allow', label: '允许', kind: 'allow' }],
      })]),
      json: async () => ({}),
    }) as unknown as typeof fetch

    render(<AcpSessionPanel {...defaultProps} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'run cmd' } })
    fireEvent.click(screen.getByText('发送').closest('button') as HTMLElement)
    fireEvent.click(await screen.findByText('允许'))

    await waitFor(() => {
      expect(acpApiMocks.respondPermission).toHaveBeenCalledWith('project-a', 'sess-1', 'allow')
    })
  })

  it('取消当前轮携带 projectId 和 sessionId 并中止 fetch', async () => {
    let signal: AbortSignal | undefined
    globalThis.fetch = vi.fn((_url, init) => {
      signal = init?.signal as AbortSignal
      return new Promise(() => undefined)
    }) as unknown as typeof fetch

    render(<AcpSessionPanel {...defaultProps} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'long task' } })
    fireEvent.click(screen.getByText('发送').closest('button') as HTMLElement)
    fireEvent.click(await screen.findByText('取消'))

    await waitFor(() => {
      expect(acpApiMocks.cancelTurn).toHaveBeenCalledWith('project-a', 'sess-1')
    })
    expect(signal?.aborted).toBe(true)
  })

  it('generation 变化后旧流响应不得回写', async () => {
    let resolveFetch: ((value: unknown) => void) | undefined
    globalThis.fetch = vi.fn(() => new Promise((resolve) => {
      resolveFetch = resolve
    })) as unknown as typeof fetch

    const { rerender } = render(<AcpSessionPanel {...defaultProps} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'old request' } })
    fireEvent.click(screen.getByText('发送').closest('button') as HTMLElement)
    await waitFor(() => expect(resolveFetch).toBeDefined())

    rerender(<AcpSessionPanel {...defaultProps} generation={2} />)
    await act(async () => {
      resolveFetch?.({
        ok: true,
        body: encodeSseFrames([sseFrame('text', { text: 'stale output' })]),
        json: async () => ({}),
      })
      await Promise.resolve()
    })

    expect(screen.queryByText('stale output')).not.toBeInTheDocument()
  })
})
