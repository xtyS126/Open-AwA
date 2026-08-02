/**
 * ScheduledTasksPage 测试套件 — 定时任务管理页面的渲染和交互测试
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ScheduledTasksPage from '@/features/scheduledTasks/ScheduledTasksPage'
import { RouterTestProvider as BrowserRouter } from '@/shared/routing/testing'
import type { ScheduledTask, ScheduledTaskExecution } from '@/shared/api/api'

const { getAllMock, getExecutionsMock } = vi.hoisted(() => ({
  getAllMock: vi.fn(),
  getExecutionsMock: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  scheduledTasksAPI: {
    getAll: getAllMock,
    getOne: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    cancel: vi.fn(),
    getExecutions: getExecutionsMock,
    getPluginCommands: vi.fn().mockResolvedValue({ data: [] }),
  },
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}))

vi.mock('@/features/scheduledTasks/components/PluginCommandSelector', () => ({
  default: () => <div data-testid="plugin-command-selector">PluginCommandSelector</div>,
}))

vi.mock('@/features/scheduledTasks/components/CronExpressionBuilder', () => ({
  default: () => <div data-testid="cron-expression-builder">CronExpressionBuilder</div>,
}))

vi.mock('@/features/scheduledTasks/components/TaskParameterPanel', () => ({
  default: () => <div data-testid="task-parameter-panel">TaskParameterPanel</div>,
}))

vi.mock('@/features/scheduledTasks/components/TaskLogViewer', () => ({
  default: () => <div data-testid="task-log-viewer">TaskLogViewer</div>,
}))

vi.mock('@/features/scheduledTasks/components/TaskTemplateManager', () => ({
  default: () => <div data-testid="task-template-manager">TaskTemplateManager</div>,
}))

function createMockTask(overrides: Partial<ScheduledTask> = {}): ScheduledTask {
  return {
    id: 1,
    user_id: 'test-user',
    title: '测试定时AI任务',
    prompt: '帮我总结今天的新闻',
    scheduled_at: '2026-05-16T09:00:00Z',
    status: 'pending',
    provider: null,
    model: null,
    task_type: 'ai',
    plugin_name: null,
    command_name: null,
    command_params: undefined,
    last_error_message: null,
    task_metadata: {},
    created_at: '2026-05-15T08:00:00Z',
    updated_at: '2026-05-15T08:00:00Z',
    completed_at: null,
    cancelled_at: null,
    next_execution_at: '2026-05-16T09:00:00Z',
    is_daily: false,
    cron_expression: null,
    weekdays: null,
    daily_time: null,
    ...overrides,
  }
}

function createEmptyExecutions(): ScheduledTaskExecution[] {
  return []
}

describe('ScheduledTasksPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getAllMock.mockReset()
    getExecutionsMock.mockReset()
  })

  // ============ 加载状态测试 ============

  it('渲染加载状态时显示加载提示', () => {
    getAllMock.mockImplementationOnce(
      () => new Promise(() => { /* 保持加载中 */ })
    )
    getExecutionsMock.mockImplementationOnce(
      () => new Promise(() => { /* 保持加载中 */ })
    )

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    expect(screen.getByText('正在加载定时任务...')).toBeInTheDocument()
  })

  // ============ 基本渲染测试 ============

  it('数据加载完成后渲染页面标题和标签页', async () => {
    getAllMock.mockResolvedValueOnce({ data: [] })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('定时任务')).toBeInTheDocument()
    })

    expect(screen.getByText('AI智能任务')).toBeInTheDocument()
    expect(screen.getByText('插件命令任务')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新' })).toBeInTheDocument()
  })

  it('空任务列表时显示空状态提示', async () => {
    getAllMock.mockResolvedValueOnce({ data: [] })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('暂无AI智能任务')).toBeInTheDocument()
    })
  })

  // ============ 任务列表渲染测试 ============

  it('加载成功后正确渲染任务列表', async () => {
    const mockTasks: ScheduledTask[] = [
      createMockTask({ id: 1, title: '每日新闻摘要', status: 'pending' }),
      createMockTask({ id: 2, title: '代码审查任务', status: 'completed', completed_at: '2026-05-15T10:00:00Z' }),
    ]

    getAllMock.mockResolvedValueOnce({ data: mockTasks })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('每日新闻摘要')).toBeInTheDocument()
      expect(screen.getByText('代码审查任务')).toBeInTheDocument()
    })

    // 任务队列计数
    expect(screen.getByText('任务队列 (2)')).toBeInTheDocument()

    // 任务卡片上的状态标记 — 使用 getAllByText 因为统计区域也有
    const pendingElements = screen.getAllByText('待执行')
    expect(pendingElements.length).toBeGreaterThanOrEqual(1)

    // completed 状态映射为 "已完成"，统计区域也会显示
    const completedElements = screen.getAllByText('已完成')
    expect(completedElements.length).toBeGreaterThanOrEqual(1)
  })

  it('渲染任务的错误信息', async () => {
    const mockTasks: ScheduledTask[] = [
      createMockTask({
        id: 1,
        title: '失败任务',
        status: 'failed',
        last_error_message: 'LLM 调用超时',
      }),
    ]

    getAllMock.mockResolvedValueOnce({ data: mockTasks })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('LLM 调用超时')).toBeInTheDocument()
    })

    // failed 状态映射为 "执行失败"
    expect(screen.getByText('执行失败')).toBeInTheDocument()
  })

  // ============ 标签切换测试 ============

  it('点击插件命令任务标签切换到插件任务视图', async () => {
    getAllMock.mockResolvedValueOnce({ data: [] })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('暂无AI智能任务')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('插件命令任务'))

    await waitFor(() => {
      expect(screen.getByTestId('plugin-command-selector')).toBeInTheDocument()
    })
  })

  it('点击 AI 智能任务标签切换回 AI 任务视图', async () => {
    getAllMock.mockResolvedValueOnce({ data: [] })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('暂无AI智能任务')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('插件命令任务'))
    await waitFor(() => {
      expect(screen.getByTestId('plugin-command-selector')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('AI智能任务'))
    await waitFor(() => {
      expect(screen.getByText('暂无AI智能任务')).toBeInTheDocument()
    })
  })

  // ============ 错误处理测试 ============

  it('加载失败时在错误横幅中显示错误信息', async () => {
    getAllMock.mockRejectedValueOnce({
      response: { data: { detail: '服务暂时不可用' } },
    })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      // 错误消息显示在 error-banner 中
      const errorBanner = screen.getByText('服务暂时不可用')
      expect(errorBanner).toBeInTheDocument()
    })
  })

  it('加载失败且无 detail 时显示默认错误消息', async () => {
    getAllMock.mockRejectedValueOnce(new Error('网络连接失败'))
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('网络连接失败')).toBeInTheDocument()
    })
  })

  it('刷新按钮可以在错误状态下点击重新加载', async () => {
    getAllMock.mockRejectedValueOnce({
      response: { data: { detail: '服务暂时不可用' } },
    })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('服务暂时不可用')).toBeInTheDocument()
    })

    // 点击刷新按钮重新加载
    getAllMock.mockResolvedValueOnce({ data: [] })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    fireEvent.click(screen.getByRole('button', { name: '刷新' }))

    await waitFor(() => {
      expect(screen.getByText('暂无AI智能任务')).toBeInTheDocument()
    })
  })

  // ============ 搜索功能测试 ============

  it('搜索框中输入内容时过滤任务', async () => {
    const mockTasks: ScheduledTask[] = [
      createMockTask({ id: 1, title: '新闻摘要任务', prompt: '总结新闻' }),
      createMockTask({ id: 2, title: '代码审查任务', prompt: '审查代码' }),
    ]

    getAllMock.mockResolvedValueOnce({ data: mockTasks })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('新闻摘要任务')).toBeInTheDocument()
      expect(screen.getByText('代码审查任务')).toBeInTheDocument()
    })

    const searchInput = screen.getByPlaceholderText('搜索任务...')
    fireEvent.change(searchInput, { target: { value: '代码' } })

    await waitFor(() => {
      expect(screen.getByText('代码审查任务')).toBeInTheDocument()
      expect(screen.queryByText('新闻摘要任务')).not.toBeInTheDocument()
    })
  })

  // ============ 状态过滤测试 ============

  it('通过状态过滤器筛选任务', async () => {
    const mockTasks: ScheduledTask[] = [
      createMockTask({ id: 1, title: '待执行任务', status: 'pending' }),
      createMockTask({ id: 2, title: '已完成任务', status: 'completed' }),
    ]

    getAllMock.mockResolvedValueOnce({ data: mockTasks })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('待执行任务')).toBeInTheDocument()
      expect(screen.getByText('已完成任务')).toBeInTheDocument()
    })

    const statusSelect = screen.getByRole('combobox')
    fireEvent.change(statusSelect, { target: { value: 'completed' } })

    await waitFor(() => {
      expect(screen.queryByText('待执行任务')).not.toBeInTheDocument()
      expect(screen.getByText('已完成任务')).toBeInTheDocument()
    })
  })

  // ============ 复选框选择测试 ============

  it('任务卡片的复选框可以选中和取消', async () => {
    const mockTasks: ScheduledTask[] = [
      createMockTask({ id: 1, title: '选择任务' }),
    ]

    getAllMock.mockResolvedValueOnce({ data: mockTasks })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('选择任务')).toBeInTheDocument()
    })

    const checkbox = screen.getByRole('checkbox')
    expect(checkbox).not.toBeChecked()

    fireEvent.click(checkbox)
    expect(checkbox).toBeChecked()

    fireEvent.click(checkbox)
    expect(checkbox).not.toBeChecked()
  })

  // ============ 每日任务渲染测试 ============

  it('每日循环任务渲染 cron 表达式', async () => {
    const mockTasks: ScheduledTask[] = [
      createMockTask({
        id: 1,
        title: '每日报告',
        is_daily: true,
        cron_expression: '0 9 * * 1-5',
      }),
    ]

    getAllMock.mockResolvedValueOnce({ data: mockTasks })
    getExecutionsMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><ScheduledTasksPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('每日报告')).toBeInTheDocument()
      expect(screen.getByText('0 9 * * 1-5')).toBeInTheDocument()
    })
  })
})
