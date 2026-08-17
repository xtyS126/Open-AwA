import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DashboardPage from '@/features/dashboard/DashboardPage'
import { RouterTestProvider as BrowserRouter } from '@/shared/routing/testing'

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  weixinAPI: { getConfig: vi.fn().mockResolvedValue({ data: {} }) },
  authAPI: { getMe: vi.fn().mockResolvedValue({ data: {} }) },
  billingAPI: { getSummary: vi.fn().mockResolvedValue({ data: {} }) },
  chatAPI: { getHistory: vi.fn().mockResolvedValue({ data: [] }) },
  modelsAPI: { getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }) },
  memoryAPI: { getShortTerm: vi.fn().mockResolvedValue({ data: [] }), getLongTerm: vi.fn().mockResolvedValue({ data: [] }) },
  experiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  fileExperiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  skillsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  promptsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  logsAPI: { query: vi.fn().mockResolvedValue({ data: { records: [], total: 0 } }) },
  behaviorAPI: { getStats: vi.fn().mockResolvedValue({ data: {} }) },
  conversationAPI: { getRecordsPreview: vi.fn().mockResolvedValue({ data: { records: [], count: 0 } }) }
}))

vi.mock('@/features/billing/billingApi', () => ({
  billingAPI: {
    getCostStatistics: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('@/shared/api/dataApi', () => ({
  getDataStats: vi.fn().mockResolvedValue({
    conversation_count: 0,
    tool_call_count: 0,
    trace_count: 0,
    feedback_count: 0,
    avg_response_time_ms: 0,
    role_usage: [],
  }),
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    updateConfiguration: vi.fn().mockResolvedValue({ data: {} })
  }
}))

/* 每个测试独立的 QueryClient 实例，避免缓存污染 */
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
      },
    },
  })
}

function renderWithProviders(ui: React.ReactNode) {
  const queryClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>,
  )
}

describe('DashboardPage', () => {
  it('renders without crashing', () => {
    renderWithProviders(<DashboardPage />)
    expect(true).toBe(true)
  })

  it('可滚动仪表盘区域具有可访问名称并可通过键盘聚焦', async () => {
    renderWithProviders(<DashboardPage />)

    const region = await screen.findByRole('region', { name: '仪表盘内容' })
    expect(region).toHaveAttribute('tabindex', '0')
  })
})
