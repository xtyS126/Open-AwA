import { useState, useEffect, useCallback } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  MessageSquare, LayoutDashboard, CreditCard, Zap,
  Clock, Blocks, Brain, Settings, Award, Radio,
  Cat, Sun, Moon, Menu, ChevronDown, Palette, Bell,
  Users, BarChart3, ShoppingBag, Network, Terminal,
  MessagesSquare
} from 'lucide-react'
import { useThemeStore } from '../../store/themeStore'
import { useI18nStore } from '@/i18n'
import { UserFloatingArea } from '../UserFloatingArea'
import { Tooltip } from '@/shared/components/ui'
import styles from './Sidebar.module.css'

interface MenuItem {
  path: string
  label: string
  iconType: 'chat' | 'dashboard' | 'billing' | 'skills' | 'scheduledTasks' | 'plugins' | 'memory' | 'settings' | 'experience' | 'communication' | 'theme' | 'workspace' | 'coding' | 'inbox' | 'roles' | 'data' | 'im' | 'roleMarket' | 'subagents' | 'vibeCoding' | 'discussions'
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
    case 'settings': return <Settings size={size} />
    case 'experience': return <Award size={size} />
    case 'communication': return <Radio size={size} />
    case 'im': return <Radio size={size} />
    case 'theme': return <Palette size={size} />
    case 'inbox': return <Bell size={size} />
    case 'roles': return <Users size={size} />
    case 'roleMarket': return <ShoppingBag size={size} />
    case 'data': return <BarChart3 size={size} />
    case 'subagents': return <Network size={size} />
    case 'vibeCoding': return <Terminal size={size} />
    case 'discussions': return <MessagesSquare size={size} />
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
        { path: '/data', label: t('sidebar.data') || '数据看板', iconType: 'data' as const },
        { path: '/skills', label: t('sidebar.skills'), iconType: 'skills' as const },
        { path: '/scheduled-tasks', label: t('sidebar.scheduledTasks'), iconType: 'scheduledTasks' as const },
        { path: '/workflows', label: t('sidebar.workflows') || '工作流', iconType: 'scheduledTasks' as const },
        { path: '/subagents', label: t('sidebar.subagents') || '子智能体', iconType: 'subagents' as const },
        { path: '/discussions', label: t('sidebar.discussions'), iconType: 'discussions' as const },
        { path: '/plugins/manage', label: t('sidebar.plugins'), iconType: 'plugins' as const },
        { path: '/memory', label: t('sidebar.memory'), iconType: 'memory' as const },
        { path: '/experience', label: t('sidebar.experience'), iconType: 'experience' as const },
      ]
    },
    {
      id: 'appearance',
      title: t('sidebar.theme'),
      items: [
        { path: '/theme', label: t('sidebar.theme'), iconType: 'theme' as const },
      ]
    },
    {
      id: 'settings',
      title: t('sidebar.settings'),
      items: [
        { path: '/settings', label: t('sidebar.settings'), iconType: 'settings' as const },
        { path: '/communication', label: t('sidebar.communication'), iconType: 'communication' as const },
        { path: '/im', label: t('sidebar.im') || 'IM 渠道', iconType: 'im' as const },
      ]
    }
  ]
  /* 移动端侧边栏展开状态 */
  const [mobileOpen, setMobileOpen] = useState(false)
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    control: true,
    agent: true,
    appearance: true,
    settings: true,
  })

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

  const toggleMobile = useCallback(() => {
    setMobileOpen((prev) => !prev)
  }, [])

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
      return location.pathname.startsWith('/plugins')
    }
    if (path === '/discussions') {
      // 讨论任务详情页 /discussions/:id 也高亮列表项
      return location.pathname === '/discussions' || location.pathname.startsWith('/discussions/')
    }
    if (path === '/communication') {
      return location.pathname === '/communication'
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
        className={styles['mobile-menu-btn']}
        onClick={toggleMobile}
        title={t('sidebar.menu')}
        aria-label={t('sidebar.menu')}
      >
        <Menu size={22} />
      </button>

      {/* 移动端遮罩层 */}
      {mobileOpen && (
        <div className={styles['mobile-overlay']} onClick={toggleMobile} />
      )}

      <aside className={`${styles['sidebar']} ${collapsed ? styles['collapsed'] : ''} ${mobileOpen ? styles['mobile-open'] : ''}`}>
      <div className={styles['sidebar-header']}>
        {!collapsed && (
          <>
            <div className={styles['logo-container']}>
              {config.logoIcon ? (
                <img src={config.logoIcon} alt="Logo" className={styles['custom-logo-icon']} />
              ) : (
                <img src="/logo.svg" alt="Logo" className={styles['custom-logo-icon']} />
              )}
              <span className={styles['logo-text']}>Open-AwA</span>
            </div>
          </>
        )}
        <button
          className={styles['collapse-btn']}
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
        
        {/* User Floating Area inserted at the bottom of the nav */}
        <div className={styles['nav-bottom-spacer']}></div>
        <UserFloatingArea collapsed={collapsed} />
      </nav>
      
      <div className={styles['sidebar-footer']}>
        <button
          className={styles['theme-toggle-btn']}
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
