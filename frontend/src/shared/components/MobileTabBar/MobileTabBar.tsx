import { useCallback } from 'react'
import { Link, useLocation } from '@/shared/routing'
import { MessageSquare, Brain, Zap, Settings, LayoutGrid } from 'lucide-react'
import { useBreakpoint } from '@/shared/hooks/useBreakpoint'
import { useI18nStore } from '@/i18n'
import { useMobileNavStore } from '@/shared/store/mobileNavStore'
import styles from './MobileTabBar.module.css'

/**
 * 底部 Tab Bar —— 移动端（≤768px）原生 APP 导航范式。
 *
 * 结构：聊天 / 记忆 / 技能 / 设置 四个直达 Tab + "更多"打开完整抽屉（Sidebar），
 * 保证所有网页端功能入口在 APP 上均可到达。
 * 桌面端不渲染（useBreakpoint isMobile 守卫），避免与侧边栏重复导航。
 */
const TAB_ITEMS = [
  { path: '/chat', labelKey: 'sidebar.chat', icon: MessageSquare },
  { path: '/memory', labelKey: 'sidebar.memory', icon: Brain },
  { path: '/skills', labelKey: 'sidebar.skills', icon: Zap },
  { path: '/settings', labelKey: 'sidebar.settings', icon: Settings },
] as const

export function MobileTabBar() {
  const location = useLocation()
  const { isMobile } = useBreakpoint()
  const { t } = useI18nStore()
  const openDrawer = useMobileNavStore((s) => s.openDrawer)

  /* 激活态判定：/chat 前缀匹配（含 /chat/:id），其余精确匹配 */
  const isActive = useCallback(
    (path: string): boolean => {
      if (path === '/chat') {
        return location.pathname === '/chat' || location.pathname.startsWith('/chat/')
      }
      return location.pathname === path
    },
    [location.pathname],
  )

  /* 移动端外不渲染：避免桌面端出现重复导航入口 */
  if (!isMobile) {
    return null
  }

  return (
    <nav className={styles['tab-bar']} role="navigation" aria-label="底部主导航">
      <div className={styles['tab-bar-inner']}>
        {TAB_ITEMS.map(({ path, labelKey, icon: Icon }) => {
          const active = isActive(path)
          return (
            <Link
              key={path}
              to={path}
              className={`${styles['tab-item']} ${active ? styles['tab-item-active'] : ''}`}
              data-testid={`tab-${path.replace('/', '')}`}
              aria-current={active ? 'page' : undefined}
            >
              <span className={styles['tab-icon-wrap']}>
                <Icon size={22} strokeWidth={active ? 2.2 : 1.8} />
                {active && <span className={styles['tab-signal-dot']} aria-hidden="true" />}
              </span>
              <span className={styles['tab-label']}>{t(labelKey)}</span>
            </Link>
          )
        })}
        {/* 更多：打开完整抽屉（含全部网页端功能入口） */}
        <button
          type="button"
          className={styles['tab-item']}
          data-testid="tab-more"
          aria-label={t('mobileTab.more')}
          onClick={openDrawer}
        >
          <span className={styles['tab-icon-wrap']}>
            <LayoutGrid size={22} strokeWidth={1.8} />
          </span>
          <span className={styles['tab-label']}>{t('mobileTab.more')}</span>
        </button>
      </div>
    </nav>
  )
}

export default MobileTabBar
