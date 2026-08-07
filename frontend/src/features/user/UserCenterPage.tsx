/**
 * 用户中心统一页面 —— 合并个人信息、画像总览、事实管理、洋葱画像四个 Tab。
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from '@/shared/routing'
import {
  Monitor, Camera, Loader2, AlertCircle, BarChart3,
  Plus, Check, X, Edit3, Trash2, Search, Save, User, Layers, FileText,
} from 'lucide-react'
import { shallow } from 'zustand/shallow'
import { useAuthStore } from '@/shared/store/authStore'
import { userAPI, passwordAPI } from '@/shared/api/api'
import type { LoginDeviceItem } from '@/shared/api/api'
import { passwordChangeSchema } from '@/shared/schemas/auth'
import { appLogger } from '@/shared/utils/logger'
import { useProfileStore } from '@/shared/store/profileStore'
import { extractProfile } from '@/shared/api/profileApi'
import { useNotification } from '@/shared/hooks/useNotification'
import ProfileDashboard from './ProfileDashboard'
import { PROFILE_CATEGORY_LABELS } from './profileCategoryLabels'
import {
  getProfile as getSoulProfile,
  getProbes,
  respondProbe,
  type OnionProfile,
  type Probe,
  type LayerData,
} from '@/features/soul/soulApi'
import ProfileCard from '@/features/soul/ProfileCard'
import ProbeNotification from '@/features/soul/ProbeNotification'
import styles from './UserCenterPage.module.css'

type TabKey = 'personal' | 'overview' | 'facts' | 'soul'

/** 五层画像的层级顺序 */
const LAYER_ORDER = ['surface', 'interest', 'role', 'values', 'core'] as const

const ALL_CATEGORIES = '全部'

function UserCenterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('personal')

  const tabs: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: 'personal', label: '个人信息', icon: <User size={16} /> },
    { key: 'overview', label: '画像总览', icon: <BarChart3 size={16} /> },
    { key: 'facts', label: '事实管理', icon: <FileText size={16} /> },
    { key: 'soul', label: '洋葱画像', icon: <Layers size={16} /> },
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
          {activeTab === 'personal' && <PersonalInfoTab />}
          {activeTab === 'overview' && <ProfileOverviewTab />}
          {activeTab === 'facts' && <FactsManagementTab />}
          {activeTab === 'soul' && <SoulProfileTab />}
        </div>
      </div>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────
 * Tab 1: 个人信息（含密码修改、设备管理、退出登录）
 * ──────────────────────────────────────────────────────────── */
function PersonalInfoTab() {
  const navigate = useNavigate()
  // 使用选择器 + shallow 浅比较，避免整个 store 变化触发重渲染
  const { user, logout } = useAuthStore(s => ({
    user: s.user,
    logout: s.logout,
  }), shallow)

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
    // 使用 zod schema 进行前端校验：必填 + 两次密码一致
    const parseResult = passwordChangeSchema.safeParse({
      oldPassword,
      newPassword,
      confirmPassword,
    })
    if (!parseResult.success) {
      const firstIssue = parseResult.error.issues[0]
      setPasswordMsg({ type: 'error', text: firstIssue?.message ?? '输入无效' })
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

  return (
    <section className={styles['section']}>
      {/* 基本信息编辑 */}
      <h2>个人信息</h2>
      <div className={styles['profile-section']}>
        <div className={styles['avatar-section']}>
          <div className={styles['avatar-preview']}>
            {avatarPreview ? (
              <img src={avatarPreview} alt="头像" className={styles['avatar-img']} loading="lazy" decoding="async" />
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

      {/* 修改密码 */}
      <div className={styles['sub-section']}>
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
      </div>

      {/* 设备管理 */}
      <div className={styles['sub-section']}>
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
      </div>

      {/* 退出登录 */}
      <div className={styles['logout-section']}>
        <h2>退出登录</h2>
        <p className={styles['section-desc']}>退出当前会话后需要重新登录。</p>
        <button className="btn btn-secondary" onClick={() => void handleLogout()}>
          退出登录
        </button>
      </div>
    </section>
  )
}

/* ────────────────────────────────────────────────────────────
 * Tab 2: 画像总览（雷达图/时间线/置信度条）
 * ──────────────────────────────────────────────────────────── */
function ProfileOverviewTab() {
  return (
    <section className={styles['section']}>
      <h2>画像总览</h2>
      <div className={styles['dashboard-wrapper']}>
        <ProfileDashboard />
      </div>
    </section>
  )
}

/* ────────────────────────────────────────────────────────────
 * Tab 3: 事实管理（画像事实 CRUD）
 * ──────────────────────────────────────────────────────────── */
function FactsManagementTab() {
  // 使用选择器 + shallow 浅比较，避免整个 store 变化触发重渲染
  const {
    facts, loading, extracting, error,
    fetchFacts, fetchStats,
    editFact, addFact, removeFact,
    confirmFact, disputeFactItem,
    setSelectedCategory,
    clearError,
  } = useProfileStore(s => ({
    facts: s.facts,
    loading: s.loading,
    extracting: s.extracting,
    error: s.error,
    fetchFacts: s.fetchFacts,
    fetchStats: s.fetchStats,
    editFact: s.editFact,
    addFact: s.addFact,
    removeFact: s.removeFact,
    confirmFact: s.confirmFact,
    disputeFactItem: s.disputeFactItem,
    setSelectedCategory: s.setSelectedCategory,
    clearError: s.clearError,
  }), shallow)

  const [searchTerm, setSearchTerm] = useState('')
  const [editingFactId, setEditingFactId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [showAddForm, setShowAddForm] = useState(false)
  const [newCategory, setNewCategory] = useState('preference')
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')
  // 使用统一的 useNotification hook 管理成功消息，自动清理定时器避免内存泄漏
  const { message: successMsg, showNotification: showSuccessMsg } = useNotification(2000)
  const [activeCategory, setActiveCategory] = useState(ALL_CATEGORIES)

  useEffect(() => {
    void fetchFacts()
    void fetchStats()
  }, [fetchFacts, fetchStats])

  const handleCategoryFilter = (cat: string) => {
    setActiveCategory(cat)
    setSelectedCategory(cat === ALL_CATEGORIES ? null : cat)
    void fetchFacts({ category: cat === ALL_CATEGORIES ? undefined : cat })
  }

  const startEdit = (factId: string, currentValue: string) => {
    setEditingFactId(factId)
    setEditValue(currentValue)
  }

  const cancelEdit = () => {
    setEditingFactId(null)
    setEditValue('')
  }

  const saveEdit = async (factId: string) => {
    if (!editValue.trim()) return
    await editFact(factId, editValue.trim())
    setEditingFactId(null)
    setEditValue('')
    showSuccessMsg({ type: 'success', text: '已更新' })
  }

  const handleAdd = async () => {
    if (!newKey.trim() || !newValue.trim()) return
    await addFact(newCategory, newKey.trim().toLowerCase().replace(/\s+/g, '_'), newValue.trim())
    setShowAddForm(false)
    setNewKey('')
    setNewValue('')
    showSuccessMsg({ type: 'success', text: '已添加' })
  }

  const handleDelete = async (factId: string) => {
    if (!confirm('确定删除此画像事实吗？')) return
    await removeFact(factId)
    showSuccessMsg({ type: 'success', text: '已删除' })
  }

  const handleVerify = async (factId: string) => {
    await confirmFact(factId)
    showSuccessMsg({ type: 'success', text: '已确认' })
  }

  const handleDispute = async (factId: string) => {
    await disputeFactItem(factId)
    showSuccessMsg({ type: 'success', text: '已反馈，将重新评估' })
  }

  const handleExtract = async () => {
    await extractProfile({})
    await fetchFacts()
    await fetchStats()
    showSuccessMsg({ type: 'success', text: '提取完成' })
  }

  // 按类别分组
  const groupedFacts: Record<string, typeof facts> = facts.reduce((acc, fact) => {
    const cat = fact.category
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(fact)
    return acc
  }, {} as Record<string, typeof facts>)

  // 搜索过滤
  const filteredGrouped = searchTerm.trim()
    ? Object.fromEntries(
        Object.entries(groupedFacts).map(([cat, catFacts]) => [
          cat,
          catFacts.filter((f) =>
            f.fact_key.includes(searchTerm.toLowerCase()) ||
            f.fact_value.includes(searchTerm)
          ),
        ]).filter((entry): entry is [string, typeof facts] => entry[1].length > 0)
      )
    : groupedFacts

  // 获取所有存在的类别
  const allCategories = [ALL_CATEGORIES, ...Object.keys(PROFILE_CATEGORY_LABELS).filter(
    (c) => c !== 'custom'
  )]

  return (
    <section className={`${styles['section']} ${styles['facts-tab']}`}>
      {/* 顶部操作栏 */}
      <div className={styles['facts-top-bar']}>
        <h2>事实管理</h2>
        <div className={styles['facts-top-actions']}>
          {successMsg && <span className={styles['success-msg']}>{successMsg.text}</span>}
          <button
            className="btn btn-primary"
            onClick={() => void handleExtract()}
            disabled={extracting}
          >
            {extracting ? <><Loader2 size={14} className={styles['spin']} /> 提取中...</> : '智能提取'}
          </button>
          <button className="btn btn-secondary" onClick={() => setShowAddForm(!showAddForm)}>
            <Plus size={14} /> 手动添加
          </button>
        </div>
      </div>

      {error && (
        <div className={styles['error-banner']}>
          <AlertCircle size={16} />
          <span>{error}</span>
          <button onClick={clearError}>关闭</button>
        </div>
      )}

      {/* 搜索和筛选 */}
      <div className={styles['facts-toolbar']}>
        <div className={styles['search-box']}>
          <Search size={14} />
          <input
            type="text"
            placeholder="搜索事实..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div className={styles['category-filters']}>
          {allCategories.map((cat) => (
            <button
              key={cat}
              className={`${styles['filter-btn']} ${activeCategory === cat ? styles['filter-active'] : ''}`}
              onClick={() => handleCategoryFilter(cat)}
            >
              {cat === ALL_CATEGORIES ? '全部' : PROFILE_CATEGORY_LABELS[cat] || cat}
            </button>
          ))}
        </div>
      </div>

      {/* 添加表单 */}
      {showAddForm && (
        <div className={styles['add-form']}>
          <h3>添加画像事实</h3>
          <div className={styles['add-form-fields']}>
            <select value={newCategory} onChange={(e) => setNewCategory(e.target.value)}>
              {Object.entries(PROFILE_CATEGORY_LABELS).filter(([k]) => k !== 'custom').map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
            <input
              type="text"
              placeholder="键名（如 preferred_language）"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
            />
            <input
              type="text"
              placeholder="值（如 Python）"
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
            />
            <button className="btn btn-primary" onClick={() => void handleAdd()}>
              <Save size={14} /> 保存
            </button>
            <button className="btn btn-secondary" onClick={() => setShowAddForm(false)}>取消</button>
          </div>
        </div>
      )}

      {/* 事实列表 */}
      <div className={styles['facts-container']}>
        {loading ? (
          <div className={styles['loading']}>
            <Loader2 size={24} className={styles['spin']} />
            <span>加载中...</span>
          </div>
        ) : Object.keys(filteredGrouped).length === 0 ? (
          <div className={styles['editor-empty']}>
            <p>暂无画像数据</p>
            <p className={styles['hint']}>使用"智能提取"或"手动添加"来创建画像事实</p>
          </div>
        ) : (
          Object.entries(filteredGrouped).map(([category, items]) => (
            <div key={category} className={styles['category-section']}>
              <h3 className={styles['category-title']}>
                {PROFILE_CATEGORY_LABELS[category] || category}
                <span className={styles['category-count']}>{items.length} 条</span>
              </h3>
              <div className={styles['facts-list']}>
                {items.map((fact) => (
                  <div key={fact.id} className={styles['fact-card']}>
                    <div className={styles['fact-header']}>
                      <code className={styles['fact-key']}>{fact.fact_key}</code>
                      <span
                        className={`${styles['conf-badge']} ${
                          fact.confidence_label === '高' ? styles['conf-high'] :
                          fact.confidence_label === '中' ? styles['conf-med'] :
                          styles['conf-low']
                        }`}
                      >
                        {fact.confidence_label} ({(fact.confidence * 100).toFixed(0)}%)
                      </span>
                      <span className={styles['source-badge']}>{fact.source_type}</span>
                    </div>

                    <div className={styles['fact-body']}>
                      {editingFactId === fact.id ? (
                        <div className={styles['edit-row']}>
                          <input
                            type="text"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            className={styles['edit-input']}
                            autoFocus
                          />
                          <button
                            className={styles['action-btn-sm']}
                            onClick={() => void saveEdit(fact.id)}
                            title="保存"
                          >
                            <Check size={14} />
                          </button>
                          <button
                            className={styles['action-btn-sm']}
                            onClick={cancelEdit}
                            title="取消"
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ) : (
                        <span className={styles['fact-val']}>{fact.fact_value}</span>
                      )}
                    </div>

                    <div className={styles['fact-footer']}>
                      <span className={styles['fact-meta']}>
                        更新于 {fact.last_updated_at ? new Date(fact.last_updated_at).toLocaleDateString('zh-CN') : '未知'}
                        {fact.verification_count > 0 && ` · 已验证 ${fact.verification_count} 次`}
                      </span>
                      <div className={styles['fact-actions']}>
                        <button
                          className={styles['action-btn']}
                          onClick={() => void handleVerify(fact.id)}
                          title="确认此事实"
                        >
                          <Check size={14} /> 确认
                        </button>
                        <button
                          className={styles['action-btn']}
                          onClick={() => void handleDispute(fact.id)}
                          title="否定此事实"
                        >
                          <X size={14} /> 否定
                        </button>
                        <button
                          className={styles['action-btn']}
                          onClick={() => startEdit(fact.id, fact.fact_value)}
                          title="编辑"
                          disabled={editingFactId !== null}
                        >
                          <Edit3 size={14} /> 编辑
                        </button>
                        <button
                          className={`${styles['action-btn']} ${styles['action-danger']}`}
                          onClick={() => void handleDelete(fact.id)}
                          title="删除"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  )
}

/* ────────────────────────────────────────────────────────────
 * Tab 4: 洋葱画像（五层洋葱模型 + 探针响应）
 * ──────────────────────────────────────────────────────────── */
function SoulProfileTab() {
  const [profile, setProfile] = useState<OnionProfile | null>(null)
  const [probes, setProbes] = useState<Probe[]>([])
  const [expandedLayers, setExpandedLayers] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  /** 加载画像和探针数据 */
  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [profileRes, probesRes] = await Promise.all([
        getSoulProfile(),
        getProbes(),
      ])

      setProfile(profileRes.profile)
      setProbes(probesRes.probes.filter((p) => p.status === 'pending'))
    } catch {
      setError('加载 Soul 画像数据失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  /** 切换某层画像的展开/折叠状态 */
  const toggleLayer = useCallback((layerName: string) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev)
      if (next.has(layerName)) {
        next.delete(layerName)
      } else {
        next.add(layerName)
      }
      return next
    })
  }, [])

  /** 响应探针 */
  const handleProbeRespond = useCallback(
    async (probeId: number, status: 'confirmed' | 'rejected') => {
      try {
        await respondProbe(probeId, status)
        setProbes((prev) => prev.filter((p) => p.id !== probeId))
      } catch {
        setError('探针响应失败，请稍后重试')
      }
    },
    []
  )

  /** 计算总体置信度（五层平均值） */
  const getOverallConfidence = useCallback((): number => {
    if (!profile) return 0
    const layers: LayerData[] = [
      profile.surface,
      profile.interest,
      profile.role,
      profile.values,
      profile.core,
    ]
    const sum = layers.reduce((acc, layer) => acc + layer.confidence, 0)
    return Math.round((sum / layers.length) * 100)
  }, [profile])

  if (loading) {
    return (
      <section className={styles['section']}>
        <div className={styles['loading']}>
          <Loader2 size={24} className={styles['spin']} />
          <span>加载中...</span>
        </div>
      </section>
    )
  }

  if (error && !profile) {
    return (
      <section className={styles['section']}>
        <div className={styles['soul-error-state']}>
          <p>{error}</p>
          <button
            className={styles['retry-btn']}
            onClick={loadData}
            type="button"
          >
            重试
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className={styles['section']}>
      {/* 页面标题 */}
      <div className={styles['soul-header']}>
        <h2>洋葱画像</h2>
        <span className={styles['header-subtitle']}>
          五层洋葱模型 - AI 理解的你
        </span>
      </div>

      {/* 用户画像摘要 */}
      {profile && (
        <div className={styles['summary-bar']}>
          <div className={styles['summary-item']}>
            <span className={styles['summary-label']}>用户 ID</span>
            <span className={styles['summary-value']}>{profile.user_id}</span>
          </div>
          <div className={styles['summary-item']}>
            <span className={styles['summary-label']}>总体置信度</span>
            <span className={styles['summary-value']}>
              {getOverallConfidence()}%
            </span>
          </div>
          <div className={styles['summary-item']}>
            <span className={styles['summary-label']}>最后更新</span>
            <span className={styles['summary-value']}>
              {formatDate(profile.updated_at)}
            </span>
          </div>
        </div>
      )}

      {/* 全局错误提示 */}
      {error && (
        <div className={styles['error-toast']}>
          <span>{error}</span>
          <button
            className={styles['dismiss-btn']}
            onClick={() => setError(null)}
            type="button"
          >
            x
          </button>
        </div>
      )}

      {/* 待确认的兴趣探针 */}
      <ProbeNotification probes={probes} onRespond={handleProbeRespond} />

      {/* 五层画像卡片 */}
      <div className={styles['layers-section']}>
        <h3 className={styles['soul-section-title']}>五层画像</h3>
        {profile ? (
          LAYER_ORDER.map((layerName) => {
            const layerData = profile[layerName]
            return (
              <ProfileCard
                key={layerName}
                layerName={layerName}
                layerData={layerData}
                isExpanded={expandedLayers.has(layerName)}
                onToggle={() => toggleLayer(layerName)}
              />
            )
          })
        ) : (
          <div className={styles['empty-hint']}>
            暂无画像数据，请先与 AI 进行对话以生成画像
          </div>
        )}
      </div>
    </section>
  )
}

/** 密码强度评估 */
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

/** 格式化日期字符串 */
function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  try {
    const date = new Date(dateStr)
    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateStr
  }
}

export default UserCenterPage
