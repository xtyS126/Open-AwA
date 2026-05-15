/**
 * AuthPage 测试套件 — 认证页面（LoginPage）的渲染和交互测试
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import LoginPage from '@/features/auth/LoginPage'
import { BrowserRouter } from 'react-router-dom'

/** 使用 vi.hoisted 在模块层注册可引用的 mock 函数 */
const { loginMock, setAuthMock, setInitializedMock, getMeMock } = vi.hoisted(() => ({
  loginMock: vi.fn(),
  setAuthMock: vi.fn(),
  setInitializedMock: vi.fn(),
  getMeMock: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  authAPI: {
    login: loginMock,
    register: vi.fn(),
    getMe: getMeMock,
    logout: vi.fn(),
  },
  getApiErrorDetail: vi.fn((err: unknown) => {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    return typeof detail === 'string' && detail.trim() ? detail : ''
  }),
}))

vi.mock('@/shared/store/authStore', () => ({
  useAuthStore: () => ({
    setAuth: setAuthMock,
    setInitialized: setInitializedMock,
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

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    loginMock.mockReset()
    setAuthMock.mockReset()
    setInitializedMock.mockReset()
    getMeMock.mockReset()
  })

  // ============ 渲染测试 ============

  it('渲染登录表单的基本元素', () => {
    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    expect(screen.getByText('Open-AwA')).toBeInTheDocument()
    expect(screen.getByText('AI Agent 实验平台')).toBeInTheDocument()
    expect(screen.getByLabelText('用户名')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument()
    expect(screen.getByText('账号由管理员通过配置文件管理')).toBeInTheDocument()
  })

  it('用户名输入框应该自动聚焦', () => {
    render(<BrowserRouter><LoginPage /></BrowserRouter>)
    const usernameInput = screen.getByLabelText('用户名')
    expect(usernameInput).toHaveFocus()
  })

  // ============ 空字段校验 ============

  it('用户名为空时点击登录显示错误提示', async () => {
    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByText('请输入用户名和密码')).toBeInTheDocument()
    })
  })

  it('仅输入用户名未输入密码时显示错误提示', async () => {
    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'testuser' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByText('请输入用户名和密码')).toBeInTheDocument()
    })
  })

  it('仅输入密码未输入用户名时显示错误提示', async () => {
    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'testpass' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByText('请输入用户名和密码')).toBeInTheDocument()
    })
  })

  // ============ 正常登录流程 ============

  it('登录成功后调用 setAuth 并传入用户名和 token', async () => {
    loginMock.mockResolvedValueOnce({
      data: { access_token: 'test-jwt-token' },
    })

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'testuser' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'correct-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(loginMock).toHaveBeenCalledWith('testuser', 'correct-password')
    })

    await waitFor(() => {
      expect(setAuthMock).toHaveBeenCalledWith(
        { username: 'testuser' },
        'test-jwt-token'
      )
    })
  })

  it('登录过程中按钮显示"登录中..."并处于禁用状态', async () => {
    loginMock.mockImplementationOnce(
      () => new Promise(() => { /* 永不 resolve */ })
    )

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'testuser' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'correct-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      const btn = screen.getByRole('button', { name: '登录中...' })
      expect(btn).toBeDisabled()
    })
  })

  // ============ 登录失败 — 401 错误 ============

  it('401 错误时显示"用户名或密码错误"', async () => {
    loginMock.mockRejectedValueOnce({ response: { status: 401 } })

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'testuser' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'wrong-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByText('用户名或密码错误')).toBeInTheDocument()
    })

    // 按钮恢复可用状态
    expect(screen.getByRole('button', { name: '登录' })).not.toBeDisabled()
  })

  it('403 错误时显示账户禁用提示', async () => {
    loginMock.mockRejectedValueOnce({ response: { status: 403 } })

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'disabled-user' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByText('账户已被禁用，请联系管理员')).toBeInTheDocument()
    })
  })

  it('403 错误有自定义 detail 时优先显示 detail', async () => {
    loginMock.mockRejectedValueOnce({
      response: {
        status: 403,
        data: { detail: '账户已过期，请联系管理员续期' },
      },
    })

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'expired-user' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByText('账户已过期，请联系管理员续期')).toBeInTheDocument()
    })
  })

  it('429 错误时显示频繁尝试提示', async () => {
    loginMock.mockRejectedValueOnce({ response: { status: 429 } })

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'testuser' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByText('登录尝试过于频繁，请稍后再试')).toBeInTheDocument()
    })
  })

  it('其他错误（如 500）时显示默认错误提示', async () => {
    loginMock.mockRejectedValueOnce({ response: { status: 500 } })

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'testuser' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByText('登录失败，请稍后重试')).toBeInTheDocument()
    })
  })

  it('网络错误时显示默认错误提示', async () => {
    loginMock.mockRejectedValueOnce(new Error('Network Error'))

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'testuser' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByText('登录失败，请稍后重试')).toBeInTheDocument()
    })
  })

  // ============ 输入交互测试 ============

  it('用户名输入框实时更新值', () => {
    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    const input = screen.getByLabelText('用户名')
    fireEvent.change(input, { target: { value: 'myuser' } })
    expect(input).toHaveValue('myuser')
  })

  it('密码输入框实时更新值', () => {
    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    const input = screen.getByLabelText('密码')
    fireEvent.change(input, { target: { value: 'mypassword' } })
    expect(input).toHaveValue('mypassword')
  })

  // ============ Token 存储测试 ============

  it('登录成功后 token 为 null 时仍然正常设置认证', async () => {
    loginMock.mockResolvedValueOnce({
      data: { access_token: null },
    })

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'testuser' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'correct-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(setAuthMock).toHaveBeenCalledWith(
        { username: 'testuser' },
        null
      )
    })
  })

  // ============ 边界测试 ============

  it('用户名前后空格在提交时被去除', async () => {
    loginMock.mockResolvedValueOnce({
      data: { access_token: 'token-string' },
    })

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: '  testuser  ' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(loginMock).toHaveBeenCalledWith('testuser', 'password')
    })
  })

  it('表单通过 Enter 键提交', async () => {
    loginMock.mockResolvedValueOnce({
      data: { access_token: 'token' },
    })

    render(<BrowserRouter><LoginPage /></BrowserRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'testuser' },
    })
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'password' },
    })

    const form = screen.getByLabelText('密码').closest('form')!
    fireEvent.submit(form)

    await waitFor(() => {
      expect(loginMock).toHaveBeenCalled()
    })
  })
})
