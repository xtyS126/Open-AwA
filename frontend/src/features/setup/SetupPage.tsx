import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { systemAPI } from '@/shared/api/api'
import type { SystemInitRequest } from '@/shared/api/api'
import { useAuthStore } from '@/shared/store/authStore'
import { appLogger } from '@/shared/utils/logger'
import styles from './SetupPage.module.css'

/**
 * 系统首次部署初始化引导页
 *
 * 首次启动容器后用户访问站点时，RootGuard 检测到系统未初始化（无 owner 用户），
 * 自动跳转到本页面。用户填写用户名/密码后调用 POST /api/system/init 完成初始化，
 * 然后跳转到登录页用刚设置的凭据登录。
 *
 * 与后端契约：
 *   - GET /api/system/init-status 检测初始化状态（由 useAppInitialization 调用）
 *   - POST /api/system/init 执行初始化
 *   - 密码强度：至少 8 字符，包含大小写字母和数字（与后端 InitRequest 一致）
 */
function SetupPage() {
  const navigate = useNavigate()
  const setSystemInitialized = useAuthStore((s) => s.setSystemInitialized)
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [email, setEmail] = useState('')
  const [nickname, setNickname] = useState('Administrator')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // 密码强度评估：返回 0-4 的等级
  const evaluatePasswordStrength = (pwd: string): number => {
    let score = 0
    if (pwd.length >= 8) score++
    if (pwd.length >= 12) score++
    if (/[a-z]/.test(pwd) && /[A-Z]/.test(pwd)) score++
    if (/\d/.test(pwd)) score++
    return Math.min(score, 4)
  }

  const strength = evaluatePasswordStrength(password)
  const strengthLabel =
    strength === 0
      ? ''
      : strength <= 1
        ? '弱'
        : strength === 2
          ? '中'
          : strength >= 3
            ? '强'
            : ''

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)

    // 前端基础校验
    if (!username.trim()) {
      setError('请输入用户名')
      return
    }
    if (!/^[a-zA-Z0-9_-]+$/.test(username)) {
      setError('用户名只能包含字母、数字、下划线和连字符')
      return
    }
    if (password.length < 8) {
      setError('密码至少需要 8 个字符')
      return
    }
    if (!/[A-Z]/.test(password)) {
      setError('密码必须包含至少一个大写字母')
      return
    }
    if (!/[a-z]/.test(password)) {
      setError('密码必须包含至少一个小写字母')
      return
    }
    if (!/\d/.test(password)) {
      setError('密码必须包含至少一个数字')
      return
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }

    setLoading(true)

    try {
      const payload: SystemInitRequest = {
        username: username.trim(),
        password,
        nickname: nickname.trim() || 'Administrator',
      }
      if (email.trim()) {
        payload.email = email.trim()
      }

      const response = await systemAPI.init(payload)
      const data = response.data?.data
      if (!response.data?.success || !data) {
        throw new Error('初始化返回数据格式异常')
      }

      appLogger.info({
        event: 'system_init',
        module: 'setup',
        action: 'init',
        status: 'success',
        message: `system initialized, owner=${data.username}`,
      })

      setSuccess(`初始化成功！用户名：${data.username}。即将跳转到登录页...`)
      setSystemInitialized(true)

      // 1.5 秒后跳转到登录页
      setTimeout(() => {
        navigate('/login', { replace: true })
      }, 1500)
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      const respData = (err as { response?: { data?: unknown } })?.response?.data
      let msg = '初始化失败，请重试'
      if (status === 409) {
        msg = '系统已初始化或已有用户存在，请直接登录'
      } else if (status === 422) {
        msg = '输入校验失败：' + (typeof respData === 'string' ? respData : JSON.stringify(respData))
      } else if (status === 500) {
        msg = '服务器内部错误，请查看后端日志'
      } else if (err instanceof Error && err.message) {
        msg = err.message
      }
      setError(msg)
      appLogger.warning({
        event: 'system_init',
        module: 'setup',
        action: 'init',
        status: 'failure',
        message: 'system init failed',
        extra: { status_code: status, error: err instanceof Error ? err.message : String(err) },
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles['setup-page']}>
      <div className={styles['setup-card']}>
        <div className={styles['setup-header']}>
          <h1>Open-AwA 首次部署</h1>
          <p>检测到系统尚未初始化，请创建管理员账户以完成部署</p>
        </div>

        <form className={styles['setup-form']} onSubmit={handleSubmit}>
          <div className={styles['form-group']}>
            <label htmlFor="username">用户名</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="字母、数字、下划线、连字符"
              autoComplete="username"
              autoFocus
              required
            />
            <span className={styles['form-hint']}>将作为 owner 管理员账户登录</span>
          </div>

          <div className={styles['form-group']}>
            <label htmlFor="password">密码</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="至少 8 字符，含大小写字母和数字"
              autoComplete="new-password"
              required
            />
            {password && (
              <>
                <div className={styles['password-strength']}>
                  {[1, 2, 3, 4].map((i) => (
                    <div
                      key={i}
                      className={`${styles['strength-bar']} ${
                        strength >= i
                          ? strength <= 1
                            ? styles['weak']
                            : strength === 2
                              ? styles['medium']
                              : styles['strong']
                          : ''
                      }`}
                    />
                  ))}
                </div>
                <span className={styles['strength-label']}>强度：{strengthLabel}</span>
              </>
            )}
          </div>

          <div className={styles['form-group']}>
            <label htmlFor="confirmPassword">确认密码</label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="再次输入密码"
              autoComplete="new-password"
              required
            />
          </div>

          <div className={styles['form-group']}>
            <label htmlFor="nickname">昵称（可选）</label>
            <input
              id="nickname"
              type="text"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              placeholder="显示名称"
            />
          </div>

          <div className={styles['form-group']}>
            <label htmlFor="email">邮箱（可选）</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="admin@example.com"
            />
          </div>

          {error && (
            <div className={styles['setup-error']} role="alert">
              {error}
            </div>
          )}
          {success && (
            <div className={styles['setup-success']} role="status">
              {success}
            </div>
          )}

          <button type="submit" className={styles['setup-btn']} disabled={loading}>
            {loading ? '初始化中...' : '完成部署初始化'}
          </button>
        </form>

        <div className={styles['setup-footer']}>
          完成后将跳转到登录页，使用刚设置的凭据登录
        </div>
      </div>
    </div>
  )
}

export default SetupPage
