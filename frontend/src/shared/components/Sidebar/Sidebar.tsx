import { useState, useEffect, useCallback } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useThemeStore } from '../../store/themeStore'
import styles from './Sidebar.module.css'

interface MenuItem {
  path: string
  label: string
  iconType: 'chat' | 'dashboard' | 'billing' | 'skills' | 'plugins' | 'memory' | 'settings' | 'experience' | 'communication'
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

const icons = {
  chat: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  ),
  dashboard: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="7" height="9" />
      <rect x="14" y="3" width="7" height="5" />
      <rect x="14" y="12" width="7" height="9" />
      <rect x="3" y="16" width="7" height="5" />
    </svg>
  ),
  billing: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="12" y1="20" x2="12" y2="10" />
      <line x1="18" y1="20" x2="18" y2="4" />
      <line x1="6" y1="20" x2="6" y2="16" />
    </svg>
  ),
  skills: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  ),
  plugins: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2v6m0 12v2M4.93 4.93l4.24 4.24m5.66 5.66l4.24 4.24M2 12h6m12 0h2M4.93 19.07l4.24-4.24m5.66-5.66l4.24-4.24" />
    </svg>
  ),
  memory: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2a9 9 0 0 0-9 9c0 3.6 3.4 6.2 5.5 8.5 1 1.1 1.5 2.4 1.5 3.5v2a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1v-2c0-1.1.5-2.4 1.5-3.5 2.1-2.3 5.5-4.9 5.5-8.5a9 9 0 0 0-9-9z" />
    </svg>
  ),
  settings: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ),
  experience: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
    </svg>
  ),
  communication: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>
    </svg>
  ),
  claw: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 4l4 4M4 4v4h4" />
      <path d="M20 4l-4 4M20 4v4h-4" />
      <path d="M4 20l4-4M4 20v-4h4" />
      <path d="M20 20l-4-4M20 20v-4h-4" />
      <circle cx="12" cy="12" r="4" />
    </svg>
  ),
  sun: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  ),
  moon: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
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
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
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
              <span className={styles['logo-icon']}>{icons.claw}</span>
              <span className={styles['logo-text']}>Open-AwA</span>
            </div>
          </>
        )}
        <button 
          className={styles['collapse-btn']} 
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? '展开' : '收起'}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
      </div>
      
      <nav className={styles['sidebar-nav']}>
        {menuGroups.map((group) => (
          <div key={group.id} className={styles['menu-group']}>
            <div 
              className={styles['group-header']}
              onClick={() => toggleGroup(group.id)}
            >
              {!collapsed && (
                <>
                  <span className={styles['group-title']}>{group.title}</span>
                  <svg 
                    className={`${styles['chevron']} ${expandedGroups[group.id] ? styles['expanded'] : ''}`}
                    width="16" 
                    height="16" 
                    viewBox="0 0 24 24" 
                    fill="none" 
                    stroke="currentColor" 
                    strokeWidth="2"
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </>
              )}
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
                    <span className={styles['sidebar-icon']}>{icons[item.iconType]}</span>
                    {!collapsed && <span className={styles['sidebar-label']}>{item.label}</span>}
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
          {theme === 'light' ? icons.moon : icons.sun}
          {!collapsed && <span className={styles['theme-label']}>{theme === 'light' ? '黑夜模式' : '白天模式'}</span>}
        </button>
        {!collapsed && <p className={styles['version-text']}>v1.0.0</p>}
      </div>
    </aside>
    </>
  )
}

export default Sidebar
