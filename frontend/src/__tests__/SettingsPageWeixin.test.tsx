import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import SettingsPage from '../pages/SettingsPage'
import { weixinAPI, promptsAPI, conversationAPI } from '../services/api'
import { billingAPI } from '../services/billingApi'
import { modelsAPI } from '../services/modelsApi'

vi.mock('../services/api', () => ({
  weixinAPI: {
    getConfig: vi.fn(),
    saveConfig: vi.fn(),
    healthCheck: vi.fn(),
  },
  promptsAPI: {
    getActive: vi.fn().mockResolvedValue({ data: null }),
  },
  conversationAPI: {
    getCollectionStatus: vi.fn().mockResolvedValue({ data: { enabled: false } }),
    getRecordsPreview: vi.fn().mockResolvedValue({ data: { records: [] } }),
  }
}))

vi.mock('../services/billingApi', () => ({
  billingAPI: {
    getModels: vi.fn().mockResolvedValue({ data: { models: [] } }),
    getRetention: vi.fn().mockResolvedValue({ data: { retention_days: 365 } }),
  }
}))

vi.mock('../services/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    getProviders: vi.fn().mockResolvedValue({ data: { providers: [] } }),
  }
}))

describe('SettingsPage Weixin Clawbot Configuration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(weixinAPI.getConfig as any).mockResolvedValue({
      data: {
        account_id: 'test_account',
        token: 'test_token',
        base_url: 'https://test.weixin.qq.com',
        timeout_seconds: 20
      }
    })
  })

  afterEach(() => {
    cleanup()
  })

  it('loads and displays weixin config on communication tab', async () => {
    render(<SettingsPage />)
    
    // Click on Communication tab
    const commTab = screen.getByText('通讯配置')
    fireEvent.click(commTab)

    // Wait for the inputs to be populated
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

    render(<SettingsPage />)
    fireEvent.click(screen.getByText('通讯配置'))

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

    render(<SettingsPage />)
    fireEvent.click(screen.getByText('通讯配置'))

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
        timeout_seconds: 20
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

    render(<SettingsPage />)
    fireEvent.click(screen.getByText('通讯配置'))

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
        timeout_seconds: 20
      })
      expect(screen.getByText('测试连接成功！')).toBeInTheDocument()
      expect(screen.getByText('配置正常，微信适配器健康检查通过。')).toBeInTheDocument()
    })
  })
})