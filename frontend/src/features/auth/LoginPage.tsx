import React, { useState } from 'react'
import { shallow } from 'zustand/shallow'
import { authAPI, setTempApiKey, persistApiKey, clearCachedApiKey } from '@/shared/api/api'
import { useAuthStore } from '@/shared/store/authStore'
import { useNavigate } from '@/shared/routing'
import { isNativeApp } from '@/shared/utils/platform'
import { apiKeySchema } from '@/shared/schemas/auth'
import { appLogger } from '@/shared/utils/logger'
import styles from './LoginPage.module.css'

/**
 * API Key 配置页面。
 * 首次使用时输入 API Key 进行认证，后续自动从浏览器缓存读取。
 * 单用户模式下不再需要用户名密码登录。
 * 表单校验使用 zod schema（apiKeySchema），与后端 OPENAWA_API_KEY 最小长度约束对齐。
 */
function LoginPage() {
  // 使用选择器 + shallow 浅比较，避免整个 store 变化触发重渲染
  const { setAuth, setInitialized, setNeedsServerSelection } = useAuthStore(s => ({
    setAuth: s.setAuth,
    setInitialized: s.setInitialized,
    setNeedsServerSelection: s.setNeedsServerSelection,
  }), shallow)
  const navigate = useNavigate()
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  /** APP 模式：重新选择局域网后端 */
  const handleSwitchServer = () => {
    setNeedsServerSelection(true)
    void navigate('/server-select')
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    // 使用 zod schema 进行前端校验，提供即时反馈
    const parseResult = apiKeySchema.safeParse({ apiKey: apiKey.trim() })
    if (!parseResult.success) {
      // 取第一条错误信息展示给用户
      const firstIssue = parseResult.error.issues[0]
      setError(firstIssue?.message ?? '输入无效')
      return
    }
    const validApiKey = parseResult.data.apiKey

    setLoading(true)
    setError(null)

    try {
      // 临时写入内存以便 getMe() 请求携带访问密钥
      setTempApiKey(validApiKey)
      const response = await authAPI.getMe()
      const data = response.data || {}
      // 验证成功后才持久化到 sessionStorage
      await persistApiKey(validApiKey)
      setAuth(
        {
          username: data.username || 'admin',
          nickname: data.nickname,
          avatar_url: data.avatar_url,
          email: data.email,
          phone: data.phone,
          role: data.role,
        },
        validApiKey
      )
      setInitialized(true)
      appLogger.info({
        event: 'auth_verified',
        module: 'auth',
        action: 'login',
        status: 'success',
        message: 'authentication verified',
      })
    } catch (err) {
      clearCachedApiKey()
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 401) {
        setError('认证失败')
      } else if (status === 429) {
        setError('请求过于频繁，请稍后再试')
      } else {
        setError('认证失败，请重试')
      }
      appLogger.warning({
        event: 'auth_verify_failed',
        module: 'auth',
        action: 'login',
        status: 'failure',
        message: 'authentication verification failed',
        extra: { status_code: status },
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles['login-page']}>
      <div className={styles['login-card']}>
        <div className={styles['login-header']}>
          <h1>Open-AwA</h1>
          <p>AI Agent 实验平台</p>
        </div>
        <form className={styles['login-form']} onSubmit={handleSubmit}>
          <div className={styles['form-group']}>
            <label htmlFor="apiKey">访问密钥</label>
            <input
              id="apiKey"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="请输入访问密钥"
              autoComplete="off"
              autoFocus
              aria-describedby={error ? 'login-error' : undefined}
              aria-invalid={!!error}
            />
          </div>
          {error && <div id="login-error" className={styles['login-error']} role="alert">{error}</div>}
          <button
            type="submit"
            className={styles['login-btn']}
            disabled={loading}
          >
            {loading ? '验证中...' : '连接'}
          </button>
        </form>
        {isNativeApp() && (
          <button
            type="button"
            className={styles['switch-server-btn']}
            onClick={handleSwitchServer}
          >
            切换服务器
          </button>
        )}
      </div>
    </div>
  )
}

export default LoginPage
