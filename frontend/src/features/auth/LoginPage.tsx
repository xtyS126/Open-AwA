import React, { useState } from 'react'
import { authAPI, getApiErrorDetail, setTempApiKey, persistApiKey, clearCachedApiKey } from '@/shared/api/api'
import { useAuthStore } from '@/shared/store/authStore'
import { appLogger } from '@/shared/utils/logger'
import styles from './LoginPage.module.css'

/**
 * API Key 配置页面。
 * 首次使用时输入 API Key 进行认证，后续自动从浏览器缓存读取。
 * 单用户模式下不再需要用户名密码登录。
 */
function LoginPage() {
  const { setAuth, setInitialized } = useAuthStore()
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!apiKey.trim()) {
      setError('请输入访问密钥')
      return
    }
    if (apiKey.trim().length < 20) {
      setError('认证失败')
      return
    }

    setLoading(true)
    setError(null)

    try {
      // 临时写入内存以便 getMe() 请求携带访问密钥
      setTempApiKey(apiKey.trim())
      const response = await authAPI.getMe()
      const data = response.data || {}
      // 验证成功后才持久化到 sessionStorage
      persistApiKey(apiKey.trim())
      setAuth(
        {
          username: data.username || 'admin',
          nickname: data.nickname,
          avatar_url: data.avatar_url,
          email: data.email,
          phone: data.phone,
          role: data.role,
        },
        apiKey.trim()
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
      </div>
    </div>
  )
}

export default LoginPage
