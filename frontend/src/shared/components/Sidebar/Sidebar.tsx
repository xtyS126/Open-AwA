import { useState, useEffect, useCallback } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { 
  MessageSquare, LayoutDashboard, CreditCard, Zap, 
  Clock, Blocks, Brain, Settings, Award, Radio, 
  Cat, Sun, Moon, Menu, ChevronDown
} from 'lucide-react'
import { useThemeStore } from '../../store/themeStore'
import styles from './Sidebar.module.css'

interface MenuItem {
  path: string
  label: string
  iconType: 'chat' | 'dashboard' | 'billing' | 'skills' | 'scheduledTasks' | 'plugins' | 'memory' | 'settings' | 'experience' | 'communication'
}

interface MenuGroup {
  id: string
  title: string
  items: MenuItem[]
}

const menuGroups: MenuGroup[] = [
  {
    id: 'control',
    title: '控制',
    items: [
      { path: '/chat', label: '聊天', iconType: 'chat' },
      { path: '/dashboard', label: '概览', iconType: 'dashboard' },
      { path: '/billing', label: '使用情况', iconType: 'billing' },
    ]
  },
  {
    id: 'agent',
    title: '代理',
    items: [
      { path: '/skills', label: '技能', iconType: 'skills' },
      { path: '/scheduled-tasks', label: '定时任务', iconType: 'scheduledTasks' },
      { path: '/plugins', label: '插件', iconType: 'plugins' },
      { path: '/memory', label: '记忆', iconType: 'memory' },
      { path: '/experience', label: '经验', iconType: 'experience' },
    ]
  },
  {
    id: 'settings',
    title: '设置',
    items: [
      { path: '/settings', label: '设置', iconType: 'settings' },
      { path: '/communication', label: '通讯配置', iconType: 'communication' },
    ]
  }
]

const renderIcon = (type: string, size = 18) => {
  switch (type) {
    case 'chat': return <MessageSquare size={size} />
    case 'dashboard': return <LayoutDashboard size={size} />
    case 'billing': return <CreditCard size={size} />
    case 'skills': return <Zap size={size} />
    case 'scheduledTasks': return <Clock size={size} />
    case 'plugins': return <Blocks size={size} />
    case 'memory': return <Brain size={size} />
    case 'settings': return <Settings size={size} />
    case 'experience': return <Award size={size} />
    case 'communication': return <Radio size={size} />
    default: return <MessageSquare size={size} />
  }
}

  function Sidebar() {
  const location = useLocation()
  const { theme, toggleTheme } = useThemeStore()
  const [collapsed, setCollapsed] = useState(false)
  /* 移动端侧边栏展开状态 */
  const [mobileOpen, setMobileOpen] = useState(false)
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    control: true,
    agent: true,
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
    if (path === '/plugins') {
      return location.pathname.startsWith('/plugins')
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
        title="菜单"
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
              <span className={styles['logo-icon']}><Cat size={24} /></span>
              <span className={styles['logo-text']}>Open-AwA</span>
            </div>
          </>
        )}
        <button 
          className={styles['collapse-btn']} 
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? '展开' : '收起'}
        >
          <Menu size={20} />
        </button>
      </div>
      
      <nav className={styles['sidebar-nav']}>
        {menuGroups.map((group, groupIndex) => (
          <div key={group.id} className={styles['menu-group']}>
            {/* 分组之间的分隔线（第一个分组前不显示） */}
            {groupIndex > 0 && !collapsed && <div className={styles['group-divider']} />}
            <div 
              className={styles['group-header']}
              onClick={() => toggleGroup(group.id)}
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
                {group.items.map((item) => (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={`${styles['sidebar-item']} ${isActive(item.path) ? styles['active'] : ''}`}
                    title={collapsed ? item.label : undefined}
                  >
                    <span className={styles['sidebar-icon']}>{renderIcon(item.iconType, 18)}</span>
                    {!collapsed && <span className={styles['sidebar-label']}>{item.label}</span>}
                    {collapsed && <span className={styles['tooltip']}>{item.label}</span>}
                  </Link>
                ))}
              </div>
            )}
          </div>
        ))}
      </nav>
      
      <div className={styles['sidebar-footer']}>
        <button 
          className={styles['theme-toggle-btn']} 
          onClick={toggleTheme}
          title={theme === 'light' ? '切换到黑夜模式' : '切换到白天模式'}
        >
          {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
          {!collapsed && <span className={styles['theme-label']}>{theme === 'light' ? '黑夜模式' : '白天模式'}</span>}
        </button>
        {!collapsed && <p className={styles['version-text']}>v1.0.0</p>}
      </div>
    </aside>
    </>
  )
}

export default Sidebar
