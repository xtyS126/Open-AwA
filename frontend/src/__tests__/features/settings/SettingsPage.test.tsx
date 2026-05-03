import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from '@/features/settings/SettingsPage'
import { useChatStore } from '@/features/chat/store/chatStore'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const modelApiMocks = vi.hoisted(() => ({
  getConfigurations: vi.fn(),
  getProviders: vi.fn(),
  getProviderDetail: vi.fn(),
  getModelsByProvider: vi.fn(),
  getCapabilities: vi.fn(),
  updateParameters: vi.fn(),
  resetParameters: vi.fn(),
  updateProviderSelectedModels: vi.fn(),
  deleteProvider: vi.fn(),
  deleteConfiguration: vi.fn(),
  setDefaultConfiguration: vi.fn(),
  createConfiguration: vi.fn(),
  updateConfiguration: vi.fn(),
}))

const billingApiMocks = vi.hoisted(() => ({
  getModels: vi.fn(),
  getRetention: vi.fn(),
  updateModelPricing: vi.fn(),
}))

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
  promptsAPI: {
    getAll: vi.fn().mockResolvedValue({ data: [] }),
    getActive: vi.fn().mockResolvedValue({ data: null }),
  },
  logsAPI: { query: vi.fn().mockResolvedValue({ data: { records: [], total: 0 } }) },
  behaviorAPI: { getStats: vi.fn().mockResolvedValue({ data: {} }) },
  conversationAPI: {
    getCollectionStatus: vi.fn().mockResolvedValue({ data: { enabled: false, stats: null } }),
    getRecordsPreview: vi.fn().mockResolvedValue({ data: { records: [], count: 0 } }),
  }
}))

vi.mock('@/features/billing/billingApi', () => ({
  billingAPI: billingApiMocks
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: modelApiMocks
}))

describe('SettingsPage', () => {
  const renderSettingsApiTab = () =>
    render(
      <MemoryRouter initialEntries={['/settings?tab=api']}>
        <Routes>
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </MemoryRouter>
    )

  const renderSettingsGeneralTab = () =>
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <Routes>
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </MemoryRouter>
    )

  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    useChatStore.setState({
      selectedModel: '',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
      outputMode: 'stream',
    })

    modelApiMocks.getConfigurations.mockResolvedValue({
      data: {
        configurations: [
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
            model_spec: {
              context_window: 128000,
              max_output_tokens: 8192,
              supports_function_calling: true,
              supports_streaming: true,
              supports_vision: true,
            },
            status: 'active',
            created_at: '2026-05-01T08:00:00Z',
            updated_at: '2026-05-03T10:00:00Z',
          },
        ],
      },
    })
    modelApiMocks.getProviders.mockResolvedValue({
      data: {
        providers: [
          { id: 'openai', name: 'OpenAI', display_name: 'OpenAI', configuration_count: 1, has_api_key: true },
          { id: 'fallback', name: 'Fallback', display_name: 'Fallback', configuration_count: 1, has_api_key: true },
        ],
      },
    })
    modelApiMocks.getCapabilities.mockResolvedValue({
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
        },
        limits: {
          temperature_min: 0,
          temperature_max: 2,
          top_k_min: 0,
          top_k_max: 1,
          max_tokens_min: 1,
          max_tokens_max: 128000,
        },
      },
    })
    modelApiMocks.getModelsByProvider.mockImplementation(async (provider: string) => {
      if (provider === 'openai') {
        return {
          data: {
            success: true,
            provider,
            source: 'remote',
            models: [
              { id: -1, provider, model: 'gpt-4o-mini', input_price: 0, output_price: 0, currency: 'USD', context_window: null },
              { id: -2, provider, model: 'gpt-4.1', input_price: 0, output_price: 0, currency: 'USD', context_window: null },
            ],
            selected_models: ['legacy-local-model'],
            error: null,
          },
        }
      }

      return {
        data: {
          success: false,
          provider,
          source: 'local',
          models: [
            { id: 99, provider, model: 'fallback-local-model', input_price: 0, output_price: 0, currency: 'USD', context_window: 4096 },
          ],
          selected_models: ['fallback-local-model'],
          error: { code: 'provider_models_fetch_failed', message: '回退到本地模型列表' },
        },
      }
    })
    modelApiMocks.createConfiguration.mockResolvedValue({ data: { success: true } })
    modelApiMocks.updateConfiguration.mockResolvedValue({ data: {} })
    modelApiMocks.updateParameters.mockResolvedValue({ data: { success: true } })
    modelApiMocks.resetParameters.mockResolvedValue({
      data: {
        configuration: {
          temperature: 0.7,
          top_k: 0.9,
        },
      },
    })
    billingApiMocks.getModels.mockResolvedValue({
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
    })
    billingApiMocks.getRetention.mockResolvedValue({ data: { retention_days: 365 } })
  })

  it('新增供应商弹窗仅保留显示名称和基础 URL，并随预置供应商切换自动更新', async () => {
    renderSettingsApiTab()

    fireEvent.click(await screen.findByText('新增供应商'))

    expect(screen.getByLabelText('显示名称（可选）')).toBeInTheDocument()
    expect(screen.getByLabelText('基础 URL（可选）')).toBeInTheDocument()
    expect(screen.queryByText('图标地址（可选）')).not.toBeInTheDocument()
    expect(screen.queryByText('默认模型（可选）')).not.toBeInTheDocument()
    expect(screen.queryByText('API URL（可选）')).not.toBeInTheDocument()
    expect(screen.queryByText('API Key（可选）')).not.toBeInTheDocument()
    expect(screen.queryByText('最大 Token 数（可选）')).not.toBeInTheDocument()

    const providerSelect = screen.getByLabelText('供应商标识')
    fireEvent.change(providerSelect, { target: { value: 'openai' } })

    const baseUrlInput = screen.getByPlaceholderText('https://api.example.com/v1') as HTMLInputElement
    const displayNameInput = screen.getByLabelText('显示名称（可选）') as HTMLInputElement

    expect(displayNameInput.value).toBe('OpenAI')
    expect(baseUrlInput.value).toBe('https://api.openai.com/v1')

    fireEvent.change(providerSelect, { target: { value: 'anthropic' } })

    expect(displayNameInput.value).toBe('Anthropic')
    expect(baseUrlInput.value).toBe('https://api.anthropic.com/v1')
  })

  it('提交新增供应商表单时仅发送显示名称和规范化基础 URL', async () => {
    renderSettingsApiTab()

    fireEvent.click(await screen.findByText('新增供应商'))

    fireEvent.change(screen.getByLabelText('供应商标识'), { target: { value: 'openai' } })
    fireEvent.change(screen.getByLabelText('显示名称（可选）'), { target: { value: 'OpenAI 国际站' } })
    fireEvent.change(screen.getByLabelText('基础 URL（可选）'), {
      target: { value: 'https://api.openai.com/v1/chat/completions' }
    })

    fireEvent.click(screen.getByText('确认创建'))

    await waitFor(() => {
      expect(modelApiMocks.createConfiguration).toHaveBeenCalledWith({
        provider: 'openai',
        model: 'custom-model',
        display_name: 'OpenAI 国际站',
        api_endpoint: 'https://api.openai.com/v1',
        is_default: false,
      })
    })

    const payload = modelApiMocks.createConfiguration.mock.calls[0]?.[0]
    expect(payload).not.toHaveProperty('api_key')
    expect(payload).not.toHaveProperty('icon')
    expect(payload).not.toHaveProperty('max_tokens')
  })

  it('通用设置默认模型使用惰性远端加载并复用缓存，且忽略本地回退模型', async () => {
    renderSettingsGeneralTab()

    expect(modelApiMocks.getModelsByProvider).not.toHaveBeenCalled()
    expect(screen.getByText('加载远端模型')).toBeInTheDocument()

    fireEvent.click(screen.getByText('加载远端模型'))

    await waitFor(() => {
      expect(modelApiMocks.getModelsByProvider).toHaveBeenCalledTimes(2)
    })

    expect(screen.getByText('OpenAI - gpt-4o-mini')).toBeInTheDocument()
    expect(screen.getByText('OpenAI - gpt-4.1')).toBeInTheDocument()
    expect(screen.queryByText('fallback-local-model')).not.toBeInTheDocument()
    expect(screen.getByText(/已忽略本地回退结果/)).toBeInTheDocument()

    fireEvent.click(screen.getByText('重新读取'))

    await waitFor(() => {
      expect(modelApiMocks.getModelsByProvider).toHaveBeenCalledTimes(2)
    })
  })

  it('AI 参数区移除最大 Tokens 输入，并展示模型级计费详情', async () => {
    renderSettingsGeneralTab()

    await screen.findByText('当前模型详情')

    expect(screen.queryByText(/^最大 Tokens$/)).not.toBeInTheDocument()
    expect(screen.getByText('当前最大 Tokens')).toBeInTheDocument()
    expect(screen.getByText('上下文窗口')).toBeInTheDocument()
    expect(screen.getByText('输入价格')).toBeInTheDocument()
    expect(screen.getByText('输出价格')).toBeInTheDocument()
    expect(screen.getByText('函数调用')).toBeInTheDocument()
    expect(screen.getByText('流式输出')).toBeInTheDocument()
    expect(screen.getByText('8K')).toBeInTheDocument()
  })
})
