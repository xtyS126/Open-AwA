import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  User, Shield, Monitor, Camera, Loader2, AlertCircle,
} from 'lucide-react'
import { useAuthStore } from '@/shared/store/authStore'
import { userAPI, passwordAPI } from '@/shared/api/api'
import type { UserProfile, LoginDeviceItem } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import styles from './UserCenterPage.module.css'

type TabKey = 'profile' | 'security' | 'devices'

function UserCenterPage() {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  const [activeTab, setActiveTab] = useState<TabKey>('profile')
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // 密码
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordMsg, setPasswordMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [passwordSubmitting, setPasswordSubmitting] = useState(false)

  // 个人信息
  const [nickname, setNickname] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [profileMsg, setProfileMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // 头像
  const [avatarUploading, setAvatarUploading] = useState(false)
  const [avatarMsg, setAvatarMsg] = useState<string | null>(null)
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null)

  // 设备
  const [devices, setDevices] = useState<LoginDeviceItem[]>([])
  const [devicesLoading, setDevicesLoading] = useState(false)

  const loadProfile = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await userAPI.getProfile()
      setProfile(res.data)
      setNickname(res.data.nickname || '')
      setEmail(res.data.email || '')
      setPhone(res.data.phone || '')
      if (res.data.avatar_url) {
        setAvatarPreview(res.data.avatar_url)
      }
    } catch (e) {
      setError('加载用户信息失败')
      appLogger.error({
        event: 'user_center_load_failed',
        module: 'user',
        message: 'failed to load user profile',
        extra: { error: e instanceof Error ? e.message : String(e) },
      })
    } finally {
      setLoading(false)
    }
  }, [])

  const loadDevices = useCallback(async () => {
    setDevicesLoading(true)
    try {
      const res = await userAPI.getDevices()
      setDevices(res.data)
    } catch {
      // 静默处理
    } finally {
      setDevicesLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadProfile()
    void loadDevices()
  }, [loadProfile, loadDevices])

  // 密码修改
  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordMsg(null)
    if (!oldPassword || !newPassword || !confirmPassword) {
      setPasswordMsg({ type: 'error', text: '请填写所有密码字段' })
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordMsg({ type: 'error', text: '两次输入的新密码不一致' })
      return
    }
    setPasswordSubmitting(true)
    try {
      await passwordAPI.change(oldPassword, newPassword, confirmPassword)
      setPasswordMsg({ type: 'success', text: '密码修改成功' })
      setOldPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setPasswordMsg({ type: 'error', text: detail || '密码修改失败' })
    } finally {
      setPasswordSubmitting(false)
    }
  }

  // 个人信息保存
  const handleProfileSave = async () => {
    setProfileMsg(null)
    try {
      await userAPI.updateProfile({ nickname, email, phone })
      setProfileMsg({ type: 'success', text: '个人信息已更新' })
    } catch {
      setProfileMsg({ type: 'error', text: '保存失败' })
    }
  }

  // 头像上传
  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 1024 * 1024) {
      setAvatarMsg('图片大小不能超过 1MB')
      return
    }
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      setAvatarMsg('仅支持 JPG 和 PNG 格式')
      return
    }
    setAvatarUploading(true)
    setAvatarMsg(null)
    try {
      const res = await userAPI.uploadAvatar(file)
      setAvatarPreview(res.data.avatar_url)
      setAvatarMsg('头像上传成功')
    } catch {
      setAvatarMsg('头像上传失败')
    } finally {
      setAvatarUploading(false)
    }
  }

  // 远程登出
  const handleRevokeDevice = async (deviceId: number) => {
    if (!confirm('确定要远程登出该设备吗？')) return
    try {
      await userAPI.revokeDevice(deviceId)
      void loadDevices()
    } catch {
      // 静默处理
    }
  }

  // 退出登录
  const handleLogout = async () => {
    try {
      await import('@/shared/api/api').then(m => m.authAPI.logout())
    } catch { /* ignore */ }
    logout()
    navigate('/login', { replace: true })
  }

  // 密码强度
  const passwordStrength = getPasswordStrength(newPassword)

  if (loading) {
    return (
      <div className={styles['loading']}>
        <Loader2 size={24} className={styles['spin']} />
        <span>加载用户信息...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className={styles['error-page']}>
        <AlertCircle size={48} />
        <p>{error}</p>
        <button className="btn btn-primary" onClick={() => void loadProfile()}>重试</button>
      </div>
    )
  }

  const tabs: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: 'profile', label: 'AI 画像', icon: <User size={16} /> },
    { key: 'security', label: '安全设置', icon: <Shield size={16} /> },
    { key: 'devices', label: '设备管理', icon: <Monitor size={16} /> },
  ]

  return (
    <div className={styles['user-page']}>
      <div className={styles['page-header']}>
        <h1>用户中心</h1>
      </div>

      <div className={styles['user-layout']}>
        {/* 左侧导航 */}
        <nav className={styles['tabs-nav']}>
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={`${styles['tab-btn']} ${activeTab === tab.key ? styles['tab-active'] : ''}`}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>

        {/* 右侧内容 */}
        <div className={styles['tab-content']}>
          {/* AI 画像 */}
          {activeTab === 'profile' && (
            <section className={styles['section']}>
              <h2>个人画像</h2>
              <div className={styles['profile-section']}>
                {/* 头像上传 */}
                <div className={styles['avatar-section']}>
                  <div className={styles['avatar-preview']}>
                    {avatarPreview ? (
                      <img src={avatarPreview} alt="头像" className={styles['avatar-img']} />
                    ) : (
                      <span className={styles['avatar-placeholder']}>
                        {(user?.username || 'U')[0].toUpperCase()}
                      </span>
                    )}
                  </div>
                  <label className={styles['upload-label']}>
                    <Camera size={14} />
                    <span>{avatarUploading ? '上传中...' : '更换头像'}</span>
                    <input
                      type="file"
                      accept="image/jpeg,image/png"
                      onChange={(e) => void handleAvatarUpload(e)}
                      disabled={avatarUploading}
                      hidden
                    />
                  </label>
                  {avatarMsg && <p className={styles['avatar-msg']}>{avatarMsg}</p>}
                </div>

                {/* 基本信息 */}
                <div className={styles['info-form']}>
                  <label className={styles['form-field']}>
                    <span>用户名</span>
                    <input value={user?.username || ''} disabled />
                  </label>
                  <label className={styles['form-field']}>
                    <span>昵称</span>
                    <input value={nickname} onChange={(e) => setNickname(e.target.value)} placeholder="设置昵称" />
                  </label>
                  <label className={styles['form-field']}>
                    <span>邮箱</span>
                    <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="绑定邮箱" type="email" />
                  </label>
                  <label className={styles['form-field']}>
                    <span>手机</span>
                    <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="绑定手机号" />
                  </label>
                  <div className={styles['form-actions']}>
                    <button className="btn btn-primary" onClick={() => void handleProfileSave()}>保存</button>
                  </div>
                  {profileMsg && (
                    <p className={profileMsg.type === 'success' ? styles['msg-success'] : styles['msg-error']}>
                      {profileMsg.text}
                    </p>
                  )}
                </div>
              </div>

              {/* AI 画像 */}
              {profile?.profile && (
                <div className={styles['ai-profile']}>
                  <h3>AI 画像分析</h3>
                  <div className={styles['interest-tags']}>
                    {(profile.profile.interests as string[] | undefined)?.map((tag: string) => (
                      <span key={tag} className={styles['tag']}>{tag}</span>
                    )) || <span className={styles['tag']}>暂无标签</span>}
                  </div>
                  <div className={styles['stats-row']}>
                    <div className={styles['stat-item']}>
                      <span className={styles['stat-num']}>{String(profile.profile.total_actions || 0)}</span>
                      <span className={styles['stat-label']}>近30天操作数</span>
                    </div>
                  </div>
                  {(profile.profile.active_hours as string[]) && (
                    <div className={styles['active-hours']}>
                      <span className={styles['section-title']}>活跃时段</span>
                      <div className={styles['hours-list']}>
                        {(profile.profile.active_hours as string[]).map((h: string) => (
                          <span key={h} className={styles['hour-tag']}>{h}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </section>
          )}

          {/* 安全设置 */}
          {activeTab === 'security' && (
            <section className={styles['section']}>
              <h2>修改密码</h2>
              <form className={styles['password-form']} onSubmit={(e) => void handlePasswordChange(e)}>
                <label className={styles['form-field']}>
                  <span>旧密码</span>
                  <input
                    type="password"
                    value={oldPassword}
                    onChange={(e) => setOldPassword(e.target.value)}
                    placeholder="输入旧密码"
                  />
                </label>
                <label className={styles['form-field']}>
                  <span>新密码</span>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="至少8位，含大小写字母和数字"
                  />
                  {newPassword && (
                    <div className={styles['strength-bar']}>
                      <div className={`${styles['strength-fill']} ${styles[`strength-${passwordStrength}`]}`} />
                      <span className={styles['strength-text']}>
                        {passwordStrength === 'weak' ? '弱' : passwordStrength === 'medium' ? '中' : '强'}
                      </span>
                    </div>
                  )}
                </label>
                <label className={styles['form-field']}>
                  <span>确认新密码</span>
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="再次输入新密码"
                  />
                </label>
                <div className={styles['form-actions']}>
                  <button className="btn btn-primary" type="submit" disabled={passwordSubmitting}>
                    {passwordSubmitting ? '提交中...' : '修改密码'}
                  </button>
                </div>
                {passwordMsg && (
                  <p className={passwordMsg.type === 'success' ? styles['msg-success'] : styles['msg-error']}>
                    {passwordMsg.text}
                  </p>
                )}
              </form>

              <div className={styles['logout-section']}>
                <h2>退出登录</h2>
                <p className={styles['section-desc']}>退出当前会话后需要重新登录。</p>
                <button className="btn btn-secondary" onClick={() => void handleLogout()}>
                  退出登录
                </button>
              </div>
            </section>
          )}

          {/* 设备管理 */}
          {activeTab === 'devices' && (
            <section className={styles['section']}>
              <h2>登录设备</h2>
              {devicesLoading ? (
                <p>加载中...</p>
              ) : devices.length === 0 ? (
                <p className={styles['empty']}>暂无设备记录</p>
              ) : (
                <div className={styles['device-list']}>
                  {devices.map((device) => (
                    <div key={device.id} className={styles['device-item']}>
                      <div className={styles['device-icon']}>
                        <Monitor size={20} />
                      </div>
                      <div className={styles['device-info']}>
                        <div className={styles['device-header']}>
                          <span className={styles['device-type']}>
                            {device.device_type === 'mobile' ? '手机' : device.device_type === 'tablet' ? '平板' : '桌面'}
                          </span>
                          {device.is_current && (
                            <span className={styles['device-current']}>当前设备</span>
                          )}
                          {device.is_online && !device.is_current && (
                            <span className={styles['device-online']}>在线</span>
                          )}
                        </div>
                        <span className={styles['device-ip']}>IP: {device.ip_address || '未知'}</span>
                        <span className={styles['device-time']}>
                          登录: {new Date(device.logged_in_at).toLocaleString('zh-CN')}
                        </span>
                      </div>
                      {!device.is_current && (
                        <button
                          className={styles['revoke-btn']}
                          onClick={() => void handleRevokeDevice(device.id)}
                        >
                          远程登出
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  )
}

// 密码强度评估
function getPasswordStrength(password: string): 'weak' | 'medium' | 'strong' {
  if (!password || password.length < 8) return 'weak'
  let score = 0
  if (password.length >= 10) score += 1
  if (/[a-z]/.test(password)) score += 1
  if (/[A-Z]/.test(password)) score += 1
  if (/\d/.test(password)) score += 1
  if (/[^a-zA-Z0-9]/.test(password)) score += 1
  if (score <= 2) return 'weak'
  if (score <= 3) return 'medium'
  return 'strong'
}

export default UserCenterPage
