import { renderHook, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useWechatConfig } from '../useWechatConfig'
import { weixinAPI } from '@/shared/api/api'

// Mock weixinAPI
vi.mock('@/shared/api/api', () => ({
  weixinAPI: {
    getConfig: vi.fn(),
    getBinding: vi.fn(),
    getAutoReplyStatus: vi.fn(),
    getParams: vi.fn(),
    getRules: vi.fn(),
    startAutoReply: vi.fn(),
    stopAutoReply: vi.fn(),
    restartAutoReply: vi.fn(),
    processAutoReplyOnce: vi.fn(),
    createRule: vi.fn(),
    updateRule: vi.fn(),
    deleteRule: vi.fn(),
    toggleRuleActive: vi.fn(),
    restoreDefaultRules: vi.fn(),
    deleteBinding: vi.fn(),
    updateParams: vi.fn(),
    startQrLogin: vi.fn(),
    cancelQrLogin: vi.fn(),
    saveConfig: vi.fn(),
    healthCheck: vi.fn()
  }
}))

// Mock appLogger
vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    error: vi.fn(),
    warn: vi.fn()
  }
}))

// Mock URL.createObjectURL
global.URL.createObjectURL = vi.fn()
global.URL.revokeObjectURL = vi.fn()

describe('useWechatConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(weixinAPI.getConfig).mockResolvedValue({ data: { account_id: 'test', token: 'token', base_url: 'http://test.com', timeout_seconds: 15, binding_status: 'bound' } })
    vi.mocked(weixinAPI.getBinding).mockResolvedValue({ data: { binding_status: 'bound' } })
    vi.mocked(weixinAPI.getAutoReplyStatus).mockResolvedValue({ data: { auto_reply_running: false } })
    vi.mocked(weixinAPI.getParams).mockResolvedValue({ data: { bot_type: '3' } })
    vi.mocked(weixinAPI.getRules).mockResolvedValue({ data: [] })
  })

  it('should load initial data correctly', async () => {
    const { result } = renderHook(() => useWechatConfig())
    
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })
    
    expect(weixinAPI.getConfig).toHaveBeenCalled()
    expect(weixinAPI.getBinding).toHaveBeenCalled()
    expect(weixinAPI.getAutoReplyStatus).toHaveBeenCalled()
    expect(weixinAPI.getParams).toHaveBeenCalled()
    expect(weixinAPI.getRules).toHaveBeenCalled()
    
    expect(result.current.weixinConfig.account_id).toBe('test')
    expect(result.current.currentBindingStatus).toBe('bound')
  })

  it('should handle API errors gracefully', async () => {
    vi.mocked(weixinAPI.getConfig).mockRejectedValue(new Error('Load Error'))
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })
    expect(result.current.configLoadError).toContain('加载微信配置失败')
  })

  it('should handle start auto reply', async () => {
    vi.mocked(weixinAPI.startAutoReply).mockResolvedValue({ data: { auto_reply_running: true } })
    vi.mocked(weixinAPI.getAutoReplyStatus).mockResolvedValue({ data: { auto_reply_running: true } })
    
    const { result } = renderHook(() => useWechatConfig())
    
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })
    
    await act(async () => {
      await result.current.handleStartAutoReply()
    })
    
    expect(weixinAPI.startAutoReply).toHaveBeenCalled()
    await waitFor(() => {
      expect(result.current.autoReplyStatus?.auto_reply_running).toBe(true)
    })
  })

  it('should handle stop auto reply', async () => {
    vi.mocked(weixinAPI.stopAutoReply).mockResolvedValue({ data: { auto_reply_running: false } })
    
    const { result } = renderHook(() => useWechatConfig())
    
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })
    
    await act(async () => {
      await result.current.handleStopAutoReply()
    })
    
    expect(weixinAPI.stopAutoReply).toHaveBeenCalled()
  })

  it('should handle restart auto reply', async () => {
    vi.mocked(weixinAPI.restartAutoReply).mockResolvedValue({ data: { auto_reply_running: true } })
    vi.mocked(weixinAPI.getAutoReplyStatus).mockResolvedValue({ data: { auto_reply_running: true } })
    
    const { result } = renderHook(() => useWechatConfig())
    
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })
    
    await act(async () => {
      await result.current.handleRestartAutoReply()
    })
    
    expect(weixinAPI.restartAutoReply).toHaveBeenCalled()
    await waitFor(() => {
      expect(result.current.autoReplyStatus?.auto_reply_running).toBe(true)
    })
  })

  it('should handle process auto reply once', async () => {
    vi.mocked(weixinAPI.processAutoReplyOnce).mockResolvedValue({ data: { ok: true, processed: 1 } })
    
    const { result } = renderHook(() => useWechatConfig())
    
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })
    
    await act(async () => {
      await result.current.handleProcessAutoReplyOnce()
    })
    
    expect(weixinAPI.processAutoReplyOnce).toHaveBeenCalled()
    expect(result.current.autoReplyProcessResult?.ok).toBe(true)
  })

  it('should handle unbind', async () => {
    vi.mocked(weixinAPI.deleteBinding).mockResolvedValue({ data: { ok: true } })
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleUnbind()
    })

    expect(weixinAPI.deleteBinding).toHaveBeenCalled()
  })

  it('should handle save weixin config', async () => {
    vi.mocked(weixinAPI.saveConfig).mockResolvedValue({ data: { ok: true } })
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleSaveWeixinConfig({ preventDefault: vi.fn() } as any)
    })

    expect(weixinAPI.saveConfig).toHaveBeenCalled()
  })

  it('should handle test weixin connection', async () => {
    vi.mocked(weixinAPI.healthCheck).mockResolvedValue({ data: { ok: true } })
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleTestWeixinConnection()
    })

    expect(weixinAPI.healthCheck).toHaveBeenCalled()
  })

  it('should handle save params', async () => {
    vi.mocked(weixinAPI.updateParams).mockResolvedValue({ data: { bot_type: '3' } })
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleSaveParams()
    })

    expect(weixinAPI.updateParams).toHaveBeenCalled()
  })

  it('should handle save rules', async () => {
    vi.mocked(weixinAPI.createRule).mockResolvedValue({ data: { id: 1 } } as any)
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleSaveRule({
        rule_name: 'test',
        match_type: 'keyword',
        match_pattern: 'hello',
        reply_content: 'hi',
        is_active: true,
        priority: 0
      })
    })

    expect(weixinAPI.createRule).toHaveBeenCalled()
  })

  it('should format status time', () => {
    const { result } = renderHook(() => useWechatConfig())
    expect(result.current.formatStatusTime('2026-05-01T12:00:00Z')).toBeDefined()
    expect(result.current.formatStatusTime('')).toBe('暂无')
  })

  it('should handle start qr login', async () => {
    vi.mocked(weixinAPI.startQrLogin).mockResolvedValue({ data: { session_key: 'sk', qrcode: 'qr', state: 'waiting' } })
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleStartQrLogin()
    })

    expect(weixinAPI.startQrLogin).toHaveBeenCalled()
    expect(result.current.qrSessionKey).toBe('sk')
  })

  it('should handle cancel qr login', () => {
    const { result } = renderHook(() => useWechatConfig())
    act(() => {
      result.current.handleCancelQrLogin()
    })
    expect(result.current.qrStatus).toBe('idle')
  })

  it('should handle delete rule', async () => {
    window.confirm = vi.fn().mockReturnValue(true)
    vi.mocked(weixinAPI.deleteRule).mockResolvedValue({ data: { ok: true } })
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleDeleteRule(1)
    })

    expect(weixinAPI.deleteRule).toHaveBeenCalledWith(1)
  })

  it('should handle toggle rule active', async () => {
    vi.mocked(weixinAPI.updateRule).mockResolvedValue({ data: { id: 1 } } as any)
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleToggleRuleActive({ id: 1, is_active: true } as any)
    })

    expect(weixinAPI.updateRule).toHaveBeenCalledWith(1, { is_active: false })
  })

  it('should handle restore default rules', async () => {
    window.confirm = vi.fn().mockReturnValue(true)
    vi.mocked(weixinAPI.createRule).mockResolvedValue({ data: { id: 1 } } as any)
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleRestoreDefaultRules()
    })

    expect(weixinAPI.createRule).toHaveBeenCalled()
  })

  it('should format binding result text', () => {
    const { result } = renderHook(() => useWechatConfig())
    expect(result.current.buildBindingResultText('user1', 'bound')).toBe('绑定成功，用户 ID：user1，绑定状态：bound')
  })

  it('should build next step text', () => {
    const { result } = renderHook(() => useWechatConfig())
    expect(result.current.buildNextStepText('bound', 'user1')).toContain('配置已自动回填')
    expect(result.current.buildNextStepText('pending')).toContain('绑定仍在处理中')
    expect(result.current.buildNextStepText('unknown')).toContain('配置已更新')
  })

  it('should format auto reply binding status', () => {
    const { result } = renderHook(() => useWechatConfig())
    expect(result.current.formatAutoReplyBindingStatus('bound')).toBe('已绑定')
    expect(result.current.formatAutoReplyBindingStatus('pending')).toBe('处理中')
    expect(result.current.formatAutoReplyBindingStatus('unbound')).toBe('未绑定')
  })

  it('should validate weixin config correctly', async () => {
    const { result } = renderHook(() => useWechatConfig())
    
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    // Set invalid base URL
    await act(async () => {
      result.current.setWeixinConfig(prev => ({ ...prev, base_url: 'invalid-url' }))
    })
    
    // Save should fail validation
    await act(async () => {
      await result.current.handleSaveWeixinConfig({ preventDefault: vi.fn() } as any)
    })
    
    expect(result.current.message?.text).toContain('Base URL 必须以 http:// 或 https:// 开头')

    // Set valid but missing account_id
    await act(async () => {
      result.current.setWeixinConfig(prev => ({ ...prev, base_url: 'http://test.com', account_id: '' }))
    })
    
    await act(async () => {
      await result.current.handleSaveWeixinConfig({ preventDefault: vi.fn() } as any)
    })
    
    expect(result.current.message?.text).toContain('微信配置不完整，account_id 和 token 为必填项')

    // Set invalid timeout
    await act(async () => {
      result.current.setWeixinConfig(prev => ({ ...prev, account_id: 'test', timeout_seconds: 0 }))
    })

    await act(async () => {
      await result.current.handleSaveWeixinConfig({ preventDefault: vi.fn() } as any)
    })
    
    expect(result.current.message?.text).toContain('超时时间必须是大于 0 的整数')
  })

  it('should handle test connection failure', async () => {
    vi.mocked(weixinAPI.healthCheck).mockRejectedValue(new Error('Test Failed'))
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleTestWeixinConnection()
    })

    expect(result.current.message?.text).toBe('测试连接请求失败')
  })

  it('should handle save config failure', async () => {
    vi.mocked(weixinAPI.saveConfig).mockRejectedValue(new Error('Save Failed'))
    const { result } = renderHook(() => useWechatConfig())
    await waitFor(() => {
      expect(result.current.loadingWeixin).toBe(false)
    })

    await act(async () => {
      await result.current.handleSaveWeixinConfig({ preventDefault: vi.fn() } as any)
    })

    expect(result.current.message?.text).toBe('微信通讯配置保存失败')
  })
})
