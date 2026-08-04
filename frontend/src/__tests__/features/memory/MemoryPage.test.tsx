import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import MemoryPage from '@/features/memory/MemoryPage'
import { RouterTestProvider as BrowserRouter } from '@/shared/routing/testing'

const { getShortTermMock, getLongTermMock, getRecordsPreviewMock, vectorSearchMock, validateLongTermMock, deprecateLongTermMock, getStatsMock, getDecayConfigMock, updateDecayConfigMock, runConsolidationMock } = vi.hoisted(() => ({
  getShortTermMock: vi.fn(),
  getLongTermMock: vi.fn(),
  getRecordsPreviewMock: vi.fn(),
  vectorSearchMock: vi.fn(),
  validateLongTermMock: vi.fn(),
  deprecateLongTermMock: vi.fn(),
  getStatsMock: vi.fn(),
  getDecayConfigMock: vi.fn(),
  updateDecayConfigMock: vi.fn(),
  runConsolidationMock: vi.fn(),
}))

vi.mock('@/shared/api/vectorModelsApi', () => ({
  vectorModelsAPI: {
    getRegistry: vi.fn().mockResolvedValue({ data: { data: { models: [] } } }),
    getConfig: vi.fn().mockResolvedValue({
      data: {
        data: {
          embedding_provider: 'auto',
          embedding_model: '',
          embedding_api_key: '',
          embedding_api_endpoint: '',
          rerank_provider: 'off',
          rerank_model: '',
          rerank_api_key: '',
          rerank_api_endpoint: '',
          model_download_source: 'modelscope',
        },
      },
    }),
    updateConfig: vi.fn().mockResolvedValue({ data: { success: true } }),
    downloadModel: vi.fn().mockResolvedValue({ data: { success: true, task: 't1' } }),
    getDownloadStatus: vi.fn().mockResolvedValue({ data: { data: { tasks: {} } } }),
  },
}))

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  weixinAPI: { getConfig: vi.fn().mockResolvedValue({ data: {} }) },
  authAPI: { getMe: vi.fn().mockResolvedValue({ data: {} }) },
  billingAPI: { getSummary: vi.fn().mockResolvedValue({ data: {} }) },
  chatAPI: { getHistory: vi.fn().mockResolvedValue({ data: [] }) },
  modelsAPI: { getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }) },
  memoryAPI: {
    getShortTerm: getShortTermMock,
    getLongTerm: getLongTermMock,
    deleteShortTerm: vi.fn(),
    deleteLongTerm: vi.fn(),
    listShortTerm: vi.fn().mockResolvedValue({ data: [] }),
    getRecentShortTerm: vi.fn().mockResolvedValue({ data: [] }),
    vectorSearch: vi.fn().mockResolvedValue({ data: [] }),
    getQuality: vi.fn().mockResolvedValue({ data: [] }),
    getStats: getStatsMock,
    getDecayConfig: getDecayConfigMock,
    updateDecayConfig: updateDecayConfigMock,
    validateLongTerm: validateLongTermMock,
    deprecateLongTerm: deprecateLongTermMock,
    runConsolidation: runConsolidationMock,
    vectorSearch: vectorSearchMock,
  },
  experiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  fileExperiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  skillsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  promptsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  logsAPI: { query: vi.fn().mockResolvedValue({ data: { records: [], total: 0 } }) },
  behaviorAPI: { getStats: vi.fn().mockResolvedValue({ data: {} }) },
  conversationAPI: { getRecordsPreview: getRecordsPreviewMock }
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    updateConfiguration: vi.fn().mockResolvedValue({ data: {} })
  }
}))

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

function renderWithQueryClient(ui: React.ReactNode) {
  const testQueryClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={testQueryClient}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>,
  )
}

describe('MemoryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getLongTermMock.mockResolvedValue({ data: [] })
    getShortTermMock.mockResolvedValue({ data: [] })
    getStatsMock.mockResolvedValue({
      data: {
        total_memories: 0,
        active_memories: 0,
        archived_memories: 0,
        average_confidence: 0,
        average_quality_score: 0,
        total_access_count: 0,
        working_memory_count: 0,
        vector_store_count: 0,
        layer_stats: {},
      },
    })
    getDecayConfigMock.mockResolvedValue({
      data: { success: true, data: { semantic: { layer: 'semantic', decay_function: 'exponential', half_life_days: 30, threshold: 0.1, enabled: true } } },
    })
    vectorSearchMock.mockResolvedValue({ data: [] })
    validateLongTermMock.mockResolvedValue({ data: { ok: true } })
    deprecateLongTermMock.mockResolvedValue({ data: { ok: true } })
    runConsolidationMock.mockResolvedValue({ data: { triggered: true, success: true, processed: 0, extracted: 0, consolidated: 0, archived: 0 } })
  })

  it('短期记忆优先使用最近会话而不是默认 session_id', async () => {
    getRecordsPreviewMock.mockResolvedValue({
      data: {
        records: [{ session_id: 'session-123' }],
        count: 1,
        limit: 20,
      },
    })
    getShortTermMock.mockResolvedValue({ data: [] })

    renderWithQueryClient(<MemoryPage />)

    await waitFor(() => expect(getShortTermMock).toHaveBeenCalledWith('session-123'))
    expect(getShortTermMock).not.toHaveBeenCalledWith('default')
    expect(await screen.findByText('当前查看会话：session-123')).toBeInTheDocument()
  })

  it('Spec memory-experience-redesign：长期记忆列表展示真实来源标签与置信度', async () => {
    getLongTermMock.mockResolvedValue({
      data: [
        {
          id: 1,
          content: '用户喜欢 Python 编程语言',
          importance: 0.7,
          confidence: 0.82,
          source_type: 'llm_extracted',
          state: 'validated',
          access_count: 5,
          created_at: new Date().toISOString(),
        },
      ],
    })

    renderWithQueryClient(<MemoryPage />)

    expect(await screen.findByText('用户喜欢 Python 编程语言')).toBeInTheDocument()
    // 来源标签（自动提炼）与状态徽章（已验证）
    expect(screen.getByText('自动提炼')).toBeInTheDocument()
    expect(screen.getByText('已验证')).toBeInTheDocument()
    // 真实置信度 0.82（非 importance 0.7）
    expect(screen.getByText('0.82')).toBeInTheDocument()
  })

  it('Spec memory-experience-redesign：点击"准确"按钮调用 validate API', async () => {
    getLongTermMock.mockResolvedValue({
      data: [
        {
          id: 1,
          content: '待验证记忆',
          importance: 0.6,
          confidence: 0.55,
          source_type: 'user_input',
          state: 'active',
          created_at: new Date().toISOString(),
        },
      ],
    })

    renderWithQueryClient(<MemoryPage />)

    await screen.findByText('待验证记忆')
    const validateButton = screen.getByTitle('记忆准确，验证后不再参与归档')
    validateButton.click()

    await waitFor(() => expect(validateLongTermMock).toHaveBeenCalledWith(1))
  })

  it('Spec memory-experience-redesign：点击"不准确"按钮调用 deprecate API', async () => {
    getLongTermMock.mockResolvedValue({
      data: [
        {
          id: 2,
          content: '应遗忘记忆',
          importance: 0.5,
          confidence: 0.4,
          source_type: 'user_input',
          state: 'active',
          created_at: new Date().toISOString(),
        },
      ],
    })

    renderWithQueryClient(<MemoryPage />)

    await screen.findByText('应遗忘记忆')
    const deprecateButton = screen.getByTitle('记忆不准确，主动遗忘')
    deprecateButton.click()

    await waitFor(() => expect(deprecateLongTermMock).toHaveBeenCalledWith(2))
  })

  it('Spec memory-experience-redesign：搜索时调用 vector-search 并携带滑块权重', async () => {
    renderWithQueryClient(<MemoryPage />)

    await screen.findByText('记忆条目')
    const searchInput = screen.getByPlaceholderText('搜索记忆内容（混合检索）...')
    fireEvent.change(searchInput, { target: { value: 'Python' } })

    await waitFor(() => expect(vectorSearchMock).toHaveBeenCalled())
    const params = vectorSearchMock.mock.calls[0][0]
    expect(params.query).toBe('Python')
    expect(params.keyword_weight).toBeGreaterThanOrEqual(0)
    expect(params.vector_weight).toBeGreaterThanOrEqual(0)
  })

  it('Spec memory-experience-redesign：切换记忆衰减开关调用 decay-config API', async () => {
    renderWithQueryClient(<MemoryPage />)

    // 等待衰减配置加载完成，且完整 UI 渲染结束（loading 分支退出）
    await waitFor(() => expect(getDecayConfigMock).toHaveBeenCalled())
    await screen.findByText('记忆条目')

    const toggle = screen.getByRole('switch')
    toggle.click()

    await waitFor(() => expect(updateDecayConfigMock).toHaveBeenCalled())
    const payload = updateDecayConfigMock.mock.calls[0][0]
    expect(payload.layer).toBe('semantic')
    expect(typeof payload.enabled).toBe('boolean')
  })
})
