import '@testing-library/jest-dom/vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useModelConfig } from '@/features/settings/containers/ModelConfigContainer'
import type { ModelConfiguration } from '@/features/settings/modelsApi'

const modelApiMocks = vi.hoisted(() => ({
  getCapabilities: vi.fn(() => Promise.resolve({
    data: {
      config_id: 11,
      provider: 'openai',
      model: 'gpt-4o-mini',
      capabilities: {
        supports_temperature: true,
        supports_top_k: true,
        supports_vision: true,
        is_multimodal: true,
        supports_function_calling: true,
        supports_streaming: true,
      },
      defaults: {
        temperature: 0.7,
        top_k: 0.9,
        max_tokens: 8192,
        frequency_penalty: 0,
        presence_penalty: 0,
        timeout: 120,
        retry_count: 3,
      },
      limits: {
        temperature_min: 0,
        temperature_max: 2,
        top_k_min: 0,
        top_k_max: 1,
        max_tokens_min: 1,
        max_tokens_max: 128000,
        frequency_penalty_min: -2,
        frequency_penalty_max: 2,
        presence_penalty_min: -2,
        presence_penalty_max: 2,
        timeout_min: 1,
        timeout_max: 600,
        retry_count_min: 0,
        retry_count_max: 10,
      },
    },
  })),
  updateParameters: vi.fn(() => Promise.resolve({ data: { success: true } })),
  resetParameters: vi.fn(() => Promise.resolve({
    data: { configuration: { temperature: 0.7, top_k: 0.9, max_tokens_limit: null } },
  })),
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: modelApiMocks,
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

/** 构建 wrapper：将 Hook 包裹在 QueryClientProvider 中 */
function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    )
  }
}

const mockConfigurations: ModelConfiguration[] = [
  {
    id: 11,
    provider: 'openai',
    model: 'gpt-4o-mini',
    display_name: 'GPT-4o Mini',
    description: null,
    selected_models: ['gpt-4o-mini'],
    is_active: true,
    is_default: true,
    sort_order: 0,
    temperature: 0.7,
    top_k: 0.9,
    top_p: null,
    max_tokens_limit: 8192,
    supports_temperature: true,
    supports_top_k: true,
    supports_vision: true,
    is_multimodal: true,
    status: 'active',
    created_at: '2026-05-01T08:00:00Z',
    updated_at: '2026-05-03T10:00:00Z',
  },
]

describe('useModelConfig - React Query 缓存复用', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('展开模型卡片时通过 useQuery 调用 modelsAPI.getCapabilities', async () => {
    const queryClient = createTestQueryClient()
    const { result } = renderHook(
      () => useModelConfig({
        configurations: mockConfigurations,
        providerFormProvider: 'openai',
        loadModelsData: vi.fn(() => Promise.resolve()),
      }),
      { wrapper: createWrapper(queryClient) },
    )

    // 初始状态：未展开任何卡片，getCapabilities 不应被调用
    expect(modelApiMocks.getCapabilities).not.toHaveBeenCalled()

    // 展开模型卡片
    await act(async () => {
      await result.current.toggleModelConfig('gpt-4o-mini')
    })

    // 等待 useQuery 触发 API 调用
    await waitFor(() => {
      expect(modelApiMocks.getCapabilities).toHaveBeenCalledTimes(1)
    })
  })

  it('折叠后重新展开同一模型时复用缓存，不重复请求 getCapabilities', async () => {
    const queryClient = createTestQueryClient()
    const { result } = renderHook(
      () => useModelConfig({
        configurations: mockConfigurations,
        providerFormProvider: 'openai',
        loadModelsData: vi.fn(() => Promise.resolve()),
      }),
      { wrapper: createWrapper(queryClient) },
    )

    // 第一次展开：触发 getCapabilities
    await act(async () => {
      await result.current.toggleModelConfig('gpt-4o-mini')
    })
    await waitFor(() => {
      expect(modelApiMocks.getCapabilities).toHaveBeenCalledTimes(1)
    })

    // 折叠：再次点击同一模型（手风琴模式，点击已展开项会折叠）
    await act(async () => {
      await result.current.toggleModelConfig('gpt-4o-mini')
    })

    // 重新展开：staleTime 60s 内应复用缓存，不发起新请求
    await act(async () => {
      await result.current.toggleModelConfig('gpt-4o-mini')
    })

    // 等待微任务队列稳定
    await new Promise((resolve) => setTimeout(resolve, 50))

    // 仍然只被调用 1 次（缓存命中）
    expect(modelApiMocks.getCapabilities).toHaveBeenCalledTimes(1)
  })
})
