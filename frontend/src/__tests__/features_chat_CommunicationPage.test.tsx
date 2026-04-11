import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import CommunicationPage from '@/features/chat/CommunicationPage'
import { BrowserRouter } from 'react-router-dom'

const { getConfigMock, getBindingMock, getParamsMock } = vi.hoisted(() => ({
  getConfigMock: vi.fn(),
  getBindingMock: vi.fn(),
  getParamsMock: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  weixinAPI: {
    getConfig: getConfigMock,
    getBinding: getBindingMock,
    getParams: getParamsMock,
  },
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

describe('CommunicationPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('在初始加载失败时展示配置与参数错误', async () => {
    getConfigMock.mockRejectedValueOnce({ response: { data: { detail: '微信配置读取失败' } } })
    getBindingMock.mockRejectedValueOnce(new Error('binding failed'))
    getParamsMock.mockRejectedValueOnce({ response: { data: { detail: '参数接口不可用' } } })

    render(<BrowserRouter><CommunicationPage /></BrowserRouter>)

    expect(await screen.findByText('微信配置读取失败')).toBeInTheDocument()
    expect(await screen.findByText('参数接口不可用')).toBeInTheDocument()
    expect(await screen.findByText('加载绑定状态失败')).toBeInTheDocument()
  })
})
