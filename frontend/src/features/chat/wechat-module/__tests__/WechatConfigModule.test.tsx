import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import WechatConfigModule from '../WechatConfigModule'
import { useWechatConfig } from '../useWechatConfig'

// Mock the hook
vi.mock('../useWechatConfig', () => ({
  useWechatConfig: vi.fn()
}))

const mockHookReturn = {
  message: null,
  weixinConfig: { account_id: 'test', token: 'token' },
  setWeixinConfig: vi.fn(),
  loadingWeixin: false,
  configLoadError: null,
  savingWeixin: false,
  testingWeixin: false,
  weixinHealthResult: null,
  startingQrLogin: false,
  pollingQrLogin: false,
  qrSessionKey: '',
  qrCodeUrl: '',
  qrImageLoadError: '',
  qrStatus: 'idle',
  qrState: null,
  qrStatusText: '',
  qrStatusHint: '',
  qrBindingResult: null,
  bindingInfo: { binding_status: 'bound' },
  loadingBinding: false,
  unbinding: false,
  bindingError: null,
  autoReplyStatus: { auto_reply_running: false, binding_ready: true },
  loadingAutoReplyStatus: false,
  autoReplyStatusError: null,
  autoReplyAction: null,
  autoReplyProcessResult: null,
  paramsConfig: {},
  paramsLoadError: null,
  editBotType: '',
  setEditBotType: vi.fn(),
  editChannelVersion: '',
  setEditChannelVersion: vi.fn(),
  savingParams: false,
  rules: [],
  loadingRules: false,
  rulesError: null,
  editingRule: null,
  setEditingRule: vi.fn(),
  savingRule: false,
  currentBindingStatus: 'bound',
  isAutoReplyBindingReady: true,
  autoReplyBusy: false,
  canStartAutoReply: true,
  canStopAutoReply: false,
  canRestartAutoReply: true,
  canProcessAutoReplyOnce: true,
  formatStatusTime: vi.fn(),
  buildBindingResultText: vi.fn(),
  buildNextStepText: vi.fn(),
  formatAutoReplyBindingStatus: vi.fn(),
  formatAutoReplyPollStatus: vi.fn(),
  loadBindingInfo: vi.fn(),
  loadAutoReplyStatus: vi.fn(),
  loadParamsConfig: vi.fn(),
  loadWeixinConfig: vi.fn(),
  loadRules: vi.fn(),
  handleUnbind: vi.fn(),
  handleSaveParams: vi.fn(),
  handleStartQrLogin: vi.fn(),
  handleCancelQrLogin: vi.fn(),
  handleSaveWeixinConfig: vi.fn(),
  handleTestWeixinConnection: vi.fn(),
  handleStartAutoReply: vi.fn(),
  handleStopAutoReply: vi.fn(),
  handleRestartAutoReply: vi.fn(),
  handleProcessAutoReplyOnce: vi.fn(),
  handleSaveRule: vi.fn(),
  handleDeleteRule: vi.fn(),
  handleToggleRuleActive: vi.fn(),
  handleRestoreDefaultRules: vi.fn()
}

describe('WechatConfigModule', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useWechatConfig).mockReturnValue(mockHookReturn as any)
  })

  it('renders without crashing', () => {
    render(<WechatConfigModule />)
    expect(screen.getByText('微信通讯配置')).toBeInTheDocument()
  })

  it('shows auto reply buttons and they are clickable', async () => {
    render(<WechatConfigModule />)
    
    const startBtn = screen.getByText('启动自动回复')
    expect(startBtn).toBeInTheDocument()
    expect(startBtn).not.toBeDisabled()
    
    fireEvent.click(startBtn)
    expect(mockHookReturn.handleStartAutoReply).toHaveBeenCalled()
    
    const processBtn = screen.getByText('单次处理')
    expect(processBtn).toBeInTheDocument()
    fireEvent.click(processBtn)
    expect(mockHookReturn.handleProcessAutoReplyOnce).toHaveBeenCalled()
  })

  it('renders loading state', () => {
    vi.mocked(useWechatConfig).mockReturnValue({
      ...mockHookReturn,
      loadingWeixin: true,
      loadingBinding: true,
      loadingAutoReplyStatus: true,
      loadingRules: true
    } as any)
    render(<WechatConfigModule />)
    expect(screen.getByText('加载配置中...')).toBeInTheDocument()
  })

  it('handles edit and save rule', () => {
    render(<WechatConfigModule />)
    
    // Check if adding new rule works
    const addBtn = screen.getByText('添加新规则')
    fireEvent.click(addBtn)
    expect(mockHookReturn.setEditingRule).toHaveBeenCalled()
  })

  it('shows qr login section', () => {
    vi.mocked(useWechatConfig).mockReturnValue({
      ...mockHookReturn,
      currentBindingStatus: 'unbound',
      qrStatus: 'waiting',
      qrCodeUrl: 'http://test-qr'
    } as any)
    render(<WechatConfigModule />)
    
    expect(screen.getByText('获取登录二维码')).toBeInTheDocument()
    expect(screen.getByAltText('微信登录二维码')).toBeInTheDocument()
  })
    vi.mocked(useWechatConfig).mockReturnValue({
      ...mockHookReturn,
      autoReplyStatus: { auto_reply_running: true, binding_ready: true },
      canStartAutoReply: false,
      canStopAutoReply: true
    } as any)
    
    render(<WechatConfigModule />)
    
    const startBtn = screen.getByText('启动自动回复')
    expect(startBtn).toBeDisabled()
    
    const stopBtn = screen.getByText('停止自动回复')
    expect(stopBtn).not.toBeDisabled()
    fireEvent.click(stopBtn)
    expect(mockHookReturn.handleStopAutoReply).toHaveBeenCalled()
  })
})
