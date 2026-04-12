import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import QRCode from 'qrcode'
import SettingsPage from '@/features/settings/SettingsPage'
import CommunicationPage from '@/features/chat/CommunicationPage'
import { weixinAPI } from '@/shared/api/api'

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,mocked-qrcode')
  }
}))

vi.mock('@/shared/api/api', () => ({
  weixinAPI: {
    getConfig: vi.fn(),
    saveConfig: vi.fn(),
    healthCheck: vi.fn(),
    getBinding: vi.fn(),
    getParams: vi.fn(),
    getAutoReplyStatus: vi.fn(),
    startQrLogin: vi.fn(),
    waitQrLogin: vi.fn(),
    exitQrLogin: vi.fn(),
  },
  promptsAPI: {
    getActive: vi.fn().mockResolvedValue({ data: null }),
  },
  conversationAPI: {
    getCollectionStatus: vi.fn().mockResolvedValue({ data: { enabled: false } }),
    getRecordsPreview: vi.fn().mockResolvedValue({ data: { records: [] } }),
  }
}))

vi.mock('@/features/billingApi', () => ({
  billingAPI: {
    getModels: vi.fn().mockResolvedValue({ data: { models: [] } }),
    getRetention: vi.fn().mockResolvedValue({ data: { retention_days: 365 } }),
  }
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    getProviders: vi.fn().mockResolvedValue({ data: { providers: [] } }),
  }
}))

describe('CommunicationPage Weixin Clawbot Configuration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
    ;(weixinAPI.getConfig as any).mockResolvedValue({
      data: {
        account_id: 'test_account',
        token: 'test_token',
        base_url: 'https://test.weixin.qq.com',
        timeout_seconds: 20
      }
    })
    ;(weixinAPI.getBinding as any).mockResolvedValue({
      data: {
        user_id: 'user-1',
        weixin_account_id: '',
        base_url: 'https://test.weixin.qq.com',
        bot_type: '3',
        channel_version: '1.0.2',
        binding_status: 'unbound',
        weixin_user_id: ''
      }
    })
    ;(weixinAPI.getParams as any).mockResolvedValue({
      data: {
        base_url: 'https://test.weixin.qq.com',
        bot_type: '3',
        channel_version: '1.0.2',
        weixin_default_base_url: 'https://ilinkai.weixin.qq.com',
        weixin_default_bot_type: '3',
        weixin_default_channel_version: '1.0.2',
        session_timeout_seconds: 3600,
        token_refresh_enabled: true
      }
    })
    ;(weixinAPI.getAutoReplyStatus as any).mockResolvedValue({
      data: {
        user_id: 'user-1',
        binding_status: 'unbound',
        binding_ready: false,
        weixin_account_id: '',
        weixin_user_id: '',
        auto_reply_enabled: false,
        auto_reply_running: false,
        last_poll_at: '',
        last_poll_status: 'idle',
        last_error: '',
        last_error_at: '',
        last_success_at: '',
        last_reply_at: '',
        last_replied_user_id: '',
        last_processed_message_id: '',
        cursor: '',
        processed_message_count: 0
      }
    })
    ;(weixinAPI.startQrLogin as any).mockResolvedValue({
      data: {
        success: true,
        state: 'pending',
        message: '使用微信扫描以下二维码，以完成连接。',
        session_key: 'session_1',
        status: 'wait',
        qrcode: 'qrcode_1',
        qrcode_content: 'https://test.weixin.qq.com/qrcode-content-1',
        qrcode_url: 'https://test.weixin.qq.com/qrcode-1.png'
      }
    })
    ;(weixinAPI.waitQrLogin as any).mockResolvedValue({
      data: {
        success: true,
        state: 'pending',
        connected: false,
        session_key: 'session_1',
        status: 'wait',
        message: '等待扫码中'
      }
    })
    ;(weixinAPI.exitQrLogin as any).mockResolvedValue({
      data: {
        message: 'success',
        cleared_sessions: 1
      }
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    cleanup()
  })

  it('loads and displays weixin config on communication tab', async () => {
    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(weixinAPI.getConfig).toHaveBeenCalledTimes(1)
    })

    const accountIdInput = screen.getByPlaceholderText('输入微信通讯账户 ID') as HTMLInputElement
    const tokenInput = screen.getByPlaceholderText('输入 iLink Bot Token') as HTMLInputElement

    expect(accountIdInput.value).toBe('test_account')
    expect(tokenInput.value).toBe('test_token')
  })

  it('validates required fields before saving', async () => {
    ;(weixinAPI.getConfig as any).mockResolvedValue({
      data: { account_id: '', token: '' }
    })

    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(weixinAPI.getConfig).toHaveBeenCalled()
    })

    const saveBtn = screen.getByText('保存配置')
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(screen.getByText('微信配置不完整，account_id 和 token 为必填项')).toBeInTheDocument()
    })

    expect(weixinAPI.saveConfig).not.toHaveBeenCalled()
  })

  it('calls saveConfig API on valid save', async () => {
    ;(weixinAPI.saveConfig as any).mockResolvedValue({ data: { message: 'success' } })

    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(weixinAPI.getConfig).toHaveBeenCalled()
    })

    const saveBtn = screen.getByText('保存配置')
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(weixinAPI.saveConfig).toHaveBeenCalledWith({
        account_id: 'test_account',
        token: 'test_token',
        base_url: 'https://test.weixin.qq.com',
        timeout_seconds: 20,
        user_id: '',
        binding_status: 'unbound'
      })
      expect(screen.getByText('微信通讯配置保存成功')).toBeInTheDocument()
    })
  })

  it('displays health check result successfully', async () => {
    ;(weixinAPI.healthCheck as any).mockResolvedValue({
      data: {
        ok: true,
        issues: [],
        suggestions: []
      }
    })

    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(weixinAPI.getConfig).toHaveBeenCalled()
    })

    const testBtn = screen.getByText('测试连接')
    fireEvent.click(testBtn)

    await waitFor(() => {
      expect(weixinAPI.healthCheck).toHaveBeenCalledWith({
        account_id: 'test_account',
        token: 'test_token',
        base_url: 'https://test.weixin.qq.com',
        timeout_seconds: 20,
        user_id: '',
        binding_status: 'unbound'
      })
      expect(screen.getByText('测试连接成功！')).toBeInTheDocument()
      expect(screen.getByText('配置正常，微信适配器健康检查通过。')).toBeInTheDocument()
    })
  })

  it('redirects legacy settings communication tab to standalone page', async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=communication']}>
        <Routes>
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/communication" element={<CommunicationPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '通讯配置' })).toBeInTheDocument()
      expect(screen.queryByText('通用设置')).not.toBeInTheDocument()
      expect(weixinAPI.getConfig).toHaveBeenCalled()
    })
  })

  it('normalizes confirmed binding status from persisted config', async () => {
    ;(weixinAPI.getConfig as any).mockResolvedValue({
      data: {
        account_id: 'test_account',
        token: 'test_token',
        base_url: 'https://test.weixin.qq.com',
        timeout_seconds: 20,
        user_id: 'persisted-confirmed-user',
        binding_status: 'confirmed'
      }
    })

    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('绑定结果：绑定成功，用户 ID：persisted-confirmed-user，绑定状态：bound')).toBeInTheDocument()
    })
  })

  it('shows persisted binding result after loading config', async () => {
    ;(weixinAPI.getConfig as any).mockResolvedValue({
      data: {
        account_id: 'test_account',
        token: 'test_token',
        base_url: 'https://test.weixin.qq.com',
        timeout_seconds: 20,
        user_id: 'persisted-user',
        binding_status: 'bound'
      }
    })

    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('绑定结果：绑定成功，用户 ID：persisted-user，绑定状态：bound')).toBeInTheDocument()
    })
  })

  it('starts qr login and auto handles confirmed success state with next-step guidance', async () => {
    ;(weixinAPI.getConfig as any)
      .mockResolvedValueOnce({
        data: {
          account_id: 'test_account',
          token: 'test_token',
          base_url: 'https://test.weixin.qq.com',
          timeout_seconds: 20
        }
      })
      .mockResolvedValueOnce({
        data: {
          account_id: 'wx_account',
          token: 'wx_token',
          base_url: 'https://ilinkai.weixin.qq.com',
          timeout_seconds: 20,
          user_id: 'wx-user-1',
          binding_status: 'bound'
        }
      })
    ;(weixinAPI.waitQrLogin as any).mockResolvedValue({
      data: {
        success: true,
        state: 'success',
        connected: true,
        session_key: 'session_1',
        status: 'confirmed',
        message: '与微信连接成功',
        account_id: 'wx_account',
        token: 'wx_token',
        base_url: 'https://ilinkai.weixin.qq.com',
        user_id: 'wx-user-1',
        binding_status: 'bound'
      }
    })

    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(weixinAPI.getConfig).toHaveBeenCalledTimes(1)
    })

    fireEvent.click(screen.getByText('获取登录二维码'))

    await waitFor(() => {
      expect(weixinAPI.startQrLogin).toHaveBeenCalledWith({
        base_url: 'https://test.weixin.qq.com',
        timeout_seconds: 20,
        force: true
      })
      expect(weixinAPI.waitQrLogin).toHaveBeenCalledWith({
        session_key: 'session_1',
        timeout_seconds: 20,
        qrcode: 'qrcode_1',
        base_url: 'https://test.weixin.qq.com'
      })
      expect(QRCode.toDataURL).toHaveBeenCalledWith('https://test.weixin.qq.com/qrcode-content-1', expect.any(Object))
      expect(screen.getByText('微信扫码登录成功，配置已自动更新；绑定成功，用户 ID：wx-user-1，绑定状态：bound 后续流程：配置已自动回填。建议先点击“测试连接”确认链路可用，再进入聊天页验证消息收发。')).toBeInTheDocument()
      expect(screen.getByText('绑定结果：绑定成功，用户 ID：wx-user-1，绑定状态：bound')).toBeInTheDocument()
      expect(screen.getByText('后续流程：配置已自动回填。建议先点击“测试连接”确认链路可用，再进入聊天页验证消息收发。')).toBeInTheDocument()
      expect(weixinAPI.getConfig).toHaveBeenCalledTimes(2)
    })
  })

  it('shows half-success state from backend state field and keeps polling', async () => {
    ;(weixinAPI.waitQrLogin as any).mockResolvedValue({
      data: {
        success: true,
        state: 'half_success',
        connected: false,
        session_key: 'session_1',
        status: 'scaned',
        message: 'waiting for confirm',
        auth_id: 'auth_123'
      }
    })

    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(weixinAPI.getConfig).toHaveBeenCalled()
    })

    fireEvent.click(screen.getByText('获取登录二维码'))

    await waitFor(() => {
      expect(screen.getByRole('img')).toBeInTheDocument()
      expect(screen.getByText((_, element) => element?.textContent === '当前阶段：half_success；当前状态：waiting for confirm（auth_123）')).toBeInTheDocument()
    })
  })

  it('updates polling base url after redirect status', async () => {
    ;(weixinAPI.waitQrLogin as any)
      .mockResolvedValueOnce({
        data: {
          success: true,
          state: 'half_success',
          connected: false,
          session_key: 'session_1',
          status: 'scaned_but_redirect',
          message: '已扫码，正在切换轮询节点',
          redirect_host: 'redirect.weixin.qq.com',
          base_url: 'https://redirect.weixin.qq.com'
        }
      })
      .mockResolvedValueOnce({
        data: {
          success: true,
          state: 'pending',
          connected: false,
          session_key: 'session_1',
          status: 'wait',
          message: '等待扫码中',
          base_url: 'https://redirect.weixin.qq.com'
        }
      })

    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(weixinAPI.getConfig).toHaveBeenCalled()
    })

    fireEvent.click(screen.getByText('获取登录二维码'))

    await waitFor(() => {
      expect(screen.getByText((_, element) => element?.textContent === '当前阶段：half_success；当前状态：已扫码，正在切换轮询节点（redirect.weixin.qq.com）')).toBeInTheDocument()
    })

    await waitFor(() => {
      expect((weixinAPI.waitQrLogin as any).mock.calls[1][0]).toEqual({
        session_key: 'session_1',
        timeout_seconds: 20,
        qrcode: 'qrcode_1',
        base_url: 'https://redirect.weixin.qq.com'
      })
    }, { timeout: 3500 })
  })

  it('cancels qr login and calls exit api', async () => {
    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(weixinAPI.getConfig).toHaveBeenCalled()
    })

    fireEvent.click(screen.getByText('获取登录二维码'))

    await waitFor(() => {
      expect(screen.getByAltText('微信登录二维码')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('取消扫码登录'))

    await waitFor(() => {
      expect(weixinAPI.exitQrLogin).toHaveBeenCalledWith({
        session_key: 'session_1',
        clear_config: false
      })
      expect(screen.queryByAltText('微信登录二维码')).not.toBeInTheDocument()
    })
  })

  it('handles refreshing status from backend as half_success state', async () => {
    ;(weixinAPI.waitQrLogin as any).mockResolvedValue({
      data: {
        success: true,
        state: 'half_success',
        connected: false,
        session_key: 'session_1',
        status: 'refreshing',
        message: '二维码已过期，正在刷新',
        qrcode: 'qr-refresh-1',
        qrcode_url: 'https://example.com/qr-refresh-1.png'
      }
    })

    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(weixinAPI.getConfig).toHaveBeenCalled()
    })

    fireEvent.click(screen.getByText('获取登录二维码'))

    await waitFor(() => {
      expect(screen.getByText((_, element) => element?.textContent === '当前阶段：half_success；当前状态：二维码已过期，正在刷新')).toBeInTheDocument()
    })
  })

  it('handles expired status and displays failure message', async () => {
    ;(weixinAPI.waitQrLogin as any).mockResolvedValue({
      data: {
        success: true,
        state: 'failed',
        connected: false,
        session_key: 'session_1',
        status: 'expired',
        message: '二维码已过期，请重新获取',
        qrcode: 'qr-expired-1',
        qrcode_url: 'https://example.com/qr-expired-1.png'
      }
    })

    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(weixinAPI.getConfig).toHaveBeenCalled()
    })

    fireEvent.click(screen.getByText('获取登录二维码'))

    await waitFor(() => {
      expect(screen.getByText((_, element) => element?.textContent === '当前阶段：failed；当前状态：二维码已过期，请重新获取')).toBeInTheDocument()
    })
  })

  it('displays ilink integration description text', async () => {
    render(
      <MemoryRouter initialEntries={['/communication']}>
        <CommunicationPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('配置外部通讯渠道，如微信 iLink 集成。')).toBeInTheDocument()
    })
  })
})
