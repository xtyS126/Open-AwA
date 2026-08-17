import '@testing-library/jest-dom/vitest'
import { render } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ExperiencePage from '@/features/experiences/ExperiencePage'
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

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    updateConfiguration: vi.fn().mockResolvedValue({ data: {} })
  }
}))

// 拦截经验文件 API，避免触发真实网络请求
vi.mock('@/features/experiences/fileExperiencesApi', () => ({
  fileExperiencesApi: {
    listFiles: vi.fn().mockResolvedValue({ data: [] }),
    getFileDetail: vi.fn().mockResolvedValue({ data: null }),
    saveFile: vi.fn().mockResolvedValue({ data: { file_name: '', updated_at: '', size: 0 } }),
  }
}))

// 每个测试独立的 QueryClient 实例，避免缓存污染
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 0,
      },
    },
  })
}

describe('ExperiencePage', () => {
  it('renders without crashing', () => {
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <BrowserRouter><ExperiencePage /></BrowserRouter>
      </QueryClientProvider>,
    )
    expect(true).toBe(true)
  })
})
