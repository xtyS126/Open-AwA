import React, { useState } from 'react'
import { authAPI, getApiErrorDetail, setCachedApiKey } from '@/shared/api/api'
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
      setError('请输入 API Key')
      return
    }
    if (apiKey.trim().length < 20) {
      setError('API Key 长度不足，请检查是否完整复制')
      return
    }

    setLoading(true)
    setError(null)

    try {
      // 先缓存 Key 再验证
      setCachedApiKey(apiKey.trim())
      const response = await authAPI.getMe()
      const data = response.data || {}
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
        event: 'auth_api_key_validated',
        module: 'auth',
        action: 'login',
        status: 'success',
        message: 'API Key validated successfully',
      })
    } catch (err) {
      setCachedApiKey('')  // 清除无效 Key
      const status = (err as { response?: { status?: number } })?.response?.status
      const detail = getApiErrorDetail(err)
      if (status === 401) {
        setError('API Key 无效，请检查后重试')
      } else if (status === 429) {
        setError('请求过于频繁，请稍后再试')
      } else {
        setError(detail || '验证失败，请检查后端地址和 API Key 是否正确')
      }
      appLogger.warning({
        event: 'auth_api_key_validate_failed',
        module: 'auth',
        action: 'login',
        status: 'failure',
        message: 'API Key validation failed',
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
            <label htmlFor="apiKey">API Key</label>
            <input
              id="apiKey"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="请输入 API Key (sk-...)"
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
          <p className={styles['login-hint']}>
            API Key 由后端启动时生成，请查看服务端日志或 .env.local 文件
          </p>
        </form>
      </div>
    </div>
  )
}

export default LoginPage
