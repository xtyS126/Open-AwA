/**
 * AuthPage 测试套件 — API 密钥登录页面（当前 UI：访问密钥 + 连接/验证中...）
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import LoginPage from '@/features/auth/LoginPage'
import { BrowserRouter } from 'react-router-dom'

const { getMeMock, persistApiKeyMock, setAuthMock, setInitializedMock } = vi.hoisted(() => ({
  getMeMock: vi.fn(),
  persistApiKeyMock: vi.fn(),
  setAuthMock: vi.fn(),
  setInitializedMock: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  authAPI: {
    login: vi.fn(),
    register: vi.fn(),
    getMe: getMeMock,
    logout: vi.fn(),
  },
  getApiErrorDetail: vi.fn(),
  setTempApiKey: vi.fn(),
  persistApiKey: persistApiKeyMock,
  clearCachedApiKey: vi.fn(),
}))

vi.mock('@/shared/store/authStore', () => ({
  useAuthStore: () => ({
    setAuth: setAuthMock,
    setInitialized: setInitializedMock,
  }),
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

const renderLogin = () => render(<BrowserRouter><LoginPage /></BrowserRouter>)

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    persistApiKeyMock.mockResolvedValue(undefined)
  })

  // ============ 渲染 ============
  it('渲染登录表单的基本元素', () => {
    renderLogin()
    expect(screen.getByText('Open-AwA')).toBeInTheDocument()
    expect(screen.getByText('AI Agent 实验平台')).toBeInTheDocument()
    expect(screen.getByLabelText('访问密钥')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '连接' })).toBeInTheDocument()
  })

  it('访问密钥输入框自动聚焦', () => {
    renderLogin()
    expect(screen.getByLabelText('访问密钥')).toHaveFocus()
  })

  // ============ 空字段校验 ============
  it('密钥为空时显示错误提示', async () => {
    renderLogin()
    fireEvent.click(screen.getByRole('button', { name: '连接' }))
    await waitFor(() => {
      expect(screen.getByText('请输入访问密钥或密码')).toBeInTheDocument()
    })
  })

  // 短输入不再被前端 schema 拒绝：API Key 与密码共用同一输入框，
  // 密码可能短至 8 位，长度校验交给后端认证顺序裁决（API Key → JWT → 密码）

  // ============ 成功登录 ============
  it('验证成功后调用 setAuth 和 setInitialized', async () => {
    getMeMock.mockResolvedValueOnce({ data: { username: 'admin' } })
    renderLogin()
    fireEvent.change(screen.getByLabelText('访问密钥'), {
      target: { value: 'sk-1234567890abcdef1234567890abcdef' },
    })
    fireEvent.click(screen.getByRole('button', { name: '连接' }))

    await waitFor(() => { expect(getMeMock).toHaveBeenCalled() })
    await waitFor(() => {
      expect(setAuthMock).toHaveBeenCalled()
      expect(setInitializedMock).toHaveBeenCalled()
    })
  })

  it('等待 CSRF 初始化完成后再发布已认证状态', async () => {
    let resolveCsrf: (() => void) | undefined
    persistApiKeyMock.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveCsrf = resolve
    }))
    getMeMock.mockResolvedValueOnce({ data: { username: 'admin' } })
    renderLogin()
    fireEvent.change(screen.getByLabelText('访问密钥'), {
      target: { value: 'sk-1234567890abcdef1234567890abcdef' },
    })
    fireEvent.click(screen.getByRole('button', { name: '连接' }))

    await waitFor(() => expect(persistApiKeyMock).toHaveBeenCalledTimes(1))
    expect(setAuthMock).not.toHaveBeenCalled()

    resolveCsrf?.()
    await waitFor(() => expect(setAuthMock).toHaveBeenCalledTimes(1))
  })

  it('加载中按钮显示"验证中..."并禁用', async () => {
    getMeMock.mockImplementationOnce(() => new Promise(() => {}))
    renderLogin()
    fireEvent.change(screen.getByLabelText('访问密钥'), {
      target: { value: 'sk-1234567890abcdef1234567890abcdef' },
    })
    fireEvent.click(screen.getByRole('button', { name: '连接' }))

    await waitFor(() => {
      const btn = screen.getByRole('button', { name: '验证中...' })
      expect(btn).toBeDisabled()
    })
  })

  // ============ 401 ============
  it('401 错误显示认证失败', async () => {
    getMeMock.mockRejectedValueOnce({ response: { status: 401 } })
    renderLogin()
    fireEvent.change(screen.getByLabelText('访问密钥'), {
      target: { value: 'sk-1234567890abcdef1234567890abcdef' },
    })
    fireEvent.click(screen.getByRole('button', { name: '连接' }))
    await waitFor(() => {
      expect(screen.getByText('认证失败')).toBeInTheDocument()
    })
  })

  // ============ 429 ============
  it('429 错误显示请求频繁提示', async () => {
    getMeMock.mockRejectedValueOnce({ response: { status: 429 } })
    renderLogin()
    fireEvent.change(screen.getByLabelText('访问密钥'), {
      target: { value: 'sk-1234567890abcdef1234567890abcdef' },
    })
    fireEvent.click(screen.getByRole('button', { name: '连接' }))
    await waitFor(() => {
      expect(screen.getByText('请求过于频繁，请稍后再试')).toBeInTheDocument()
    })
  })

  // ============ 其他错误 ============
  it('500 错误显示认证失败请重试', async () => {
    getMeMock.mockRejectedValueOnce({ response: { status: 500 } })
    renderLogin()
    fireEvent.change(screen.getByLabelText('访问密钥'), {
      target: { value: 'sk-1234567890abcdef1234567890abcdef' },
    })
    fireEvent.click(screen.getByRole('button', { name: '连接' }))
    await waitFor(() => {
      expect(screen.getByText('认证失败，请重试')).toBeInTheDocument()
    })
  })

  it('网络错误显示认证失败请重试', async () => {
    getMeMock.mockRejectedValueOnce(new Error('Network Error'))
    renderLogin()
    fireEvent.change(screen.getByLabelText('访问密钥'), {
      target: { value: 'sk-1234567890abcdef1234567890abcdef' },
    })
    fireEvent.click(screen.getByRole('button', { name: '连接' }))
    await waitFor(() => {
      expect(screen.getByText('认证失败，请重试')).toBeInTheDocument()
    })
  })

  // ============ 输入行为 ============
  it('输入框实时更新值', () => {
    renderLogin()
    const input = screen.getByLabelText('访问密钥') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'new-key' } })
    expect(input.value).toBe('new-key')
  })

  it('Enter 键提交表单', async () => {
    getMeMock.mockResolvedValueOnce({ data: { username: 'admin' } })
    renderLogin()
    const input = screen.getByLabelText('访问密钥')
    fireEvent.change(input, { target: { value: 'sk-1234567890abcdef1234567890abcdef' } })
    fireEvent.submit(input.closest('form')!)
    await waitFor(() => { expect(getMeMock).toHaveBeenCalled() })
  })
})
