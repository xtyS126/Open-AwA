/**
 * PermissionDialog 权限审批弹窗组件单元测试。
 *
 * 覆盖点：
 *   - 权限详情渲染（工具名 / kind 徽章 / 目标 / 动作 / 命令 / 影响路径）
 *   - 选项列表渲染与点击回调
 *   - 取消按钮回调
 *   - 选中后 loading 状态显示
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, it, expect, vi } from 'vitest'
import PermissionDialog from '@/features/vibe-coding/components/PermissionDialog'
import type { SuspendedPermission } from '@/shared/api/acpApi'

/** 构造测试用权限对象 */
function buildPermission(overrides: Partial<SuspendedPermission> = {}): SuspendedPermission {
  return {
    tool_name: 'bash',
    tool_kind: 'execute',
    target: '/tmp/work',
    action: 'run',
    summary: '即将执行 shell 命令',
    command: 'rm -rf /tmp/work',
    paths: ['/tmp/work/a.txt', '/tmp/work/b.txt'],
    options: [
      { id: 'allow_once', label: '允许一次', kind: 'allow' },
      { id: 'allow_always', label: '永久允许', kind: 'allow', hint: '后续不再询问' },
      { id: 'deny', label: '拒绝', kind: 'deny' },
    ],
    ...overrides,
  }
}

describe('PermissionDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders permission details correctly', () => {
    const onSelect = vi.fn().mockResolvedValue(undefined)
    const onCancel = vi.fn()
    const permission = buildPermission()

    render(
      <PermissionDialog permission={permission} onSelect={onSelect} onCancel={onCancel} />
    )

    // 工具名与 kind 徽章
    expect(screen.getByText('bash')).toBeInTheDocument()
    expect(screen.getByText('execute')).toBeInTheDocument()
    // 目标与动作
    expect(screen.getByText('/tmp/work')).toBeInTheDocument()
    expect(screen.getByText('run')).toBeInTheDocument()
    // 命令展示
    expect(screen.getByText('rm -rf /tmp/work')).toBeInTheDocument()
    // 影响路径
    expect(screen.getByText('/tmp/work/a.txt')).toBeInTheDocument()
    expect(screen.getByText('/tmp/work/b.txt')).toBeInTheDocument()
  })

  it('renders options list', () => {
    const onSelect = vi.fn().mockResolvedValue(undefined)
    const onCancel = vi.fn()
    const permission = buildPermission()

    render(
      <PermissionDialog permission={permission} onSelect={onSelect} onCancel={onCancel} />
    )

    // 三个选项标签都应渲染
    expect(screen.getByText('允许一次')).toBeInTheDocument()
    expect(screen.getByText('永久允许')).toBeInTheDocument()
    // 选项 hint
    expect(screen.getByText('后续不再询问')).toBeInTheDocument()
    // "拒绝" 既是选项也是取消按钮文案，应出现多次
    expect(screen.getAllByText('拒绝').length).toBeGreaterThanOrEqual(2)
  })

  it('calls onSelect with option id when option clicked', async () => {
    const onSelect = vi.fn().mockResolvedValue(undefined)
    const onCancel = vi.fn()
    const permission = buildPermission()

    render(
      <PermissionDialog permission={permission} onSelect={onSelect} onCancel={onCancel} />
    )

    // 点击 "允许一次" 选项按钮（取按钮内文案定位）
    const optionButton = screen.getByText('允许一次').closest('button')
    expect(optionButton).not.toBeNull()
    fireEvent.click(optionButton as HTMLElement)

    await waitFor(() => {
      expect(onSelect).toHaveBeenCalledTimes(1)
      expect(onSelect).toHaveBeenCalledWith('allow_once')
    })
  })

  it('calls onCancel when cancel button clicked', () => {
    const onSelect = vi.fn().mockResolvedValue(undefined)
    const onCancel = vi.fn()
    const permission = buildPermission()

    render(
      <PermissionDialog permission={permission} onSelect={onSelect} onCancel={onCancel} />
    )

    // footer 取消按钮文案为 "拒绝"，与选项中的 "拒绝" 同名，需定位 footer 内的按钮
    // footer 是 Modal 末尾区域；通过 button 文案集合定位最后一个 "拒绝" 按钮
    const denyButtons = screen.getAllByText('拒绝').map((el) => el.closest('button'))
    // 最后一个 "拒绝" 是 footer 的取消按钮（选项列表在前，footer 在后）
    const footerCancelBtn = denyButtons[denyButtons.length - 1]
    expect(footerCancelBtn).not.toBeNull()
    fireEvent.click(footerCancelBtn as HTMLElement)

    expect(onCancel).toHaveBeenCalledTimes(1)
    // 选中选项的回调不应被调用
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('shows loading state after option selected', async () => {
    // 让 onSelect 保持 pending 状态，便于观察 loading 文案
    let resolveSelect: (() => void) | null = null
    const onSelect = vi.fn().mockImplementation(
      () => new Promise<void>((resolve) => {
        resolveSelect = resolve
      })
    )
    const onCancel = vi.fn()
    const permission = buildPermission()

    render(
      <PermissionDialog permission={permission} onSelect={onSelect} onCancel={onCancel} />
    )

    const optionButton = screen.getByText('允许一次').closest('button')
    fireEvent.click(optionButton as HTMLElement)

    // 点击后应显示 "处理中..." 提示（至少一处：选中的选项内 hint 或 footer 取消按钮文案）
    await waitFor(() => {
      expect(screen.getAllByText('处理中...').length).toBeGreaterThan(0)
    })
    // footer 取消按钮在提交期间文案变为 "处理中..." 且被禁用
    const processingButtons = screen.getAllByText('处理中...').map((el) => el.closest('button'))
    const disabledFooterBtn = processingButtons.find((btn) => btn?.disabled === true)
    expect(disabledFooterBtn).toBeDefined()

    // 释放 pending Promise，避免悬挂的异步状态污染后续用例
    if (resolveSelect) {
      resolveSelect()
    }
    await waitFor(() => expect(onSelect).toHaveBeenCalledTimes(1))
  })
})
