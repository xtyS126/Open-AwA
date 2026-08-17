import '@testing-library/jest-dom/vitest'
import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BillingTabContainer } from '@/features/settings/containers/BillingTabContainer'

const billingApiMocks = vi.hoisted(() => ({
  getModels: vi.fn(() => Promise.resolve({
    data: {
      models: [
        {
          id: 1,
          provider: 'openai',
          model: 'gpt-4o-mini',
          input_price: 0.15,
          output_price: 0.6,
          cache_hit_price: 0.05,
          currency: 'USD',
          context_window: 128000,
          is_active: true,
          supports_vision: true,
          is_multimodal: true,
          updated_at: '2026-05-03T10:00:00Z',
        },
      ],
    },
  })),
  updateModelPricing: vi.fn(() => Promise.resolve({ data: { success: true } })),
}))

vi.mock('@/features/billing/billingApi', () => ({
  billingAPI: billingApiMocks,
}))

/** 创建测试用 QueryClient：staleTime 60s 模拟生产配置，验证缓存复用 */
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 60 * 1000,
        gcTime: 5 * 60 * 1000,
      },
    },
  })
}

describe('BillingTabContainer - React Query 缓存复用', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('挂载时通过 useQuery 调用 billingAPI.getModels', async () => {
    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <BillingTabContainer />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(billingApiMocks.getModels).toHaveBeenCalledTimes(1)
    })
  })

  it('组件 remount 时复用缓存，不重复请求 getModels', async () => {
    const queryClient = createTestQueryClient()

    // 第一次挂载：触发 useQuery 请求
    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <BillingTabContainer />
      </QueryClientProvider>,
    )
    await waitFor(() => {
      expect(billingApiMocks.getModels).toHaveBeenCalledTimes(1)
    })
    unmount()

    // 第二次挂载：同一 QueryClient，staleTime 60s 内应复用缓存
    render(
      <QueryClientProvider client={queryClient}>
        <BillingTabContainer />
      </QueryClientProvider>,
    )

    // 等待微任务队列稳定，确认没有额外的 API 调用
    await new Promise((resolve) => setTimeout(resolve, 50))

    // 仍然只被调用 1 次（缓存命中，未发起重复请求）
    expect(billingApiMocks.getModels).toHaveBeenCalledTimes(1)
  })
})
