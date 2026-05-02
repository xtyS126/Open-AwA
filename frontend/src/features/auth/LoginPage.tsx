import React, { useState } from 'react'
import { authAPI, getApiErrorDetail } from '@/shared/api/api'
import { useAuthStore } from '@/shared/store/authStore'
import { appLogger } from '@/shared/utils/logger'
import styles from './LoginPage.module.css'

/**
 * 登录页面组件。
 * 用户必须通过此页面登录后才能访问系统功能。
 * 用户账号的增删仅允许通过后端本地配置文件 config/users.yaml 修改。
 */
function LoginPage() {
  const { setAuth, setInitialized } = useAuthStore()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) {
      setError('请输入用户名和密码')
      return
    }

    setLoading(true)
    setError(null)

    try {
      const response = await authAPI.login(username.trim(), password)
      setAuth(
        { username: username.trim() },
        response.data.access_token || null
      )
      setInitialized(true)
      appLogger.info({
        event: 'auth_login',
        module: 'auth',
        action: 'login',
        status: 'success',
        message: 'user login succeeded',
      })
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      const detail = getApiErrorDetail(err)
      if (status === 401) {
        setError('用户名或密码错误')
      } else if (status === 403) {
        setError(detail || '账户已被禁用，请联系管理员')
      } else if (status === 429) {
        setError('登录尝试过于频繁，请稍后再试')
      } else {
        setError('登录失败，请稍后重试')
      }
      appLogger.warning({
        event: 'auth_login',
        module: 'auth',
        action: 'login',
        status: 'failure',
        message: 'user login failed',
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
            <label htmlFor="username">用户名</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoComplete="username"
              autoFocus
            />
          </div>
          <div className={styles['form-group']}>
            <label htmlFor="password">密码</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
              autoComplete="current-password"
            />
          </div>
          {error && <div className={styles['login-error']}>{error}</div>}
          <button
            type="submit"
            className={styles['login-btn']}
            disabled={loading}
          >
            {loading ? '登录中...' : '登录'}
          </button>
          <p className={styles['login-hint']}>
            账号由管理员通过配置文件管理
          </p>
        </form>
      </div>
    </div>
  )
}

export default LoginPage
