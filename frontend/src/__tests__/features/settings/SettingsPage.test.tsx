import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from '@/features/settings/SettingsPage'
import { useModelStore } from '@/features/chat/store/modelStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'
import { useSharedSettingsStore } from '@/features/settings/hooks/useSharedSettingsStore'
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
  saveProviderCredential: vi.fn(),
  getProviderCredential: vi.fn(),
  getMaskedApiKey: vi.fn(),
  getPlainApiKey: vi.fn(),
  getProviderCatalog: vi.fn(),
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
  },
  userAPI: {
    getProfile: vi.fn().mockResolvedValue({ data: {} }),
    updateProfile: vi.fn().mockResolvedValue({ data: {} }),
    uploadAvatar: vi.fn().mockResolvedValue({ data: {} }),
    getDevices: vi.fn().mockResolvedValue({ data: [] }),
    revokeDevice: vi.fn().mockResolvedValue({ data: {} }),
    getPreferences: vi.fn().mockResolvedValue({ data: { preferences: {} } }),
    updatePreferences: vi.fn().mockResolvedValue({ data: { preferences: {} } }),
  },
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
    useModelStore.setState({
      selectedModel: '',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
    })
    usePreferenceStore.setState({
      outputMode: 'stream',
    })
    // 重置设置页共享 store，避免前一个用例填充的 lastLoadedAt 缓存导致后续用例跳过 getConfigurations
    useSharedSettingsStore.getState().reset()

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
    modelApiMocks.getProviderDetail.mockImplementation(async (provider: string) => {
      return {
        data: {
          configuration: {
            id: provider === 'openai' ? 11 : 99,
            provider,
            selected_models: provider === 'openai' ? ['legacy-local-model'] : ['fallback-local-model'],
            has_api_key: true
          },
          provider: {
            id: provider,
            name: provider,
            has_api_key: true
          }
        }
      }
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
    modelApiMocks.saveProviderCredential.mockResolvedValue({ data: { success: true } })
    modelApiMocks.getMaskedApiKey.mockResolvedValue({
      data: {
        masked_api_key: 'sk-t...6789',
        has_api_key: true,
        api_key_status: 'active',
      },
    })
    modelApiMocks.getPlainApiKey.mockResolvedValue({
      data: {
        api_key: 'sk-test-complete-provider-key-0123456789',
        has_api_key: true,
        api_key_status: 'active',
      },
    })
    modelApiMocks.getProviderCatalog.mockResolvedValue({
      data: {
        providers: [
          { id: 'openai', name: 'OpenAI', display_name: 'OpenAI', base_url: 'https://api.openai.com/v1', source: 'pricing_data' },
          { id: 'anthropic', name: 'Anthropic', display_name: 'Anthropic', base_url: 'https://api.anthropic.com/v1', source: 'pricing_data' },
        ],
      },
    })
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

    // 首次触发 ApiSettings 懒加载，完整测试套件中模块编译耗时较高，放宽超时
    fireEvent.click(await screen.findByText('新增供应商', undefined, { timeout: 5000 }))

    const dialog = screen.getByRole('dialog', { name: '新增供应商' })
    expect(within(dialog).getByLabelText('显示名称（可选）')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('基础 URL（可选）')).toBeInTheDocument()
    expect(within(dialog).queryByText('图标地址（可选）')).not.toBeInTheDocument()
    expect(within(dialog).queryByText('默认模型（可选）')).not.toBeInTheDocument()
    expect(within(dialog).queryByText('API URL（可选）')).not.toBeInTheDocument()
    expect(within(dialog).queryByText('API Key（可选）')).not.toBeInTheDocument()
    expect(within(dialog).queryByText('最大 Token 数（可选）')).not.toBeInTheDocument()

    // 等待供应商目录加载完成（select 不再 disabled）
    const providerSelect = await screen.findByLabelText('供应商标识')
    await waitFor(() => {
      expect(providerSelect).not.toBeDisabled()
    })

    fireEvent.change(providerSelect, { target: { value: 'openai' } })

    const baseUrlInput = screen.getByPlaceholderText('https://api.example.com/v1') as HTMLInputElement
    const displayNameInput = screen.getByLabelText('显示名称（可选）') as HTMLInputElement

    await waitFor(() => {
      expect(displayNameInput.value).toBe('OpenAI')
      expect(baseUrlInput.value).toBe('https://api.openai.com/v1')
    })

    fireEvent.change(providerSelect, { target: { value: 'anthropic' } })

    await waitFor(() => {
      expect(displayNameInput.value).toBe('Anthropic')
      expect(baseUrlInput.value).toBe('https://api.anthropic.com/v1')
    })
  })

  it('提交新增供应商表单时仅发送显示名称和规范化基础 URL', async () => {
    renderSettingsApiTab()

    fireEvent.click(await screen.findByText('新增供应商'))

    // 等待供应商目录加载完成
    const providerSelect = await screen.findByLabelText('供应商标识')
    await waitFor(() => {
      expect(providerSelect).not.toBeDisabled()
    })

    fireEvent.change(providerSelect, { target: { value: 'openai' } })
    fireEvent.change(screen.getByLabelText('显示名称（可选）'), { target: { value: 'OpenAI 国际站' } })
    fireEvent.change(screen.getByLabelText('基础 URL（可选）'), {
      target: { value: 'https://api.openai.com/v1/chat/completions' }
    })

    fireEvent.click(screen.getByText('确认创建'))

    await waitFor(() => {
      expect(modelApiMocks.saveProviderCredential).toHaveBeenCalledWith('openai', {
        display_name: 'OpenAI 国际站',
        api_endpoint: 'https://api.openai.com/v1',
      })
    })

    const payload = modelApiMocks.saveProviderCredential.mock.calls[0]?.[1]
    expect(payload).not.toHaveProperty('api_key')
    expect(payload).not.toHaveProperty('icon')
    expect(payload).not.toHaveProperty('max_tokens')
  })

  it('通用设置默认模型使用惰性远端加载并复用缓存，且忽略本地回退模型', async () => {
    renderSettingsGeneralTab()

    expect(modelApiMocks.getModelsByProvider).not.toHaveBeenCalled()
    // 等待懒加载的 GeneralTabContainer 完成渲染
    await waitFor(() => {
      expect(screen.getByText('加载远端模型')).toBeInTheDocument()
    }, { timeout: 5000 })

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

  it('通用设置支持保存工具回环次数上限', async () => {
    renderSettingsGeneralTab()

    const roundsInput = await screen.findByLabelText(
      '工具回环次数上限',
      undefined,
      { timeout: 5000 },
    ) as HTMLInputElement
    fireEvent.change(roundsInput, { target: { value: '18' } })
    fireEvent.click(screen.getByText('保存设置'))

    await waitFor(() => {
      const saved = JSON.parse(window.localStorage.getItem('app_settings') || '{}')
      expect(saved.maxToolCallRounds).toBe(18)
    })
  })

  it('通用设置的主题、语言和输出模式选择框具有可靠名称', async () => {
    renderSettingsGeneralTab()

    expect(await screen.findByRole('combobox', { name: '主题' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '语言' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '输出模式' })).toBeInTheDocument()
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

  it('在导入模型时会自动保存整个供应商配置', async () => {
    renderSettingsApiTab()
    
    const providerItem = await screen.findByText('OpenAI')
    fireEvent.click(providerItem)
    
    const baseUrlInput = await screen.findByPlaceholderText('https://api.example.com')
    fireEvent.change(baseUrlInput, { target: { value: 'https://api.openai.com/v1' } })
    const apiKeyInput = screen.getByPlaceholderText('已配置密钥，留空表示不修改')
    fireEvent.change(apiKeyInput, { target: { value: 'draft-api-key' } })

    const getModelsBtn = screen.getByText('获取模型列表')
    fireEvent.click(getModelsBtn)

    await waitFor(() => {
      expect(modelApiMocks.getModelsByProvider).toHaveBeenCalledWith('openai', {
        api_endpoint: 'https://api.openai.com/v1',
        api_key: 'draft-api-key',
      })
    })
    
    expect(await screen.findByText('导入模型')).toBeInTheDocument()
    const checkbox = await screen.findByLabelText('gpt-4.1')
    fireEvent.click(checkbox)

    const confirmBtn = screen.getByText('确认导入')
    fireEvent.click(confirmBtn)
    
    await waitFor(() => {
      // handleImportModels 先保存供应商凭据（包含 api_endpoint）
      expect(modelApiMocks.saveProviderCredential).toHaveBeenCalledWith('openai', expect.objectContaining({
        api_endpoint: 'https://api.openai.com/v1',
      }))
      // 再更新已选模型列表
      expect(modelApiMocks.updateProviderSelectedModels).toHaveBeenCalledWith('openai', expect.objectContaining({
        selected_models: ['gpt-4.1']
      }))
    })

    expect(modelApiMocks.getConfigurations).toHaveBeenCalled()
  })

  it('点击显示后展示完整 API Key 而不是脱敏值', async () => {
    renderSettingsApiTab()

    fireEvent.click(await screen.findByText('OpenAI', undefined, { timeout: 5000 }))
    const showButton = await screen.findByRole(
      'button',
      { name: '显示' },
      { timeout: 5000 },
    )
    fireEvent.click(showButton)

    await waitFor(() => {
      expect(modelApiMocks.getPlainApiKey).toHaveBeenCalledWith('openai')
      expect(
        screen.getByText('当前密钥: sk-test-complete-provider-key-0123456789'),
      ).toBeInTheDocument()
    })
    expect(screen.queryByText('当前密钥: sk-t...6789')).not.toBeInTheDocument()
  })

  it('在批量删除模型时会自动保存整个供应商配置', async () => {
    modelApiMocks.getModelsByProvider.mockResolvedValue({
      data: {
        success: true,
        provider: 'openai',
        source: 'remote',
        models: [
          {
            id: -1,
            provider: 'openai',
            model: 'legacy-local-model',
            input_price: 0,
            output_price: 0,
            currency: 'USD',
            context_window: null,
          },
        ],
        selected_models: ['legacy-local-model'],
        error: null,
      },
    })
    renderSettingsApiTab()
    
    const providerItem = await screen.findByText('OpenAI')
    fireEvent.click(providerItem)
    
    const claudeCheckbox = await screen.findByLabelText('legacy-local-model')
    fireEvent.click(claudeCheckbox)
    
    const batchDeleteBtn = await screen.findByText(/批量删除 \(\d+\)/)
    fireEvent.click(batchDeleteBtn)
    
    const confirmBtn = await screen.findByText('确认删除')
    fireEvent.click(confirmBtn)
    
    await waitFor(() => {
      expect(modelApiMocks.updateConfiguration).toHaveBeenCalledWith(11, expect.objectContaining({
        selected_models: []
      }))
    })
  })
})
