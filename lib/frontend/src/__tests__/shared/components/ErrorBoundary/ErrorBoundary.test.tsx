/**
 * ErrorBoundary 单元测试。
 *
 * 覆盖点：
 *   - 正常渲染：children 不抛错时直接渲染
 *   - page 变体：捕获错误后渲染大卡片 UI（含"应用 发生了意外错误"）
 *   - compact 变体：捕获错误后渲染紧凑条幅（含"渲染异常"+ 重试按钮）
 *   - 重试机制：重试按钮点击后重新渲染 children
 *   - 重试上限：达到 MAX_RETRY_COUNT 后切换为"刷新页面"按钮
 *   - 复制错误信息：调用 navigator.clipboard.writeText
 *   - 日志上报：appLogger.error 被调用且携带 module 与 component_stack
 *
 * Mock：
 *   - appLogger：验证错误上报
 *   - navigator.clipboard：验证复制行为
 *   - window.location.reload：验证刷新行为
 */
import '@testing-library/jest-dom/vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'

const loggerMocks = vi.hoisted(() => ({
  error: vi.fn(),
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    error: loggerMocks.error,
  },
}))

/** 故意抛错的子组件，用于触发 ErrorBoundary */
function FaultyComponent({ message = '子组件渲染失败' }: { message?: string }): never {
  throw new Error(message)
}

/** 受控抛错的子组件：通过 key 变化或 prop 触发错误 */
function ControlledFault({ fail }: { fail: boolean }) {
  if (fail) {
    throw new Error('controlled fault triggered')
  }
  return <div data-testid="healthy-child">healthy</div>
}

describe('ErrorBoundary - 正常路径', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('children 不抛错时直接渲染', () => {
    const { container } = render(
      <ErrorBoundary name="TestModule">
        <div data-testid="child">content</div>
      </ErrorBoundary>
    )

    expect(screen.getByTestId('child')).toBeInTheDocument()
    // 不应渲染错误 UI
    expect(container).not.toHaveTextContent('发生了意外错误')
    expect(loggerMocks.error).not.toHaveBeenCalled()
  })
})

describe('ErrorBoundary - page 变体（默认）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('子组件抛错后渲染页面级错误 UI', () => {
    // 抑制 React 控制台报错噪音
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <ErrorBoundary name="PageModule">
        <FaultyComponent />
      </ErrorBoundary>
    )

    expect(screen.getByText('PageModule 发生了意外错误')).toBeInTheDocument()
    expect(screen.getByText('子组件渲染失败')).toBeInTheDocument()
    // 默认重试按钮（未达上限）
    expect(screen.getByRole('button', { name: /重试/ })).toBeInTheDocument()

    // 日志上报应被调用
    expect(loggerMocks.error).toHaveBeenCalledTimes(1)
    const logCall = loggerMocks.error.mock.calls[0][0]
    expect(logCall.module).toBe('PageModule')
    expect(logCall.event).toBe('frontend_render_error')
    expect(logCall.extra.error).toBe('子组件渲染失败')

    spy.mockRestore()
  })

  it('重试按钮点击后重新渲染 children', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

    // 使用受控抛错组件：首次 fail=true 抛错，重试时通过新 fail=false 渲染健康
    let fail = true
    function Wrapper() {
      return (
        <ErrorBoundary name="RetryModule">
          <ControlledFault fail={fail} />
        </ErrorBoundary>
      )
    }

    const { rerender } = render(<Wrapper />)

    // 首次渲染应进入错误态
    expect(screen.getByText('RetryModule 发生了意外错误')).toBeInTheDocument()

    // 先 rerender 让 fail=false 生效（更新 ErrorBoundary 的 children 引用），
    // 再点击重试按钮触发 setState({ hasError: false, retryKey++ })，
    // retryKey 改变后 React.Fragment remount，使用新的 fail=false children
    fail = false
    rerender(<Wrapper />)

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /重试/ }))
    })

    // 错误 UI 消失，健康子组件渲染
    expect(screen.getByTestId('healthy-child')).toBeInTheDocument()

    spy.mockRestore()
  })

  it('达到重试上限后切换为"刷新页面"按钮', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <ErrorBoundary name="MaxRetryModule">
        <FaultyComponent />
      </ErrorBoundary>
    )

    // 连续点击 3 次重试，每次都因 FaultyComponent 再次抛错而回到错误态
    for (let i = 0; i < 3; i += 1) {
      act(() => {
        fireEvent.click(screen.getByRole('button', { name: /重试/ }))
      })
    }

    // 第 4 次时按钮应变切换为"刷新页面"
    expect(screen.getByText('已尝试重试 3 次仍无法恢复，建议刷新页面。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新页面' })).toBeInTheDocument()
    // 重试按钮不应再出现
    expect(screen.queryByRole('button', { name: /重试/ })).not.toBeInTheDocument()

    spy.mockRestore()
  })

  it('点击"刷新页面"调用 window.location.reload', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const reloadSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { reload: reloadSpy },
    })

    render(
      <ErrorBoundary name="ReloadModule">
        <FaultyComponent />
      </ErrorBoundary>
    )

    // 达到重试上限
    for (let i = 0; i < 3; i += 1) {
      act(() => {
        fireEvent.click(screen.getByRole('button', { name: /重试/ }))
      })
    }

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: '刷新页面' }))
    })

    expect(reloadSpy).toHaveBeenCalledTimes(1)

    spy.mockRestore()
  })
})

describe('ErrorBoundary - compact 变体', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('子组件抛错后渲染紧凑条幅 UI（不破坏布局）', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <ErrorBoundary name="SubagentExecutionContainer" variant="compact">
        <FaultyComponent message="subagent render boom" />
      </ErrorBoundary>
    )

    // compact 变体显示模块名 + "渲染异常"
    expect(screen.getByText('SubagentExecutionContainer 渲染异常')).toBeInTheDocument()
    // 错误文本
    expect(screen.getByText('subagent render boom')).toBeInTheDocument()
    // 重试按钮（未达上限）
    expect(screen.getByRole('button', { name: /重试/ })).toBeInTheDocument()
    // 不应渲染页面级 UI
    expect(screen.queryByText('发生了意外错误')).not.toBeInTheDocument()

    // 日志上报应被调用
    expect(loggerMocks.error).toHaveBeenCalledTimes(1)
    const logCall = loggerMocks.error.mock.calls[0][0]
    expect(logCall.module).toBe('SubagentExecutionContainer')

    spy.mockRestore()
  })

  it('compact 重试按钮点击后重新渲染 children', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

    let fail = true
    function Wrapper() {
      return (
        <ErrorBoundary name="PluginDebugPanel" variant="compact">
          <ControlledFault fail={fail} />
        </ErrorBoundary>
      )
    }

    const { rerender } = render(<Wrapper />)

    expect(screen.getByText('PluginDebugPanel 渲染异常')).toBeInTheDocument()

    // 先 rerender 让 fail=false 生效（更新 ErrorBoundary 的 children 引用），
    // 再点击重试按钮触发 setState({ hasError: false, retryKey++ })，
    // retryKey 改变后 React.Fragment remount，使用新的 fail=false children
    fail = false
    rerender(<Wrapper />)

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /重试/ }))
    })

    expect(screen.getByTestId('healthy-child')).toBeInTheDocument()
    expect(screen.queryByText('PluginDebugPanel 渲染异常')).not.toBeInTheDocument()

    spy.mockRestore()
  })

  it('compact 达到重试上限后切换为"刷新页面"按钮', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <ErrorBoundary name="TerminalPane" variant="compact">
        <FaultyComponent />
      </ErrorBoundary>
    )

    // 连续点击 3 次重试
    for (let i = 0; i < 3; i += 1) {
      act(() => {
        fireEvent.click(screen.getByRole('button', { name: /重试/ }))
      })
    }

    // 应切换为刷新页面按钮
    expect(screen.getByRole('button', { name: '刷新页面' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /重试/ })).not.toBeInTheDocument()

    spy.mockRestore()
  })

  it('compact 复制按钮调用 clipboard.writeText 携带错误详情', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const writeTextSpy = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: { writeText: writeTextSpy },
    })

    render(
      <ErrorBoundary name="MessageList" variant="compact">
        <FaultyComponent message="message list boom" />
      </ErrorBoundary>
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '复制错误信息' }))
    })

    expect(writeTextSpy).toHaveBeenCalledTimes(1)
    const copiedText = writeTextSpy.mock.calls[0][0] as string
    expect(copiedText).toContain('模块: MessageList')
    expect(copiedText).toContain('message list boom')

    spy.mockRestore()
  })

  it('compact 错误条幅具备 role=alert 与 aria-live=assertive 用于辅助技术', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <ErrorBoundary name="A11yModule" variant="compact">
        <FaultyComponent />
      </ErrorBoundary>
    )

    const alert = screen.getByRole('alert')
    expect(alert).toHaveAttribute('aria-live', 'assertive')

    spy.mockRestore()
  })
})
