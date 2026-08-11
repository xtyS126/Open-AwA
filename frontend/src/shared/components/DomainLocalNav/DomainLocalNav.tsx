import { Link, useLocation } from '@/shared/routing'
import { useBreakpoint } from '@/shared/hooks/useBreakpoint'
import { useI18nStore } from '@/i18n'
import { getActiveChild, getActiveDomain } from '@/shared/navigation/navigationSelectors'
import styles from './DomainLocalNav.module.css'

/**
 * 在移动 Web 中投影当前工作域的二级入口。
 * 路径和选中规则均来自统一导航清单，避免维护第二套路由常量。
 */
export function DomainLocalNav() {
  const location = useLocation()
  const { isMobile } = useBreakpoint()
  const { t } = useI18nStore()
  const activeDomain = getActiveDomain(location.pathname)

  if (!isMobile || !activeDomain) {
    return null
  }

  const activeChild = getActiveChild(activeDomain, location.pathname)

  return (
    <nav
      className={styles.root}
      aria-label={`${t(activeDomain.labelKey)}页面导航`}
    >
      <div className={styles.scroller}>
        {activeDomain.children.map((entry) => {
          const active = entry.id === activeChild?.id
          return (
            <Link
              key={entry.id}
              to={entry.canonicalPath}
              activeOptions={{ exact: true }}
              className={`${styles.link} ${active ? styles.active : ''}`}
              aria-current={active ? 'page' : undefined}
            >
              {t(entry.labelKey)}
            </Link>
          )
        })}
      </div>
    </nav>
  )
}

export default DomainLocalNav
