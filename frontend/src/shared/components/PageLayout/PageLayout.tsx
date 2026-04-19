import { ReactNode } from 'react'
import styles from './PageLayout.module.css'

export interface PageLayoutProps {
  title?: string
  actions?: ReactNode
  secondarySidebar?: ReactNode
  children: ReactNode
  className?: string
}

export default function PageLayout({
  title,
  actions,
  secondarySidebar,
  children,
  className = ''
}: PageLayoutProps) {
  return (
    <div className={`${styles['page-layout']} ${className}`}>
      {secondarySidebar && (
        <aside className={styles['secondary-sidebar']}>
          {secondarySidebar}
        </aside>
      )}
      <main className={styles['main-content']}>
        {(title || actions) && (
          <header className={styles['page-header']}>
            {title && <h1 className={styles['page-title']}>{title}</h1>}
            {actions && <div className={styles['page-actions']}>{actions}</div>}
          </header>
        )}
        <div className={styles['page-body']}>
          {children}
        </div>
      </main>
    </div>
  )
}
