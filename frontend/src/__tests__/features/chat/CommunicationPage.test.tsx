import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import CommunicationPage from '@/features/chat/CommunicationPage'
import { BrowserRouter } from 'react-router-dom'

const {
  getConfigMock,
  getBindingMock,
  getParamsMock,
  getAutoReplyStatusMock,
  getRulesMock,
  startAutoReplyMock,
  stopAutoReplyMock,
  restartAutoReplyMock,
  processAutoReplyOnceMock,
  saveConfigMock
} = vi.hoisted(() => ({
  getConfigMock: vi.fn(),
  getBindingMock: vi.fn(),
  getParamsMock: vi.fn(),
  getAutoReplyStatusMock: vi.fn(),
  getRulesMock: vi.fn(),
  startAutoReplyMock: vi.fn(),
  stopAutoReplyMock: vi.fn(),
  restartAutoReplyMock: vi.fn(),
  processAutoReplyOnceMock: vi.fn(),
  saveConfigMock: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  weixinAPI: {
    getConfig: getConfigMock,
    saveConfig: saveConfigMock,
    getBinding: getBindingMock,
    getParams: getParamsMock,
    getAutoReplyStatus: getAutoReplyStatusMock,
    getRules: getRulesMock,
    startAutoReply: startAutoReplyMock,
    stopAutoReply: stopAutoReplyMock,
    restartAutoReply: restartAutoReplyMock,
    processAutoReplyOnce: processAutoReplyOnceMock,
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
  const buildAutoReplyStatus = (overrides: Record<string, unknown> = {}) => ({
    user_id: 'user-1',
    binding_status: 'bound',
    binding_ready: true,
    weixin_account_id: 'wx-account',
    weixin_user_id: 'wx-user-1',
    auto_reply_enabled: true,
    auto_reply_running: false,
    last_poll_at: '2026-04-12T08:00:00Z',
    last_poll_status: 'ok',
    last_error: '',
    last_error_at: '',
    last_success_at: '2026-04-12T08:01:00Z',
    last_reply_at: '2026-04-12T08:02:00Z',
    last_replied_user_id: 'friend-1',
    last_processed_message_id: 'msg-1',
    cursor: 'cursor-1',
    processed_message_count: 3,
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()

    getConfigMock.mockResolvedValue({
      data: {
        account_id: 'wx-account',
        token: 'token-12345678',
        base_url: 'https://wx.example.com',
        timeout_seconds: 15,
        user_id: 'wx-user-1',
        binding_status: 'bound'
      }
    })
    getBindingMock.mockResolvedValue({
      data: {
        user_id: 'user-1',
        weixin_account_id: 'wx-account',
        base_url: 'https://wx.example.com',
        bot_type: '3',
        channel_version: '1.0.2',
        binding_status: 'bound',
        weixin_user_id: 'wx-user-1'
      }
    })
    getParamsMock.mockResolvedValue({
      data: {
        base_url: 'https://wx.example.com',
        bot_type: '3',
        channel_version: '1.0.2',
        weixin_default_base_url: 'https://ilinkai.weixin.qq.com',
        weixin_default_bot_type: '3',
        weixin_default_channel_version: '1.0.2',
        session_timeout_seconds: 3600,
        token_refresh_enabled: true
      }
    })
    getAutoReplyStatusMock.mockResolvedValue({
      data: buildAutoReplyStatus()
    })
    getRulesMock.mockResolvedValue({
      data: []
    })
    startAutoReplyMock.mockResolvedValue({
      data: buildAutoReplyStatus({ auto_reply_running: true })
    })
    stopAutoReplyMock.mockResolvedValue({
      data: buildAutoReplyStatus({ auto_reply_enabled: false, auto_reply_running: false })
    })
    restartAutoReplyMock.mockResolvedValue({
      data: buildAutoReplyStatus({ auto_reply_running: true })
    })
    processAutoReplyOnceMock.mockResolvedValue({
      data: {
        ok: true,
        status: 'ok',
        processed: 2,
        skipped: 1,
        duplicates: 0,
        errors: 0,
        cursor_advanced: true,
        cursor: 'cursor-2'
      }
    })
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

  it('展示自动回复状态并支持启动、停止、重启和单次处理', async () => {
    render(<BrowserRouter><CommunicationPage /></BrowserRouter>)

    expect(await screen.findByText('绑定状态：已绑定')).toBeInTheDocument()
    expect(screen.getByText('运行状态：已停止')).toBeInTheDocument()
    expect(screen.getByText('启用状态：已启用')).toBeInTheDocument()
    expect(screen.getByText('当前游标：cursor-1')).toBeInTheDocument()

    fireEvent.click(screen.getByText('启动自动回复'))
    await waitFor(() => {
      expect(startAutoReplyMock).toHaveBeenCalledTimes(1)
      expect(screen.getByText('自动回复已启动')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('停止自动回复'))
    await waitFor(() => {
      expect(stopAutoReplyMock).toHaveBeenCalledTimes(1)
      expect(screen.getByText('自动回复已停止')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('重启自动回复'))
    await waitFor(() => {
      expect(restartAutoReplyMock).toHaveBeenCalledTimes(1)
      expect(screen.getByText('自动回复已重启')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('单次处理'))
    await waitFor(() => {
      expect(processAutoReplyOnceMock).toHaveBeenCalledTimes(1)
      expect(screen.getByText('单次处理完成：成功 2 条，跳过 1 条，重复 0 条')).toBeInTheDocument()
      expect(screen.getByText('单次处理结果：状态 正常，成功 2 条，跳过 1 条，重复 0 条，错误 0 条')).toBeInTheDocument()
    })
  })

  it('在未绑定时禁用自动回复操作按钮', async () => {
    getConfigMock.mockResolvedValueOnce({
      data: {
        account_id: 'wx-account',
        token: 'token-12345678',
        base_url: 'https://wx.example.com',
        timeout_seconds: 15,
        user_id: '',
        binding_status: 'unbound'
      }
    })
    getBindingMock.mockResolvedValueOnce({
      data: {
        user_id: 'user-1',
        weixin_account_id: '',
        base_url: '',
        bot_type: '',
        channel_version: '',
        binding_status: 'unbound',
        weixin_user_id: ''
      }
    })
    getAutoReplyStatusMock.mockResolvedValueOnce({
      data: buildAutoReplyStatus({
        binding_status: 'unbound',
        binding_ready: false,
        weixin_account_id: '',
        weixin_user_id: '',
        auto_reply_enabled: false,
        auto_reply_running: false,
        cursor: '',
        processed_message_count: 0,
      })
    })

    render(<BrowserRouter><CommunicationPage /></BrowserRouter>)

    expect(await screen.findByText('当前未完成绑定，自动回复操作暂不可用。')).toBeInTheDocument()
    expect(screen.getByText('启动自动回复')).toBeDisabled()
    expect(screen.getByText('重启自动回复')).toBeDisabled()
    expect(screen.getByText('单次处理')).toBeDisabled()
  })

  it('在保存前校验 Base URL 格式', async () => {
    render(<BrowserRouter><CommunicationPage /></BrowserRouter>)

    const baseUrlInput = await screen.findByDisplayValue('https://wx.example.com')
    fireEvent.change(baseUrlInput, { target: { value: 'wx.example.com' } })
    fireEvent.click(screen.getByText('保存配置'))

    await waitFor(() => {
      expect(screen.getByText('Base URL 必须以 http:// 或 https:// 开头')).toBeInTheDocument()
    })
    expect(saveConfigMock).not.toHaveBeenCalled()
  })
})
