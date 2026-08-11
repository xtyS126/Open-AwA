import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, MessageSquareWarning, Moon, Sun } from 'lucide-react'
import { Link, useLocation } from '@/shared/routing'
import { useThemeStore } from '@/shared/store/themeStore'
import { useI18nStore } from '@/i18n'
import { useIssueFeedbackStore } from '@/shared/store/issueFeedbackStore'
import { useBreakpoint } from '@/shared/hooks/useBreakpoint'
import { useMediaQuery } from '@/shared/hooks/useMediaQuery'
import { BrandMark } from '@/shared/components/BrandMark/BrandMark'
import { navigationManifest } from '@/shared/navigation/navigationManifest'
import { getActiveChild, getActiveDomain } from '@/shared/navigation/navigationSelectors'
import { renderNavigationIcon } from '@/shared/navigation/navigationIcons'
import { getDomainEntryPath, useDomainEntryPaths } from '@/shared/navigation/domainHistory'
import styles from './Sidebar.module.css'

const SIDEBAR_COLLAPSED_STORAGE_KEY = 'openawa.sidebar.subnav-collapsed'

function readDesktopCollapsePreference(): boolean {
  return typeof window !== 'undefined'
    && window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === 'true'
}

export function Sidebar() {
  const location = useLocation()
  const { theme, toggleTheme, config } = useThemeStore()
  const { t } = useI18nStore()
  const { isTablet } = useBreakpoint()
  const isCollapsibleDesktop = useMediaQuery('(min-width: 1024px) and (max-width: 1439.98px)')
  const isWideDesktop = useMediaQuery('(min-width: 1440px)')
  const [collapsed, setCollapsed] = useState(() => (
    isTablet || (isCollapsibleDesktop && readDesktopCollapsePreference())
  ))
  const matchedDomain = getActiveDomain(location.pathname)
  const activeDomain = matchedDomain ?? navigationManifest.domains[0]
  const activeChild = matchedDomain ? getActiveChild(matchedDomain, location.pathname) : undefined
  const effectiveCollapsed = collapsed || !matchedDomain
  const domainEntryPaths = useDomainEntryPaths(location)
  const collapseLabel = collapsed ? '展开子导航' : '收起子导航'

  useEffect(() => {
    if (isTablet) {
      setCollapsed(true)
    } else if (isCollapsibleDesktop) {
      setCollapsed(readDesktopCollapsePreference())
    } else if (isWideDesktop) {
      setCollapsed(false)
    } else {
      setCollapsed(false)
    }
  }, [isCollapsibleDesktop, isTablet, isWideDesktop])

  const updateCollapsed = (nextCollapsed: boolean) => {
    setCollapsed(nextCollapsed)
    if (isCollapsibleDesktop) {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(nextCollapsed))
    }
  }

  return (
    <aside
      className={`${styles['sidebar']} ${effectiveCollapsed ? styles['collapsed'] : ''} ${isTablet ? styles['tablet'] : ''}`}
      data-testid="sidebar"
      data-collapsed={effectiveCollapsed}
      data-layout={isTablet ? 'temporary' : isWideDesktop ? 'wide' : 'collapsible'}
    >
      <div className={styles['domain-rail']}>
        <Link className={styles['brand-link']} to="/assistant" aria-label="Open-AwA">
          {config.logoIcon ? (
            <img src={config.logoIcon} alt="" className={styles['custom-brand']} />
          ) : (
            <BrandMark size={38} decorative />
          )}
        </Link>

        <nav className={styles['domain-nav']} aria-label="工作域">
          {navigationManifest.domains.map((domain) => {
            const active = domain.id === matchedDomain?.id
            return (
              <Link
                key={domain.id}
                to={getDomainEntryPath(domain, domainEntryPaths)}
                className={`${styles['domain-link']} ${active ? styles['active'] : ''}`}
                aria-current={active ? 'page' : undefined}
              >
                <span className={styles['domain-icon']}>
                  {renderNavigationIcon(domain.iconKey, 20)}
                </span>
                <span>{t(domain.labelKey)}</span>
              </Link>
            )
          })}
        </nav>

        {collapsed && matchedDomain && (
          <button
            type="button"
            className={styles['expand-button']}
            aria-label={collapseLabel}
            onClick={() => updateCollapsed(false)}
          >
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        )}

        <div className={styles['rail-spacer']} />
        <button
          type="button"
          className={styles['rail-action']}
          aria-label={t('sidebar.issueFeedback') || '问题反馈'}
          onClick={() => useIssueFeedbackStore.getState().open()}
        >
          <MessageSquareWarning size={19} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={styles['rail-action']}
          aria-label={`${t('sidebar.theme')}: ${theme === 'light' ? t('sidebar.darkMode') : t('sidebar.lightMode')}`}
          onClick={toggleTheme}
        >
          {theme === 'light'
            ? <Moon size={19} aria-hidden="true" />
            : <Sun size={19} aria-hidden="true" />}
        </button>
      </div>

      {!effectiveCollapsed && matchedDomain && (
        <section className={styles['subnav-panel']}>
          <header className={styles['subnav-header']}>
            <div>
              <span className={styles['subnav-kicker']}>Open-AwA</span>
              <h2>{t(activeDomain.labelKey)}</h2>
            </div>
            <button
              type="button"
              className={styles['collapse-button']}
              aria-label={collapseLabel}
              onClick={() => updateCollapsed(true)}
            >
              <ChevronLeft size={18} aria-hidden="true" />
            </button>
          </header>

          <nav className={styles['subnav']} aria-label={`${t(activeDomain.labelKey)}子导航`}>
            {activeDomain.children.map((entry) => {
              const active = entry.id === activeChild?.id
              return (
                <Link
                  key={entry.id}
                  to={entry.canonicalPath}
                  className={`${styles['subnav-link']} ${active ? styles['active'] : ''}`}
                  aria-current={active ? 'page' : undefined}
                  onClick={() => {
                    if (isTablet) setCollapsed(true)
                  }}
                >
                  <span className={styles['subnav-indicator']} aria-hidden="true" />
                  <span>{t(entry.labelKey)}</span>
                </Link>
              )
            })}
          </nav>

          <div className={styles['subnav-note']}>
            <span>{String(navigationManifest.version).padStart(2, '0')}</span>
            <p>任务优先的统一导航</p>
          </div>
        </section>
      )}

    </aside>
  )
}

export default Sidebar
