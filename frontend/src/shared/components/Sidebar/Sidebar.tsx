import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  MessageSquare, LayoutDashboard, CreditCard, Zap,
  Clock, Blocks, Brain, Settings, Award, Radio,
  Cat, Sun, Moon, Menu, ChevronDown, Bell,
  Users, ShoppingBag, Network, Terminal,
  MessagesSquare,
  MessageSquareWarning,
  Layers,
} from 'lucide-react'
import { useThemeStore } from '../../store/themeStore'
import { useI18nStore } from '@/i18n'
import { UserFloatingArea } from '../UserFloatingArea'
import { Tooltip } from '@/shared/components/ui'
import { useIssueFeedbackStore } from '@/shared/store/issueFeedbackStore'
import styles from './Sidebar.module.css'

interface MenuItem {
  path: string
  label: string
  iconType: 'chat' | 'dashboard' | 'billing' | 'skills' | 'scheduledTasks' | 'plugins' | 'memory' | 'settings' | 'experience' | 'workspace' | 'coding' | 'inbox' | 'roles' | 'im' | 'roleMarket' | 'subagents' | 'vibeCoding' | 'discussions' | 'userProfile' | 'pets'
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
        { path: '/tts', label: t('sidebar.tts') || 'TTS', iconType: 'skills' as const },
        { path: '/roles', label: t('sidebar.roles') || '角色管理', iconType: 'roles' as const },
        { path: '/role-market', label: t('sidebar.roleMarket') || '角色市场', iconType: 'roleMarket' as const },
        { path: '/pets', label: t('sidebar.pets') || '宠物', iconType: 'pets' as const },
        { path: '/skills', label: t('sidebar.skills'), iconType: 'skills' as const },
        { path: '/scheduled-tasks', label: t('sidebar.scheduledTasks'), iconType: 'scheduledTasks' as const },
        { path: '/workflows', label: t('sidebar.workflows') || '工作流', iconType: 'scheduledTasks' as const },
        { path: '/subagents', label: t('sidebar.subagents') || '子智能体', iconType: 'subagents' as const },
        { path: '/discussions', label: t('sidebar.discussions'), iconType: 'discussions' as const },
        { path: '/plugins/manage', label: t('sidebar.plugins'), iconType: 'plugins' as const },
        { path: '/memory', label: t('sidebar.memory'), iconType: 'memory' as const },
        { path: '/experience', label: t('sidebar.experience'), iconType: 'experience' as const },
        { path: '/user-profile', label: t('sidebar.userProfile') || '我的画像', iconType: 'userProfile' as const },
      ]
    },
    {
      id: 'settings',
      title: t('sidebar.settings'),
      items: [
        { path: '/settings', label: t('sidebar.settings'), iconType: 'settings' as const },
        { path: '/im', label: t('sidebar.im') || 'IM 渠道', iconType: 'im' as const },
      ]
    }
  ]
  /* 移动端侧边栏展开状态 */
  const [mobileOpen, setMobileOpen] = useState(false)
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    control: true,
    agent: true,
    settings: true,
  })

  /* 汉堡菜单按钮引用：用于抽屉关闭后将焦点返回到触发按钮，符合无障碍焦点流转规范 */
  const menuBtnRef = useRef<HTMLButtonElement>(null)

  /* 滑动手势状态：touchStartRef 记录起始 x 坐标，dragOffset 记录当前拖动偏移量（仅向左为负）*/
  const touchStartRef = useRef<number | null>(null)
  const dragOffsetRef = useRef(0)
  const [dragOffset, setDragOffset] = useState(0)

  /* 监听窗口大小变化，在非移动端时自动关闭移动端菜单 */
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth > 768) {
        setMobileOpen(false)
      }
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  /* 路由切换时自动关闭移动端菜单 */
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  /* 移动端打开时阻止背景滚动 */
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [mobileOpen])

  /* 焦点管理：抽屉从打开变为关闭时，焦点返回汉堡菜单按钮，便于键盘用户继续操作 */
  useEffect(() => {
    if (!mobileOpen && menuBtnRef.current) {
      // 延迟一帧避免与点击事件冲突
      requestAnimationFrame(() => menuBtnRef.current?.focus())
    }
  }, [mobileOpen])

  const toggleMobile = useCallback(() => {
    setMobileOpen((prev) => !prev)
  }, [])

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
      setMobileOpen(false)
    }
    dragOffsetRef.current = 0
    setDragOffset(0)
    touchStartRef.current = null
  }, [])

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
      {/* 移动端汉堡菜单按钮 */}
      <button
        ref={menuBtnRef}
        className={styles['mobile-menu-btn']}
        data-testid="mobile-menu-btn"
        onClick={toggleMobile}
        title={t('sidebar.menu')}
        aria-label={t('sidebar.menu')}
        aria-expanded={mobileOpen}
      >
        <Menu size={22} />
      </button>

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
                <img src={config.logoIcon} alt="Logo" className={styles['custom-logo-icon']} fetchPriority="high" decoding="async" />
              ) : (
                <img src="/logo.svg" alt="Logo" className={styles['custom-logo-icon']} fetchPriority="high" decoding="async" />
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
                      className={`${styles['sidebar-item']} ${active ? styles['active'] : ''}`}
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
              setMobileOpen(false)
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
