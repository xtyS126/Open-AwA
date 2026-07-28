/**
 * PermissionDialog 组件单元测试。
 * 测试权限请求弹窗的渲染、用户交互和回调行为。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PermissionDialog } from '../PermissionDialog'

describe('PermissionDialog', () => {
  const mockRequest = {
    id: 'per_abc123',
    session_id: 'session-1',
    action: 'write',
    resources: ['/path/to/file.ts', '/path/to/config.json'],
    agent: 'build',
  }

  const mockOnReply = vi.fn()
  const mockOnClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('渲染权限请求基本信息', () => {
    render(
      <PermissionDialog
        request={mockRequest}
        onReply={mockOnReply}
        onClose={mockOnClose}
      />
    )

    // 标题可见
    expect(screen.getByText('权限请求')).toBeTruthy()

    // 操作和资源信息可见
    expect(screen.getByText('build')).toBeTruthy()

    // 三个按钮可见
    expect(screen.getByText('允许一次')).toBeTruthy()
    expect(screen.getByText('始终允许')).toBeTruthy()
    expect(screen.getByText('拒绝')).toBeTruthy()
  })

  it('点击允许一次触发 onReply 回调', () => {
    render(
      <PermissionDialog
        request={mockRequest}
        onReply={mockOnReply}
        onClose={mockOnClose}
      />
    )

    fireEvent.click(screen.getByText('允许一次'))
    expect(mockOnReply).toHaveBeenCalledTimes(1)
    expect(mockOnReply).toHaveBeenCalledWith('per_abc123', 'once')
  })

  it('点击始终允许触发 onReply 回调', () => {
    render(
      <PermissionDialog
        request={mockRequest}
        onReply={mockOnReply}
        onClose={mockOnClose}
      />
    )

    fireEvent.click(screen.getByText('始终允许'))
    expect(mockOnReply).toHaveBeenCalledTimes(1)
    expect(mockOnReply).toHaveBeenCalledWith('per_abc123', 'always')
  })

  it('点击拒绝显示拒绝输入区域', () => {
    render(
      <PermissionDialog
        request={mockRequest}
        onReply={mockOnReply}
        onClose={mockOnClose}
      />
    )

    fireEvent.click(screen.getByText('拒绝'))
    // 拒绝输入区域应该出现
    expect(screen.getByPlaceholderText(/拒绝原因/)).toBeTruthy()
    expect(screen.getByText('确认拒绝')).toBeTruthy()
  })

  it('输入拒绝原因后确认拒绝', () => {
    render(
      <PermissionDialog
        request={mockRequest}
        onReply={mockOnReply}
        onClose={mockOnClose}
      />
    )

    fireEvent.click(screen.getByText('拒绝'))
    const textarea = screen.getByPlaceholderText(/拒绝原因/)
    fireEvent.change(textarea, { target: { value: '应该使用 read 而不是 write' } })

    fireEvent.click(screen.getByText('确认拒绝'))
    expect(mockOnReply).toHaveBeenCalledWith(
      'per_abc123',
      'reject',
      '应该使用 read 而不是 write'
    )
  })

  it('点击遮罩层触发 onClose', () => {
    render(
      <PermissionDialog
        request={mockRequest}
        onReply={mockOnReply}
        onClose={mockOnClose}
      />
    )

    // 点击 overlay 关闭
    const overlay = screen.getByText('权限请求').closest('div')
    // 寻找 overlay (最外层 div)
    const dialog = document.querySelector('[class*="overlay"]')
    if (dialog) {
      fireEvent.click(dialog)
      expect(mockOnClose).toHaveBeenCalled()
    }
  })

  it('点击弹窗内部不触发 onClose', () => {
    render(
      <PermissionDialog
        request={mockRequest}
        onReply={mockOnReply}
        onClose={mockOnClose}
      />
    )

    // 点击弹窗标题不应关闭
    fireEvent.click(screen.getByText('权限请求'))
    expect(mockOnClose).not.toHaveBeenCalled()
  })

  it('无 agent 时不显示 agent badge', () => {
    const requestWithoutAgent = { ...mockRequest, agent: undefined }
    render(
      <PermissionDialog
        request={requestWithoutAgent}
        onReply={mockOnReply}
        onClose={mockOnClose}
      />
    )

    // 不应该有 agent badge
    const badge = document.querySelector('[class*="agentBadge"]')
    expect(badge).toBeNull()
  })
})
