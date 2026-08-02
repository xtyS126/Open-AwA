/**
 * UserPage 测试套件 — 用户中心页面（当前 UI：个人信息/画像总览/事实管理/洋葱画像四标签）
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import UserCenterPage from '@/features/user/UserCenterPage'
import { RouterTestProvider as BrowserRouter } from '@/shared/routing/testing'
import type { UserProfile, LoginDeviceItem } from '@/shared/api/api'

const { getProfileMock, getDevicesMock, logoutMock } = vi.hoisted(() => ({
  getProfileMock: vi.fn(),
  getDevicesMock: vi.fn(),
  logoutMock: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  userAPI: {
    getProfile: getProfileMock,
    getDevices: getDevicesMock,
    updateProfile: vi.fn().mockResolvedValue({ data: { message: 'ok' } }),
    uploadAvatar: vi.fn(),
    revokeDevice: vi.fn(),
    getPreferences: vi.fn().mockResolvedValue({ data: { preferences: {} } }),
    updatePreferences: vi.fn(),
  },
  passwordAPI: {
    change: vi.fn().mockResolvedValue({ data: { message: '密码修改成功' } }),
  },
  authAPI: {
    logout: vi.fn().mockResolvedValue({}),
  },
}))

vi.mock('@/shared/store/authStore', () => ({
  useAuthStore: () => ({
    user: { username: 'testuser' },
    logout: logoutMock,
  }),
}))

vi.mock('@/shared/store/profileStore', () => ({
  useProfileStore: () => ({
    facts: [],
    factsTotal: 0,
    confidenceScores: [],
    stats: null,
    extractionLogs: [],
    loading: false,
    extracting: false,
    error: null,
    fetchFacts: vi.fn(),
    fetchStats: vi.fn(),
    fetchExtractionLogs: vi.fn(),
  }),
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

function createMockProfile(overrides: Partial<UserProfile> = {}): UserProfile {
  return {
    user_id: 'test-user-001',
    username: 'testuser',
    nickname: '测试用户',
    avatar_url: null,
    email: 'test@example.com',
    phone: '13800138000',
    profile: { interests: ['编程', 'AI', '阅读'], total_actions: 42, active_hours: ['08:00', '14:00', '20:00'] },
    ...overrides,
  }
}

function createMockDevices(): LoginDeviceItem[] {
  return [
    { id: 1, device_type: 'desktop', ip_address: '192.168.1.100', user_agent: 'Chrome/120.0', logged_in_at: '2026-05-15T08:00:00Z', last_active_at: '2026-05-15T12:00:00Z', is_online: true, is_current: true },
    { id: 2, device_type: 'mobile', ip_address: '10.0.0.5', user_agent: 'iPhone Safari', logged_in_at: '2026-05-14T20:00:00Z', last_active_at: '2026-05-14T22:00:00Z', is_online: false, is_current: false },
  ]
}

describe('UserCenterPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ============ 加载 / 错误 ============
  it('渲染加载状态', () => {
    getProfileMock.mockImplementationOnce(() => new Promise(() => {}))
    getDevicesMock.mockImplementationOnce(() => new Promise(() => {}))
    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)
    expect(screen.getByText('加载用户信息...')).toBeInTheDocument()
  })

  it('加载失败显示错误和重试按钮', async () => {
    getProfileMock.mockRejectedValueOnce(new Error('fail'))
    getDevicesMock.mockRejectedValueOnce(new Error('fail'))
    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)
    await waitFor(() => { expect(screen.getByText('加载用户信息失败')).toBeInTheDocument() })
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })

  // ============ 标签导航 ============
  it('渲染四个标签页导航', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })
    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)
    await waitFor(() => { expect(screen.getByText('个人信息')).toBeInTheDocument() })
    expect(screen.getByText('画像总览')).toBeInTheDocument()
    expect(screen.getByText('事实管理')).toBeInTheDocument()
    expect(screen.getByText('洋葱画像')).toBeInTheDocument()
  })

  // ============ 个人信息 Tab（含密码修改和退出登录） ============
  it('个人信息标签显示密码修改和退出登录', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })
    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)
    await waitFor(() => { expect(screen.getByText('个人信息')).toBeInTheDocument() })

    // 个人信息 Tab 为默认 Tab，密码修改和退出登录直接在其中
    await waitFor(() => { expect(screen.getByRole('heading', { name: '修改密码' })).toBeInTheDocument() })
    expect(screen.getByRole('heading', { name: '退出登录' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '退出登录' })).toBeInTheDocument()
  })

  // ============ 设备管理（个人信息 Tab 子区域） ============
  it('个人信息标签包含设备列表', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })
    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)
    await waitFor(() => { expect(screen.getByText('个人信息')).toBeInTheDocument() })

    await waitFor(() => { expect(screen.getByRole('heading', { name: '登录设备' })).toBeInTheDocument() })
  })

  // ============ 退出登录 ============
  it('退出登录按钮触发 logout 并导航', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })
    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)
    await waitFor(() => { expect(screen.getByText('个人信息')).toBeInTheDocument() })

    // 退出登录在个人信息 Tab 中，无需切换
    await waitFor(() => { expect(screen.getByRole('button', { name: '退出登录' })).toBeInTheDocument() })

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
    await waitFor(() => { expect(logoutMock).toHaveBeenCalled() })
  })
})
