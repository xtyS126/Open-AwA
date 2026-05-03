import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from '@/features/settings/SettingsPage'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const modelApiMocks = vi.hoisted(() => ({
  getConfigurations: vi.fn(),
  getProviders: vi.fn(),
  createConfiguration: vi.fn(),
  updateConfiguration: vi.fn(),
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
  billingAPI: {
    getModels: vi.fn().mockResolvedValue({ data: { models: [] } }),
    getRetention: vi.fn().mockResolvedValue({ data: { retention_days: 365 } }),
  }
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

  beforeEach(() => {
    vi.clearAllMocks()
    modelApiMocks.getConfigurations.mockResolvedValue({ data: { configurations: [] } })
    modelApiMocks.getProviders.mockResolvedValue({ data: { providers: [] } })
    modelApiMocks.createConfiguration.mockResolvedValue({ data: { success: true } })
    modelApiMocks.updateConfiguration.mockResolvedValue({ data: {} })
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
})
