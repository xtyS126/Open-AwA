import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Link, useLocation, useNavigate } from '@/shared/routing'
import {
  MessageSquare, LayoutDashboard, CreditCard, Zap,
  Clock, Blocks, Brain, Settings, Award, Radio,
  Cat, Sun, Moon, Menu, ChevronDown, Bell,
  Users, ShoppingBag, Network, Terminal,
  MessagesSquare,
  MessageSquareWarning,
  Layers,
  LogOut,
  UserRound,
} from 'lucide-react'
import { useThemeStore } from '../../store/themeStore'
import { useMobileNavStore } from '@/shared/store/mobileNavStore'
import { useAuthStore } from '@/shared/store/authStore'
import { useI18nStore } from '@/i18n'
import { UserFloatingArea } from '../UserFloatingArea'
import { Tooltip } from '@/shared/components/ui'
import { useIssueFeedbackStore } from '@/shared/store/issueFeedbackStore'
import { authAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import styles from './Sidebar.module.css'

interface MenuItem {
  path: string
  label: string
  iconType: 'chat' | 'dashboard' | 'billing' | 'skills' | 'scheduledTasks' | 'plugins' | 'memory' | 'settings' | 'experience' | 'workspace' | 'coding' | 'inbox' | 'roles' | 'im' | 'roleMarket' | 'subagents' | 'vibeCoding' | 'discussions' | 'userProfile' | 'pets'
  /** 移动端抽屉（≤768px）隐藏：底部 Tab Bar 已有直达入口，抽屉内不重复展示（桌面端侧边栏保留） */
  mobileHidden?: boolean
}

interface MenuGroup {
  id: string
  title: string
  items: MenuItem[]
}

const renderIcon = (type: string, size = 18) => {
  switch (type) {
    case 'chat': return <MessageSquare size={size} />
    case 'workspace': return <Cat size={size} />
    case 'coding': return <Blocks size={size} />
    case 'dashboard': return <LayoutDashboard size={size} />
    case 'billing': return <CreditCard size={size} />
    case 'skills': return <Zap size={size} />
    case 'scheduledTasks': return <Clock size={size} />
    case 'plugins': return <Blocks size={size} />
    case 'memory': return <Brain size={size} />
    case 'pets': return <Cat size={size} />
    case 'settings': return <Settings size={size} />
    case 'experience': return <Award size={size} />
    case 'im': return <Radio size={size} />
    case 'inbox': return <Bell size={size} />
    case 'roles': return <Users size={size} />
    case 'roleMarket': return <ShoppingBag size={size} />
    case 'subagents': return <Network size={size} />
    case 'vibeCoding': return <Terminal size={size} />
    case 'discussions': return <MessagesSquare size={size} />
    case 'userProfile': return <Layers size={size} />
    default: return <MessageSquare size={size} />
  }
}

/**
 * 移动端左上角用户区：替代原汉堡按钮位置，展示头像 + 姓名。
 * 点击后停留在当前页面（不整页跳转），弹出用户菜单浮层：
 * 用户中心入口 / 退出登录；完整导航抽屉仍由底部 Tab Bar "更多"打开。
 */
function MobileUserArea() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const { t } = useI18nStore()
  const [open, setOpen] = useState(false)
  /* 仅在聊天页显示：设置/记忆/技能等页面顶部有各自导航，不重复展示用户区浮层 */
  const isChatPage = location.pathname === '/chat' || location.pathname.startsWith('/chat/')
  if (!isChatPage || !user) return null
  const initial = (user.username || 'U')[0].toUpperCase()

  /* 退出登录：接口失败也清除本地会话并回登录页（与 UserFloatingArea 行为一致） */
  const handleLogout = async () => {
    try {
      await authAPI.logout()
    } catch (error) {
      appLogger.warning({
        event: 'logout_api_failed',
        module: 'auth',
        message: 'logout api call failed',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <>
      <button
        type="button"
        className={styles['mobile-user-area']}
        onClick={() => setOpen((o) => !o)}
        title={t('user.center')}
        aria-label={t('user.center')}
        aria-expanded={open}
        data-testid="mobile-user-area"
      >
        <span className={styles['mobile-user-avatar']}>{initial}</span>
        <span className={styles['mobile-user-name']}>{user.username}</span>
      </button>
      {/* 用户菜单浮层：点击头像在当前页弹出，遮罩点击关闭，不卸载当前页面 */}
      {open && (
        <>
          <div
            className={styles['user-menu-overlay']}
            data-testid="user-menu-overlay"
            onClick={() => setOpen(false)}
          />
          <div
            className={styles['user-menu']}
            role="menu"
            aria-label={t('user.center')}
            data-testid="user-menu"
          >
            <div className={styles['user-menu-header']}>
              <span className={styles['mobile-user-avatar']}>{initial}</span>
              <span className={styles['user-menu-name']}>{user.username}</span>
            </div>
            <button
              type="button"
              role="menuitem"
              className={styles['user-menu-item']}
              onClick={() => {
                setOpen(false)
                navigate('/user')
              }}
            >
              <UserRound size={16} />
              {t('user.center')}
            </button>
            <button
              type="button"
              role="menuitem"
              className={styles['user-menu-item']}
              onClick={handleLogout}
            >
              <LogOut size={16} />
              {t('user.logout')}
            </button>
          </div>
        </>
      )}
    </>
  )
}

  function Sidebar() {
  const location = useLocation()
  const { theme, toggleTheme, config } = useThemeStore()
  const { t } = useI18nStore()
  const [collapsed, setCollapsed] = useState(false)

  const menuGroups: MenuGroup[] = [
    {
      id: 'control',
      title: t('sidebar.control'),
      items: [
        { path: '/chat', label: t('sidebar.chat'), iconType: 'chat' as const },
        { path: '/coding', label: t('sidebar.coding'), iconType: 'coding' as const },
        { path: '/vibe-coding', label: t('sidebar.vibeCoding'), iconType: 'vibeCoding' as const },
        { path: '/workspace', label: t('sidebar.workspace'), iconType: 'workspace' as const },
        { path: '/dashboard', label: t('sidebar.dashboard'), iconType: 'dashboard' as const },
        { path: '/billing', label: t('sidebar.billing'), iconType: 'billing' as const },
        { path: '/inbox', label: t('sidebar.inbox'), iconType: 'inbox' as const },
      ]
    },
    {
      id: 'agent',
      title: t('sidebar.agent'),
      items: [
        { path: '/tts', label: t('sidebar.tts'), iconType: 'skills' as const },
        { path: '/roles', label: t('sidebar.roles'), iconType: 'roles' as const },
        { path: '/role-market', label: t('sidebar.roleMarket'), iconType: 'roleMarket' as const },
        { path: '/pets', label: t('sidebar.pets'), iconType: 'pets' as const },
        { path: '/skills', label: t('sidebar.skills'), iconType: 'skills' as const, mobileHidden: true },
        { path: '/scheduled-tasks', label: t('sidebar.scheduledTasks'), iconType: 'scheduledTasks' as const },
        { path: '/workflows', label: t('sidebar.workflows'), iconType: 'scheduledTasks' as const },
        { path: '/subagents', label: t('sidebar.subagents'), iconType: 'subagents' as const },
        { path: '/discussions', label: t('sidebar.discussions'), iconType: 'discussions' as const },
        { path: '/plugins/manage', label: t('sidebar.plugins'), iconType: 'plugins' as const },
        { path: '/memory', label: t('sidebar.memory'), iconType: 'memory' as const, mobileHidden: true },
        { path: '/experience', label: t('sidebar.experience'), iconType: 'experience' as const },
      ]
    },
    {
      id: 'settings',
      title: t('sidebar.settings'),
      items: [
        { path: '/user', label: t('user.center'), iconType: 'userProfile' as const },
        { path: '/settings', label: t('sidebar.settings'), iconType: 'settings' as const, mobileHidden: true },
        { path: '/im', label: t('sidebar.im'), iconType: 'im' as const },
      ]
    }
  ]
  /* 移动端侧边栏展开状态：与底部 Tab Bar "更多"入口共享全局开关 */
  const mobileOpen = useMobileNavStore((s) => s.drawerOpen)
  const closeDrawer = useMobileNavStore((s) => s.closeDrawer)
  const toggleMobile = useMobileNavStore((s) => s.toggleDrawer)
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    control: true,
    agent: true,
    settings: true,
  })

  /* 滑动手势状态：touchStartRef 记录起始 x 坐标，dragOffset 记录当前拖动偏移量（仅向左为负）*/
  const touchStartRef = useRef<number | null>(null)
  const dragOffsetRef = useRef(0)
  const [dragOffset, setDragOffset] = useState(0)

  /* 监听窗口大小变化，在非移动端时自动关闭移动端菜单 */
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth > 768) {
        closeDrawer()
      }
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [closeDrawer])

  /* 路由切换时自动关闭移动端菜单 */
  useEffect(() => {
    closeDrawer()
  }, [closeDrawer, location.pathname])

  /* 移动端打开时阻止背景滚动 */
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [mobileOpen])

  /* 滑动手势：touchstart 记录起始坐标 */
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (!mobileOpen) return
    touchStartRef.current = e.touches[0].clientX
  }, [mobileOpen])

  /* 滑动手势：touchmove 计算偏移量，仅向左滑动（offset < 0）时跟手 */
  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (touchStartRef.current === null) return
    const offset = e.touches[0].clientX - touchStartRef.current
    if (offset < 0) {
      dragOffsetRef.current = offset
      setDragOffset(offset)
    }
  }, [])

  /* 滑动手势：touchend 判断是否达到关闭阈值（向左 > 60px），重置状态 */
  const handleTouchEnd = useCallback(() => {
    if (touchStartRef.current === null) return
    if (dragOffsetRef.current < -60) {
      closeDrawer()
    }
    dragOffsetRef.current = 0
    setDragOffset(0)
    touchStartRef.current = null
  }, [closeDrawer])

  /* 抽屉跟手偏移：拖动过程中临时覆盖 transform 与 transition，避免渐变延迟 */
  const asideStyle: React.CSSProperties = dragOffset !== 0
    ? { transform: `translateX(${dragOffset}px)`, transition: 'none' }
    : {}

  const toggleGroup = (groupId: string) => {
    setExpandedGroups(prev => ({
      ...prev,
      [groupId]: !prev[groupId]
    }))
  }

  const isActive = (path: string) => {
    if (path.includes('?')) {
      return location.pathname + location.search === path
    }
    if (path === '/chat') {
      return location.pathname === '/chat' || location.pathname.startsWith('/chat/')
    }
    if (path === '/plugins/manage') {
      return location.pathname === '/plugins/manage' || location.pathname.startsWith('/plugins/config')
    }
    if (path === '/discussions') {
      // 讨论任务详情页 /discussions/:id 也高亮列表项
      return location.pathname === '/discussions' || location.pathname.startsWith('/discussions/')
    }
    if (path === '/settings') {
      return location.pathname === '/settings' && (!location.search || !location.search.includes('tab='))
    }
    return location.pathname === path
  }

  return (
    <>
      {/* 移动端左上角用户区：头像 + 姓名，点击进入用户中心（替代原汉堡按钮） */}
      <MobileUserArea />

      {/* 移动端遮罩层：始终渲染，通过 visible 类切换可见性实现 opacity 渐变 */}
      <div
        className={`${styles['mobile-overlay']} ${mobileOpen ? styles['visible'] : ''}`}
        data-testid="mobile-overlay"
        data-visible={mobileOpen}
        onClick={toggleMobile}
        aria-hidden={!mobileOpen}
      />

      <aside
        className={`${styles['sidebar']} ${collapsed ? styles['collapsed'] : ''} ${mobileOpen ? styles['mobile-open'] : ''}`}
        data-testid="sidebar"
        data-collapsed={collapsed}
        data-mobile-open={mobileOpen}
        style={asideStyle}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
      <div className={styles['sidebar-header']}>
        {!collapsed && (
          <>
            <div className={styles['logo-container']}>
              {config.logoIcon ? (
                <img src={config.logoIcon} alt="Logo" className={styles['custom-logo-icon']} decoding="async" {...{ fetchpriority: 'high' } as React.ImgHTMLAttributes<HTMLImageElement>} />
              ) : (
                <img src="/logo.svg" alt="Logo" className={styles['custom-logo-icon']} decoding="async" {...{ fetchpriority: 'high' } as React.ImgHTMLAttributes<HTMLImageElement>} />
              )}
              <span className={styles['logo-text']}>Open-AwA</span>
            </div>
          </>
        )}
        <button
          className={styles['collapse-btn']}
          data-testid="sidebar-collapse-btn"
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
          aria-label={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
        >
          <Menu size={20} />
        </button>
      </div>
      
      <nav className={styles['sidebar-nav']} role="navigation" aria-label="主导航">
        {menuGroups.map((group, groupIndex) => (
          <div key={group.id} className={styles['menu-group']}>
            {/* 分组之间的分隔线（第一个分组前不显示） */}
            {groupIndex > 0 && !collapsed && <div className={styles['group-divider']} />}
            <div
              className={styles['group-header']}
              onClick={() => toggleGroup(group.id)}
              role="button"
              tabIndex={0}
              aria-expanded={expandedGroups[group.id]}
              aria-label={group.title}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  toggleGroup(group.id)
                }
              }}
            >
              {!collapsed && (
                <>
                  <span className={styles['group-title']}>{group.title}</span>
                  <span className={`${styles['chevron']} ${expandedGroups[group.id] ? styles['expanded'] : ''}`}>
                    <ChevronDown size={16} />
                  </span>
                </>
              )}
              {/* 折叠模式下分组之间用分隔线替代 */}
              {collapsed && groupIndex > 0 && <div className={styles['group-divider']} />}
            </div>

            {expandedGroups[group.id] && (
              <div className={styles['group-items']}>
                {group.items.map((item) => {
                  const active = isActive(item.path)
                  const linkContent = (
                    <Link
                      key={item.path}
                      to={item.path}
                      className={`${styles['sidebar-item']} ${active ? styles['active'] : ''} ${item.mobileHidden ? styles['mobile-hidden-item'] : ''}`}
                      data-testid="sidebar-item"
                      aria-current={active ? 'page' : undefined}
                    >
                      <span className={styles['sidebar-icon']}>{renderIcon(item.iconType, 18)}</span>
                      {!collapsed && <span className={styles['sidebar-label']}>{item.label}</span>}
                    </Link>
                  )
                  return collapsed ? (
                    <Tooltip key={item.path} content={item.label} position="right">
                      {linkContent}
                    </Tooltip>
                  ) : (
                    linkContent
                  )
                })}
              </div>
            )}
          </div>
        ))}

        {/* 问题反馈入口：独立按钮，不在 menuGroups 数据结构中，点击打开全局反馈面板 */}
        {!collapsed ? (
          <button
            className={styles['sidebar-item']}
            onClick={() => {
              useIssueFeedbackStore.getState().open()
              closeDrawer()
            }}
            data-testid="sidebar-issue-feedback-btn"
            aria-label={t('sidebar.issueFeedback') || '问题反馈'}
            type="button"
          >
            <span className={styles['sidebar-icon']}><MessageSquareWarning size={18} /></span>
            <span className={styles['sidebar-label']}>{t('sidebar.issueFeedback') || '问题反馈'}</span>
          </button>
        ) : (
          <Tooltip content={t('sidebar.issueFeedback') || '问题反馈'} position="right">
            <button
              className={styles['sidebar-item']}
              onClick={() => useIssueFeedbackStore.getState().open()}
              aria-label={t('sidebar.issueFeedback') || '问题反馈'}
              type="button"
              data-testid="sidebar-issue-feedback-btn"
            >
              <span className={styles['sidebar-icon']}><MessageSquareWarning size={18} /></span>
            </button>
          </Tooltip>
        )}

        {/* User Floating Area inserted at the bottom of the nav */}
        <div className={styles['nav-bottom-spacer']}></div>
        <UserFloatingArea collapsed={collapsed} />
      </nav>
      
      <div className={styles['sidebar-footer']}>
        <button
          className={styles['theme-toggle-btn']}
          data-testid="theme-toggle-btn"
          onClick={toggleTheme}
          title={theme === 'light' ? t('sidebar.darkMode') : t('sidebar.lightMode')}
          aria-label={`${t('sidebar.theme')}: ${theme === 'light' ? t('sidebar.darkMode') : t('sidebar.lightMode')}`}
        >
          {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
          {!collapsed && <span className={styles['theme-label']}>{theme === 'light' ? t('sidebar.nightMode') : t('sidebar.dayMode')}</span>}
        </button>
        {!collapsed && <p className={styles['version-text']}>v1.0.0</p>}
      </div>
    </aside>
    </>
  )
}

export default Sidebar
