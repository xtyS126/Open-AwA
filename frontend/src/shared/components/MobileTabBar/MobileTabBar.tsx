import { Link, useLocation } from '@/shared/routing'
import { useBreakpoint } from '@/shared/hooks/useBreakpoint'
import { useI18nStore } from '@/i18n'
import { navigationManifest } from '@/shared/navigation/navigationManifest'
import { getActiveDomain } from '@/shared/navigation/navigationSelectors'
import { renderNavigationIcon } from '@/shared/navigation/navigationIcons'
import { getDomainEntryPath, useDomainEntryPaths } from '@/shared/navigation/domainHistory'
import styles from './MobileTabBar.module.css'

/**
 * 移动 Web 从统一清单投影五个工作域。
 * 二级视图由页面内导航承载，不再打开包含全部页面的完整抽屉。
 */
export function MobileTabBar() {
  const location = useLocation()
  const { isMobile } = useBreakpoint()
  const { t } = useI18nStore()
  const activeDomain = getActiveDomain(location.pathname)
  const domainEntryPaths = useDomainEntryPaths(location)

  if (!isMobile) {
    return null
  }

  return (
    <nav className={styles['tab-bar']} aria-label="底部主导航">
      <div className={styles['tab-bar-inner']}>
        {navigationManifest.domains.map((domain) => {
          const active = domain.id === activeDomain?.id
          return (
            <Link
              key={domain.id}
              to={getDomainEntryPath(domain, domainEntryPaths)}
              className={`${styles['tab-item']} ${active ? styles['tab-item-active'] : ''}`}
              data-testid={`tab-${domain.id}`}
              aria-current={active ? 'page' : undefined}
            >
              <span className={styles['tab-icon-wrap']}>
                {renderNavigationIcon(domain.iconKey, 21)}
              </span>
              <span className={styles['tab-label']}>{t(domain.labelKey)}</span>
            </Link>
          )
        })}
      </div>
    </nav>
  )
}

export default MobileTabBar
