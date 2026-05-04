import { render, screen, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { SubagentContainer } from '@/features/chat/components/SubagentContainer'

const mockAddToast = vi.fn()

vi.mock('@/shared/components/Toast', () => ({
  useToast: () => ({
    addToast: mockAddToast,
    ToastContainer: () => null,
  }),
}))

describe('SubagentContainer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  const defaultProps = {
    agentId: 'agent-1',
    name: 'Test Agent',
    steps: [],
  }

  it('should render basic layout', () => {
    const { container } = render(
      <SubagentContainer
        {...defaultProps}
        status="running"
        content="Log line 1"
      />
    )
    expect(screen.getByText('Test Agent')).toBeInTheDocument()
    expect(container.querySelector('div[class*="running"]')).toBeInTheDocument()
  })

  it('should trigger toast on error status', () => {
    const { container } = render(
      <SubagentContainer
        {...defaultProps}
        status="error"
        content="Error line"
      />
    )
    expect(mockAddToast).toHaveBeenCalledWith('Subagent Test Agent 执行失败', 'error')
    expect(container.querySelector('div[class*="error"]')).toBeInTheDocument()
  })

  it('should trigger toast on non-zero exit code', () => {
    const { container } = render(
      <SubagentContainer
        {...defaultProps}
        status="completed"
        content="Error line"
        exitCode={1}
      />
    )
    expect(mockAddToast).toHaveBeenCalledWith('Subagent Test Agent 执行失败', 'error')
    expect(container.querySelector('div[class*="error"]')).toBeInTheDocument()
  })

  it('should trigger timeout error after 30s of no output', () => {
    const { rerender } = render(
      <SubagentContainer
        {...defaultProps}
        status="running"
        content="Log line 1"
      />
    )

    act(() => {
      vi.advanceTimersByTime(30000)
    })

    expect(mockAddToast).toHaveBeenCalledWith('Subagent Test Agent 执行失败', 'error')

    vi.clearAllMocks()
    rerender(
      <SubagentContainer
        {...defaultProps}
        status="running"
        content="Log line 1\nLog line 2"
      />
    )

    act(() => {
      vi.advanceTimersByTime(29000)
    })
    expect(mockAddToast).not.toHaveBeenCalled()
  })

  it('should truncate content exceeding 50000 characters', () => {
    const longContent = 'A'.repeat(50001)
    render(
      <SubagentContainer
        {...defaultProps}
        status="running"
        content={longContent}
      />
    )
    expect(screen.getByText(/日志过长，已截断/)).toBeInTheDocument()
  })

  it('should render step tree with icons', () => {
    const { container } = render(
      <SubagentContainer
        {...defaultProps}
        status="running"
        content=""
        steps={[
          { type: 'thought', label: 'Thought', timestamp: 1000 },
          { type: 'file_read', label: 'src/app.ts', timestamp: 2000 },
          { type: 'search', label: 'keyword', timestamp: 3000 },
          { type: 'tool_call', label: 'Tool: search', timestamp: 4000 },
          { type: 'generic', label: 'general message', timestamp: 5000 },
        ]}
      />
    )
    expect(screen.getByText('Thought')).toBeInTheDocument()
    expect(screen.getByText('src/app.ts')).toBeInTheDocument()
    expect(screen.getByText('keyword')).toBeInTheDocument()
    expect(screen.getByText('Tool: search')).toBeInTheDocument()
    expect(screen.getByText('general message')).toBeInTheDocument()
    expect(container.querySelector('div[class*="treeLine"]')).toBeInTheDocument()
    expect(container.querySelector('div[class*="stepConnector"]')).toBeInTheDocument()
  })

  it('should toggle expand/collapse on header click', () => {
    const { container } = render(
      <SubagentContainer
        {...defaultProps}
        status="running"
        content="Log line"
        steps={[{ type: 'thought', label: 'Thought', timestamp: 1000 }]}
      />
    )
    const header = container.querySelector('div[class*="header"]')
    expect(header).not.toBeNull()

    const treeBody = container.querySelector('div[class*="treeBodyExpanded"]')
    expect(treeBody).not.toBeNull()

    act(() => {
      header!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const treeBodyAfterCollapse = container.querySelector('div[class*="treeBodyExpanded"]')
    expect(treeBodyAfterCollapse).toBeNull()
  })
})
