/**
 * UserPage 测试套件 — 用户中心页面的渲染和交互测试
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import UserCenterPage from '@/features/user/UserCenterPage'
import { BrowserRouter } from 'react-router-dom'
import type { UserProfile, LoginDeviceItem } from '@/shared/api/api'

const {
  getProfileMock,
  getDevicesMock,
  logoutMock,
  navigateMock,
} = vi.hoisted(() => ({
  getProfileMock: vi.fn(),
  getDevicesMock: vi.fn(),
  logoutMock: vi.fn(),
  navigateMock: vi.fn(),
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

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateMock,
  }
})

function createMockProfile(overrides: Partial<UserProfile> = {}): UserProfile {
  return {
    user_id: 'test-user-001',
    username: 'testuser',
    nickname: '测试用户',
    avatar_url: null,
    email: 'test@example.com',
    phone: '13800138000',
    profile: {
      interests: ['编程', 'AI', '阅读'],
      total_actions: 42,
      active_hours: ['08:00', '14:00', '20:00'],
    },
    ...overrides,
  }
}

function createMockDevices(): LoginDeviceItem[] {
  return [
    {
      id: 1,
      device_type: 'desktop',
      ip_address: '192.168.1.100',
      user_agent: 'Chrome/120.0',
      logged_in_at: '2026-05-15T08:00:00Z',
      last_active_at: '2026-05-15T12:00:00Z',
      is_online: true,
      is_current: true,
    },
    {
      id: 2,
      device_type: 'mobile',
      ip_address: '10.0.0.5',
      user_agent: 'iPhone Safari',
      logged_in_at: '2026-05-14T20:00:00Z',
      last_active_at: '2026-05-14T22:00:00Z',
      is_online: false,
      is_current: false,
    },
  ]
}

describe('UserCenterPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getProfileMock.mockReset()
    getDevicesMock.mockReset()
    logoutMock.mockReset()
    navigateMock.mockReset()
  })

  // ============ 加载状态测试 ============

  it('渲染加载状态时显示加载提示', () => {
    getProfileMock.mockImplementationOnce(
      () => new Promise(() => { /* 保持加载中 */ })
    )
    getDevicesMock.mockImplementationOnce(
      () => new Promise(() => { /* 保持加载中 */ })
    )

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    expect(screen.getByText('加载用户信息...')).toBeInTheDocument()
  })

  // ============ 错误状态测试 ============

  it('加载用户信息失败时显示错误提示和重试按钮', async () => {
    getProfileMock.mockRejectedValueOnce(new Error('加载失败'))
    getDevicesMock.mockRejectedValueOnce(new Error('加载失败'))

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('加载用户信息失败')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })

  it('点击重试按钮重新加载数据', async () => {
    getProfileMock.mockRejectedValueOnce(new Error('加载失败'))
    getDevicesMock.mockRejectedValueOnce(new Error('加载失败'))

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('加载用户信息失败')).toBeInTheDocument()
    })

    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    fireEvent.click(screen.getByRole('button', { name: '重试' }))

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
    })
  })

  // ============ 基本渲染测试 ============

  it('加载成功后渲染页面标题和三个标签页导航', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('用户中心')).toBeInTheDocument()
    })

    expect(screen.getByText('AI 画像')).toBeInTheDocument()
    expect(screen.getByText('安全设置')).toBeInTheDocument()
    expect(screen.getByText('设备管理')).toBeInTheDocument()
  })

  it('默认显示 AI 画像标签页内容', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
    })
  })

  // ============ AI 画像标签测试 ============

  it('AI 画像标签显示用户基本信息', async () => {
    const profile = createMockProfile()
    getProfileMock.mockResolvedValueOnce({ data: profile })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      const usernameInput = screen.getByDisplayValue('testuser')
      expect(usernameInput).toBeDisabled()
      expect(screen.getByDisplayValue('测试用户')).toBeInTheDocument()
      expect(screen.getByDisplayValue('test@example.com')).toBeInTheDocument()
      expect(screen.getByDisplayValue('13800138000')).toBeInTheDocument()
    })
  })

  it('没有头像时显示用户名首字母占位符', async () => {
    getProfileMock.mockResolvedValueOnce({
      data: createMockProfile({ avatar_url: null }),
    })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('T')).toBeInTheDocument()
    })
  })

  it('有头像地址时渲染头像图片', async () => {
    getProfileMock.mockResolvedValueOnce({
      data: createMockProfile({ avatar_url: 'https://example.com/avatar.png' }),
    })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      const img = screen.getByAltText('头像')
      expect(img).toHaveAttribute('src', 'https://example.com/avatar.png')
    })
  })

  it('AI 画像分析区域显示兴趣标签', async () => {
    const profile = createMockProfile()
    getProfileMock.mockResolvedValueOnce({ data: profile })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('AI 画像分析')).toBeInTheDocument()
    })

    expect(screen.getByText('编程')).toBeInTheDocument()
    expect(screen.getByText('AI')).toBeInTheDocument()
    expect(screen.getByText('阅读')).toBeInTheDocument()
  })

  it('AI 画像分析区域显示操作数统计', async () => {
    const profile = createMockProfile()
    getProfileMock.mockResolvedValueOnce({ data: profile })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('42')).toBeInTheDocument()
      expect(screen.getByText('近30天操作数')).toBeInTheDocument()
    })
  })

  it('AI 画像分析区域显示活跃时段', async () => {
    const profile = createMockProfile()
    getProfileMock.mockResolvedValueOnce({ data: profile })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('08:00')).toBeInTheDocument()
      expect(screen.getByText('14:00')).toBeInTheDocument()
      expect(screen.getByText('20:00')).toBeInTheDocument()
    })
  })

  // profile 字段为 null 时 AI 画像分析区域不渲染
  it('无 profile 数据时不显示 AI 画像分析区域', async () => {
    // 需要 profile 为 null/undefined 才能阻止 AI 区域渲染（空对象 {} 是 truthy）
    const profileWithoutAI = createMockProfile()
    profileWithoutAI.profile = null
    getProfileMock.mockResolvedValueOnce({ data: profileWithoutAI })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
      expect(screen.queryByText('AI 画像分析')).not.toBeInTheDocument()
    })
  })

  // 空 interests 数组在 JSX 中为 truthy（`[].map()` 返回 `[]`），不触发 || 回退
  // "暂无标签" 仅当 interests 为 undefined/null 时显示
  it('空兴趣标签时不显示标签内容', async () => {
    getProfileMock.mockResolvedValueOnce({
      data: createMockProfile({ profile: { interests: [], total_actions: 1 } }),
    })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('AI 画像分析')).toBeInTheDocument()
    })

    // interests 为空数组时，map 返回空数组（truthy），不渲染任何标签
    // 确认原本的标签不在页面上
    expect(screen.queryByText('编程')).not.toBeInTheDocument()
    expect(screen.queryByText('AI')).not.toBeInTheDocument()
  })

  // ============ 安全设置标签测试 ============

  it('点击安全设置标签切换到密码修改页面', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('安全设置'))

    // "修改密码" 同时出现在 h2 和提交按钮中，使用 heading role 定位
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '修改密码' })).toBeInTheDocument()
    })

    expect(screen.getByPlaceholderText('输入旧密码')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('至少8位，含大小写字母和数字')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('再次输入新密码')).toBeInTheDocument()

    // "退出登录" 同时出现在 h2 和按钮中，使用 heading role 定位 h2
    expect(screen.getByRole('heading', { name: '退出登录' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '退出登录' })).toBeInTheDocument()
  })

  // ============ 设备管理标签测试 ============

  it('点击设备管理标签切换到设备列表', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({
      data: [
        { id: 1, device_type: 'desktop', ip_address: '192.168.1.1', user_agent: null, logged_in_at: '2026-05-15T08:00:00Z', last_active_at: '2026-05-15T12:00:00Z', is_online: true, is_current: true },
      ],
    })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('设备管理'))

    await waitFor(() => {
      expect(screen.getByText('登录设备')).toBeInTheDocument()
    })

    // device_type 'desktop' 映射为 '桌面'
    expect(screen.getByText('桌面')).toBeInTheDocument()
    expect(screen.getByText('当前设备')).toBeInTheDocument()
  })

  it('设备列表为空时显示空状态提示', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('设备管理'))

    await waitFor(() => {
      expect(screen.getByText('暂无设备记录')).toBeInTheDocument()
    })
  })

  it('设备列表中非当前设备显示远程登出按钮', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({
      data: [
        { id: 1, device_type: 'desktop', ip_address: '192.168.1.1', user_agent: null, logged_in_at: '2026-05-15T08:00:00Z', last_active_at: '2026-05-15T12:00:00Z', is_online: true, is_current: true },
        { id: 2, device_type: 'mobile', ip_address: '10.0.0.5', user_agent: null, logged_in_at: '2026-05-14T08:00:00Z', last_active_at: '2026-05-14T12:00:00Z', is_online: false, is_current: false },
      ],
    })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('设备管理'))

    await waitFor(() => {
      expect(screen.getByText('远程登出')).toBeInTheDocument()
    })
  })

  // ============ 退出登录测试 ============

  it('退出登录按钮触发 logout 并导航到登录页', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: createMockDevices() })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('安全设置'))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '修改密码' })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }))

    await waitFor(() => {
      expect(logoutMock).toHaveBeenCalled()
      expect(navigateMock).toHaveBeenCalledWith('/login', { replace: true })
    })
  })

  // ============ 昵称编辑测试 ============

  it('编辑昵称字段后输入值更新', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile({ nickname: '旧昵称' }) })
    getDevicesMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByDisplayValue('旧昵称')).toBeInTheDocument()
    })

    const nicknameInput = screen.getByDisplayValue('旧昵称')
    fireEvent.change(nicknameInput, { target: { value: '新昵称' } })
    expect(nicknameInput).toHaveValue('新昵称')
  })

  // ============ 密码修改测试 ============

  it('密码修改表单提交时旧密码为空显示错误提示', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('安全设置'))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '修改密码' })).toBeInTheDocument()
    })

    // 只填写新密码，旧密码留空
    fireEvent.change(screen.getByPlaceholderText('至少8位，含大小写字母和数字'), { target: { value: 'NewPass123' } })
    fireEvent.change(screen.getByPlaceholderText('再次输入新密码'), { target: { value: 'NewPass123' } })

    // 点击提交按钮（与 h2 同文本，使用 role selector 定位）
    fireEvent.click(screen.getByRole('button', { name: '修改密码' }))

    await waitFor(() => {
      expect(screen.getByText('请填写所有密码字段')).toBeInTheDocument()
    })
  })

  it('两次新密码不一致时显示错误提示', async () => {
    getProfileMock.mockResolvedValueOnce({ data: createMockProfile() })
    getDevicesMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('安全设置'))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '修改密码' })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('输入旧密码'), { target: { value: 'oldpass' } })
    fireEvent.change(screen.getByPlaceholderText('至少8位，含大小写字母和数字'), { target: { value: 'NewPass123' } })
    fireEvent.change(screen.getByPlaceholderText('再次输入新密码'), { target: { value: 'NewPass456' } })

    fireEvent.click(screen.getByRole('button', { name: '修改密码' }))

    await waitFor(() => {
      expect(screen.getByText('两次输入的新密码不一致')).toBeInTheDocument()
    })
  })

  // ============ 边界测试 ============

  it('无 nickname/email/phone 的数据正常渲染占位符', async () => {
    getProfileMock.mockResolvedValueOnce({
      data: createMockProfile({ nickname: null, email: null, phone: null }),
    })
    getDevicesMock.mockResolvedValueOnce({ data: [] })

    render(<BrowserRouter><UserCenterPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('个人画像')).toBeInTheDocument()
    })

    expect(screen.getByPlaceholderText('设置昵称')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('绑定邮箱')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('绑定手机号')).toBeInTheDocument()
  })
})
