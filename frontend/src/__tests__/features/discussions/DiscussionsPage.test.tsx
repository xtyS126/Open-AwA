/**
 * DiscussionsPage 讨论任务主页面单元测试。
 *
 * 测试目标：
 *   - 列表渲染：标题、新建/刷新按钮、状态过滤器
 *   - 状态徽章：不同状态显示对应文案
 *   - 交互：点击新建按钮打开 modal、点击列表项选中、刷新调用 fetchList、过滤器切换
 *   - 空状态：列表为空显示 EmptyState
 *   - 路由参数：/discussions/:id 自动选中任务
 *
 * Mock：
 *   - @/shared/api/discussionsApi：所有 API 函数（避免真实网络请求）
 *   - @/features/discussions/components/DiscussionStream：避免 EventSource 依赖
 *   - @/shared/utils/logger：避免日志副作用
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import {
  RouterTestProvider as MemoryRouter,
  renderWithRouter,
} from '@/shared/routing/testing'
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import DiscussionsPage from '@/features/discussions/DiscussionsPage'
import { useDiscussionStore } from '@/features/discussions/store/discussionStore'
import type {
  DiscussionTaskDetail,
  DiscussionTaskListItem,
  DiscussionListResponse,
  DiscussionCreateResponse,
  DiscussionReviseResponse,
  DiscussionForceExecuteResponse,
} from '@/shared/api/discussionsApi'

// 提升的 mock 句柄
const apiMocks = vi.hoisted(() => ({
  listDiscussions: vi.fn(),
  getDiscussionDetail: vi.fn(),
  createDiscussion: vi.fn(),
  reviseDiscussion: vi.fn(),
  forceExecuteDiscussion: vi.fn(),
}))

// 使用 importActual 保留纯函数（groupVotesByRound 等），仅覆盖 API 调用函数
vi.mock('@/shared/api/discussionsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/discussionsApi')>()
  return {
    ...actual,
    listDiscussions: apiMocks.listDiscussions,
    getDiscussionDetail: apiMocks.getDiscussionDetail,
    createDiscussion: apiMocks.createDiscussion,
    reviseDiscussion: apiMocks.reviseDiscussion,
    forceExecuteDiscussion: apiMocks.forceExecuteDiscussion,
  }
})

// mock DiscussionStream 避免 EventSource 调用
vi.mock('@/features/discussions/components/DiscussionStream', () => ({
  default: ({ discussionId }: { discussionId: string }) =>
    <div data-testid="discussion-stream-mock" data-discussion-id={discussionId} />,
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}))

/** 构造列表项 mock 数据 */
function createMockListItem(
  overrides: Partial<DiscussionTaskListItem> = {}
): DiscussionTaskListItem {
  return {
    id: 'task-1',
    title: '测试任务',
    status: 'discussing',
    round: 1,
    max_rounds: 3,
    created_at: '2026-01-01T00:00:00Z',
    vote_summary: {},
    ...overrides,
  }
}

/** 构造详情 mock 数据（默认 completed 状态避免触发 SSE 订阅） */
function createMockTaskDetail(
  overrides: Partial<DiscussionTaskDetail> = {}
): DiscussionTaskDetail {
  return {
    id: 'task-1',
    title: '测试任务详情',
    status: 'completed',
    round: 1,
    max_rounds: 3,
    created_at: '2026-01-01T00:00:00Z',
    vote_summary: {},
    description: '这是一个测试任务描述',
    proposed_action: { type: 'plugin_command', payload: { command: 'echo' } },
    context: {},
    completed_at: null,
    votes: [],
    ...overrides,
  }
}

/** 默认空列表响应 */
function emptyListResponse(): DiscussionListResponse {
  return { items: [], total: 0, page: 1, page_size: 20 }
}

describe('DiscussionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 重置 store 状态（保留 actions）
    useDiscussionStore.setState({
      list: [],
      total: 0,
      page: 1,
      pageSize: 20,
      statusFilter: 'all',
      selectedTask: null,
      isLoadingList: false,
      isLoadingDetail: false,
      isSubmitting: false,
      error: null,
      isCreateModalOpen: false,
    })
    // 默认 mock：列表返回空，详情返回 completed 任务
    apiMocks.listDiscussions.mockResolvedValue(emptyListResponse())
    apiMocks.getDiscussionDetail.mockResolvedValue(createMockTaskDetail())
    apiMocks.createDiscussion.mockResolvedValue({
      discussion_id: 'new-1',
      status: 'created',
    } as DiscussionCreateResponse)
    apiMocks.reviseDiscussion.mockResolvedValue({
      ...createMockTaskDetail(),
      discussion_id: 'task-1',
      status: 'discussing',
      round: 2,
    } as DiscussionReviseResponse)
    apiMocks.forceExecuteDiscussion.mockResolvedValue({
      discussion_id: 'task-1',
      status: 'executing',
    } as DiscussionForceExecuteResponse)
  })

  afterEach(() => {
    cleanup()
  })

  describe('列表渲染', () => {
    it('renders page title and create button', async () => {
      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      // 标题
      expect(screen.getByText('讨论任务')).toBeInTheDocument()
      // 新建按钮（aria-label）
      expect(screen.getByRole('button', { name: '新建讨论' })).toBeInTheDocument()
      // 刷新按钮
      expect(screen.getByRole('button', { name: '刷新' })).toBeInTheDocument()
      // 状态过滤器
      expect(screen.getByRole('tab', { name: '全部' })).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: '进行中' })).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: '已完成' })).toBeInTheDocument()

      await waitFor(() => {
        expect(apiMocks.listDiscussions).toHaveBeenCalled()
      })
    })

    it('renders task list items', async () => {
      apiMocks.listDiscussions.mockResolvedValue({
        items: [
          createMockListItem({ id: 't1', title: '任务一' }),
          createMockListItem({ id: 't2', title: '任务二', status: 'completed' }),
          createMockListItem({ id: 't3', title: '任务三', status: 'failed' }),
        ],
        total: 3,
        page: 1,
        page_size: 20,
      })

      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('任务一')).toBeInTheDocument()
        expect(screen.getByText('任务二')).toBeInTheDocument()
        expect(screen.getByText('任务三')).toBeInTheDocument()
      })
    })

    it('renders empty state when no tasks', async () => {
      apiMocks.listDiscussions.mockResolvedValue(emptyListResponse())

      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('暂无讨论任务')).toBeInTheDocument()
      })
    })

    it('shows loading state', async () => {
      // 使用可控 Promise 模拟加载中
      let resolveListPromise!: (value: DiscussionListResponse) => void
      apiMocks.listDiscussions.mockImplementation(
        () =>
          new Promise<DiscussionListResponse>((resolve) => {
            resolveListPromise = resolve
          })
      )

      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      // 等待 fetchList 设置 isLoadingList=true
      await waitFor(() => {
        expect(screen.getByText('加载中...')).toBeInTheDocument()
      })

      // 释放 Promise 避免悬挂
      resolveListPromise(emptyListResponse())
    })

    it('shows error state', async () => {
      apiMocks.listDiscussions.mockRejectedValue(new Error('Network error'))

      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        const alert = screen.getByRole('alert')
        expect(alert).toBeInTheDocument()
      })
    })
  })

  describe('状态徽章', () => {
    const statusCases: Array<{ status: DiscussionTaskListItem['status']; label: string }> = [
      { status: 'created', label: '已创建' },
      { status: 'discussing', label: '讨论中' },
      { status: 'pending_approval', label: '待审批' },
      { status: 'approved', label: '已通过' },
      { status: 'rejected', label: '已拒绝' },
      { status: 'executing', label: '执行中' },
      { status: 'completed', label: '已完成' },
      { status: 'failed', label: '失败' },
    ]

    statusCases.forEach(({ status, label }) => {
      it(`renders correct status badge for ${status}`, async () => {
        apiMocks.listDiscussions.mockResolvedValue({
          items: [createMockListItem({ id: 't1', title: `任务-${status}`, status })],
          total: 1,
          page: 1,
          page_size: 20,
        })

        render(
          <MemoryRouter initialEntries={['/discussions']}>
            <DiscussionsPage />
          </MemoryRouter>
        )

        await waitFor(() => {
          expect(screen.getByText(label)).toBeInTheDocument()
        })
      })
    })

    it('renders round number', async () => {
      apiMocks.listDiscussions.mockResolvedValue({
        items: [createMockListItem({ id: 't1', title: '任务', round: 2, max_rounds: 5 })],
        total: 1,
        page: 1,
        page_size: 20,
      })

      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        // 第 2 轮 / 5
        expect(screen.getByText(/第 2 轮/)).toBeInTheDocument()
      })
    })
  })

  describe('交互', () => {
    it('clicking create button opens modal', async () => {
      // 提供一个任务避免 EmptyState 也渲染新建按钮造成选择歧义
      apiMocks.listDiscussions.mockResolvedValue({
        items: [createMockListItem({ id: 't1', title: '占位任务' })],
        total: 1,
        page: 1,
        page_size: 20,
      })

      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('占位任务')).toBeInTheDocument()
      })

      // 初始时 modal 未显示
      expect(screen.queryByRole('dialog', { name: '新建讨论' })).not.toBeInTheDocument()

      // 点击工具栏新建按钮
      fireEvent.click(screen.getByRole('button', { name: '新建讨论' }))

      // modal 出现
      await waitFor(() => {
        expect(screen.getByRole('dialog', { name: '新建讨论' })).toBeInTheDocument()
      })
    })

    it('clicking task item selects it', async () => {
      apiMocks.listDiscussions.mockResolvedValue({
        items: [createMockListItem({ id: 'task-xyz', title: '可点击任务' })],
        total: 1,
        page: 1,
        page_size: 20,
      })

      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('可点击任务')).toBeInTheDocument()
      })

      // 点击任务项
      fireEvent.click(screen.getByText('可点击任务'))

      // 验证调用了 getDiscussionDetail
      await waitFor(() => {
        expect(apiMocks.getDiscussionDetail).toHaveBeenCalledWith('task-xyz')
      })
    })

    it('clicking refresh button calls fetchList', async () => {
      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      // 等待初始加载完成
      await waitFor(() => {
        expect(apiMocks.listDiscussions).toHaveBeenCalledTimes(1)
      })

      // 点击刷新
      fireEvent.click(screen.getByRole('button', { name: '刷新' }))

      // 验证再次调用了 listDiscussions
      await waitFor(() => {
        expect(apiMocks.listDiscussions).toHaveBeenCalledTimes(2)
      })
    })

    it('changing status filter updates store', async () => {
      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(apiMocks.listDiscussions).toHaveBeenCalledTimes(1)
      })

      // 点击「进行中」过滤器
      fireEvent.click(screen.getByRole('tab', { name: '进行中' }))

      // 切换过滤器会触发 fetchList（statusFilter 变更 -> setStatusFilter -> fetchList）
      await waitFor(() => {
        expect(apiMocks.listDiscussions).toHaveBeenCalledTimes(2)
      })

      // 验证 store 的 statusFilter 已更新
      expect(useDiscussionStore.getState().statusFilter).toBe('in_progress')
    })
  })

  describe('空状态', () => {
    it('shows empty detail panel when no task selected', async () => {
      apiMocks.listDiscussions.mockResolvedValue(emptyListResponse())

      render(
        <MemoryRouter initialEntries={['/discussions']}>
          <DiscussionsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('请选择一个讨论任务查看详情')).toBeInTheDocument()
      })
    })

    it('selects task by url param', async () => {
      renderWithRouter(<DiscussionsPage />, {
        initialEntry: '/discussions/task-from-url',
        routePath: '/discussions/$id',
      })

      // 路由参数触发 selectTask -> getDiscussionDetail
      await waitFor(() => {
        expect(apiMocks.getDiscussionDetail).toHaveBeenCalledWith('task-from-url')
      })
    })
  })
})
