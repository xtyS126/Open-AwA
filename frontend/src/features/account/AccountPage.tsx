import { useCallback, useEffect, useMemo } from 'react'
import UserCenterPage, { type UserCenterSection } from '@/features/user/UserCenterPage'
import { useLocation, useNavigate } from '@/shared/routing'
import styles from './AccountPage.module.css'

export type AccountSection = 'personal' | 'overview' | 'facts' | 'profile'

function isAccountSection(value: string | null): value is AccountSection {
  return value === 'personal' || value === 'overview' || value === 'facts' || value === 'profile'
}

function toUserCenterSection(section: AccountSection): UserCenterSection {
  return section === 'profile' ? 'soul' : section
}

function toAccountSection(section: UserCenterSection): AccountSection {
  return section === 'soul' ? 'profile' : section
}

/**
 * 账户规范入口，统一承载个人信息、设备、画像和事实管理。
 */
export default function AccountPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const params = useMemo(() => new URLSearchParams(location.search), [location.search])
  const rawSection = params.get('section')
  const section: AccountSection = isAccountSection(rawSection) ? rawSection : 'personal'

  useEffect(() => {
    if (
      location.pathname === '/account'
      && rawSection !== null
      && !isAccountSection(rawSection)
    ) {
      void navigate('/account', { replace: true })
    }
  }, [location.pathname, navigate, rawSection])

  const handleSectionChange = useCallback((nextSection: UserCenterSection) => {
    const normalized = toAccountSection(nextSection)
    const target = normalized === 'personal' ? '/account' : `/account?section=${normalized}`
    void navigate(target)
  }, [navigate])

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>全局上下文</span>
        <h1 className={styles.title}>账户</h1>
        <p className={styles.subtitle}>管理个人信息、登录设备以及由对话逐步形成的用户画像。</p>
      </header>
      <section className={styles.content}>
        <UserCenterPage
          activeSection={toUserCenterSection(section)}
          hideHeader
          onSectionChange={handleSectionChange}
        />
      </section>
    </div>
  )
}
