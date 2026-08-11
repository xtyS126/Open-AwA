import type { ReactNode } from 'react'
import styles from './LibrarySectionShell.module.css'

export interface LibrarySectionTab<TId extends string> {
  id: TId
  label: string
  icon: ReactNode
}

interface LibrarySectionShellProps<TId extends string> {
  eyebrow: string
  title: string
  subtitle: string
  tabs: readonly LibrarySectionTab<TId>[]
  activeTab: TId
  onTabChange: (tab: TId) => void
  children: ReactNode
}

/**
 * 为资源库聚合页提供统一的标题、视图切换和内容承载样式。
 */
export default function LibrarySectionShell<TId extends string>({
  eyebrow,
  title,
  subtitle,
  tabs,
  activeTab,
  onTabChange,
  children,
}: LibrarySectionShellProps<TId>) {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>{eyebrow}</span>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.subtitle}>{subtitle}</p>
      </header>

      <div className={styles.tabs} role="tablist" aria-label={`${title}视图`}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? styles.activeTab : styles.tab}
            onClick={() => onTabChange(tab.id)}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      <section className={styles.content} aria-live="polite">
        {children}
      </section>
    </div>
  )
}
