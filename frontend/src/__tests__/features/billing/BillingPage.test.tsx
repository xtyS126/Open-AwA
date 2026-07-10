import '@testing-library/jest-dom/vitest'
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { beforeEach, describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import BillingPage from '@/features/billing/BillingPage'
import { BrowserRouter } from 'react-router-dom'
import { useAuthStore } from '@/shared/store/authStore'
import { BILLING_USAGE_UPDATED_EVENT } from '@/shared/events/billingEvents'

// 提升 mock 到顶层，确保 vi.mock 内可引用
const billingMocks = vi.hoisted(() => ({
  getCostStatistics: vi.fn(),
  getUsage: vi.fn(),
  getBudget: vi.fn(),
  getReport: vi.fn(),
}))

const syncModelCatalogMock = vi.hoisted(() => vi.fn())

vi.mock('@/features/billing/billingApi', () => ({
  billingAPI: billingMocks,
  syncModelCatalog: syncModelCatalogMock,
}))

// 每个测试独立的 QueryClient 实例，避免缓存污染
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // 关闭重试，避免失败测试等待过久
        retry: false,
        // 关闭 staleTime，确保每次 mount 都重新发起查询
        staleTime: 0,
        gcTime: 0,
      },
    },
  })
}

function renderWithQueryClient(ui: React.ReactNode) {
  const testQueryClient = createTestQueryClient()
  return {
    queryClient: testQueryClient,
    ...render(
      <QueryClientProvider client={testQueryClient}>
        <BrowserRouter>{ui}</BrowserRouter>
      </QueryClientProvider>,
    ),
  }
}

describe('BillingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 重置 auth store 到默认状态（未登录）
    useAuthStore.setState({ user: null, apiKey: null, isAuthenticated: false, isInitialized: false })

    billingMocks.getCostStatistics.mockResolvedValue({
      data: {
        period: 'monthly',
        period_start: '2026-04-01T00:00:00',
        period_end: '2026-04-30T00:00:00',
        total_cost: 0.2345,
        total_input_tokens: 1200,
        total_output_tokens: 800,
        total_calls: 4,
        by_model: [
          { provider: 'openai', model: 'gpt-4o-mini', input_tokens: 1200, output_tokens: 800, cost: 0.2345, call_count: 4 },
        ],
        by_content_type: {
          chat: { tokens: 2000, cost: 0.2345 },
        },
        trend: [
          { date: '2026-04-19', cost: 0.2345, input_tokens: 1200, output_tokens: 800 },
        ],
        currency: 'USD',
      },
    })
    billingMocks.getUsage.mockResolvedValue({
      data: {
        records: [
          {
            call_id: 'usage-1',
            user_id: 'user-1',
            session_id: 'session-1',
            provider: 'openai',
            model: 'gpt-4o-mini',
            content_type: 'chat',
            input_tokens: 1200,
            output_tokens: 800,
            input_cost: 0.1,
            output_cost: 0.1345,
            total_cost: 0.2345,
            currency: 'USD',
            cache_hit: false,
            duration_ms: 245,
            created_at: '2026-04-19T03:00:00',
          },
        ],
      },
    })
    billingMocks.getBudget.mockResolvedValue({ data: null })
    billingMocks.getReport.mockResolvedValue({ data: 'csv' })
    syncModelCatalogMock.mockReset()
  })

  it('renders billing data and sync status', async () => {
    renderWithQueryClient(<BillingPage />)
    expect(await screen.findByText('用量计费')).toBeInTheDocument()
    expect(await screen.findByText('已开启聊天用量联动')).toBeInTheDocument()
    expect(screen.getByText('gpt-4o-mini')).toBeInTheDocument()
  })

  it('receives billing usage update event and refreshes silently', async () => {
    renderWithQueryClient(<BillingPage />)

    await waitFor(() => expect(billingMocks.getCostStatistics).toHaveBeenCalledTimes(1))

    await act(async () => {
      window.dispatchEvent(new CustomEvent(BILLING_USAGE_UPDATED_EVENT, {
        detail: { callId: 'usage-2', provider: 'openai', model: 'gpt-4o-mini' },
      }))
    })

    // invalidateQueries 触发后台刷新，getCostStatistics 应被再次调用
    await waitFor(() => expect(billingMocks.getCostStatistics).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByText('已开启聊天用量联动')).toBeInTheDocument())
  })

  it('hides sync catalog button for non-admin users', async () => {
    // 非 admin 用户：设置 role 为普通用户
    useAuthStore.setState({ user: { username: 'user1', role: 'user' } })

    renderWithQueryClient(<BillingPage />)
    await screen.findByText('用量计费')

    // 同步按钮不应出现
    expect(screen.queryByLabelText('同步模型目录')).not.toBeInTheDocument()
  })

  it('shows sync catalog button for admin users', async () => {
    // admin 用户
    useAuthStore.setState({ user: { username: 'admin', role: 'admin' } })

    renderWithQueryClient(<BillingPage />)
    await screen.findByText('用量计费')

    // 同步按钮应出现
    expect(screen.getByLabelText('同步模型目录')).toBeInTheDocument()
    expect(screen.getByText('同步模型目录')).toBeInTheDocument()
  })

  it('opens confirmation dialog when sync button is clicked', async () => {
    useAuthStore.setState({ user: { username: 'admin', role: 'admin' } })

    renderWithQueryClient(<BillingPage />)
    await screen.findByText('用量计费')

    // 初始时对话框不可见
    expect(screen.queryByText('同步模型目录', { selector: 'h3' })).not.toBeInTheDocument()

    // 点击同步按钮
    const syncBtn = screen.getByLabelText('同步模型目录')
    fireEvent.click(syncBtn)

    // 对话框应出现，包含确认文案
    expect(await screen.findByText('同步模型目录', { selector: 'h3' })).toBeInTheDocument()
    expect(screen.getByText(/此操作将从/)).toBeInTheDocument()
    expect(screen.getByText('取消')).toBeInTheDocument()
    expect(screen.getByText('确认同步')).toBeInTheDocument()
  })

  it('calls syncModelCatalog and shows success toast when confirmed', async () => {
    useAuthStore.setState({ user: { username: 'admin', role: 'admin' } })
    syncModelCatalogMock.mockResolvedValue({
      success: true,
      added: 5,
      updated: 3,
      removed: 1,
      skipped: 12,
      synced_at: '2026-07-10T08:00:00Z',
    })

    renderWithQueryClient(<BillingPage />)
    await screen.findByText('用量计费')

    // 打开对话框
    fireEvent.click(screen.getByLabelText('同步模型目录'))

    // 确认同步
    const confirmBtn = await screen.findByText('确认同步')
    await act(async () => {
      fireEvent.click(confirmBtn)
    })

    // 验证调用了 syncModelCatalog
    await waitFor(() => expect(syncModelCatalogMock).toHaveBeenCalledTimes(1))

    // 验证展示了成功 toast（包含同步统计）
    expect(await screen.findByText(/同步完成：新增 5 个/)).toBeInTheDocument()
    expect(screen.getByText(/更新 3 个/)).toBeInTheDocument()
    expect(screen.getByText(/失效 1 个/)).toBeInTheDocument()
    expect(screen.getByText(/跳过 12 个/)).toBeInTheDocument()
  })

  it('shows error toast when sync fails', async () => {
    useAuthStore.setState({ user: { username: 'admin', role: 'admin' } })
    syncModelCatalogMock.mockRejectedValue({
      response: { status: 502, data: { detail: '模型目录同步失败: 上游服务不可用' } },
    })

    renderWithQueryClient(<BillingPage />)
    await screen.findByText('用量计费')

    // 打开对话框并确认
    fireEvent.click(screen.getByLabelText('同步模型目录'))
    const confirmBtn = await screen.findByText('确认同步')
    await act(async () => {
      fireEvent.click(confirmBtn)
    })

    // 验证展示了错误 toast
    expect(await screen.findByText(/模型目录同步失败: 上游服务不可用/)).toBeInTheDocument()
  })

  it('closes dialog when cancel button is clicked', async () => {
    useAuthStore.setState({ user: { username: 'admin', role: 'admin' } })

    renderWithQueryClient(<BillingPage />)
    await screen.findByText('用量计费')

    // 打开对话框
    fireEvent.click(screen.getByLabelText('同步模型目录'))
    expect(await screen.findByText('取消')).toBeInTheDocument()

    // 点击取消
    fireEvent.click(screen.getByText('取消'))

    // 对话框应关闭（标题 h3 不再存在）
    await waitFor(() => {
      expect(screen.queryByText('同步模型目录', { selector: 'h3' })).not.toBeInTheDocument()
    })
  })

  it('renders new usage table columns', async () => {
    renderWithQueryClient(<BillingPage />)
    await screen.findByText('用量计费')

    // 验证新增列头存在
    expect(screen.getByText('缓存读取Tokens')).toBeInTheDocument()
    expect(screen.getByText('缓存写入Tokens')).toBeInTheDocument()
    expect(screen.getByText('缓存成本')).toBeInTheDocument()
    expect(screen.getByText('思考Tokens')).toBeInTheDocument()
    expect(screen.getByText('计数方法')).toBeInTheDocument()
    expect(screen.getByText('操作')).toBeInTheDocument()
  })

  it('opens detail drawer when detail button is clicked', async () => {
    renderWithQueryClient(<BillingPage />)
    await screen.findByText('用量计费')

    // 等待用量数据加载
    await waitFor(() => expect(billingMocks.getUsage).toHaveBeenCalledTimes(1))

    // 点击详情按钮
    const detailBtn = screen.getByLabelText(/查看.*调用详情/)
    fireEvent.click(detailBtn)

    // 抽屉应打开，显示标题
    expect(await screen.findByText('用量调用详情')).toBeInTheDocument()
  })
})
