import '@testing-library/jest-dom/vitest'
import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PromptsTabContainer } from '@/features/settings/containers/PromptsTabContainer'

const promptsApiMocks = vi.hoisted(() => ({
  getActive: vi.fn(() => Promise.resolve({
    data: {
      id: 'prompt-1',
      name: 'System Prompt',
      content: 'You are a helpful assistant.',
      is_active: true,
    },
  })),
  getAll: vi.fn(() => Promise.resolve({ data: [] })),
  update: vi.fn(() => Promise.resolve({ data: {} })),
  create: vi.fn(() => Promise.resolve({ data: {} })),
}))

vi.mock('@/shared/api/api', () => ({
  promptsAPI: promptsApiMocks,
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

describe('PromptsTabContainer - React Query 缓存复用', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('挂载时通过 useQuery 调用 promptsAPI.getActive', async () => {
    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <PromptsTabContainer />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(promptsApiMocks.getActive).toHaveBeenCalledTimes(1)
    })
  })

  it('组件 remount 时复用缓存，不重复请求 getActive', async () => {
    const queryClient = createTestQueryClient()

    // 第一次挂载：触发 useQuery 请求
    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <PromptsTabContainer />
      </QueryClientProvider>,
    )
    await waitFor(() => {
      expect(promptsApiMocks.getActive).toHaveBeenCalledTimes(1)
    })
    unmount()

    // 第二次挂载：同一 QueryClient，staleTime 60s 内应复用缓存
    render(
      <QueryClientProvider client={queryClient}>
        <PromptsTabContainer />
      </QueryClientProvider>,
    )

    // 等待微任务队列稳定，确认没有额外的 API 调用
    await new Promise((resolve) => setTimeout(resolve, 50))

    // 仍然只被调用 1 次（缓存命中，未发起重复请求）
    expect(promptsApiMocks.getActive).toHaveBeenCalledTimes(1)
  })
})
