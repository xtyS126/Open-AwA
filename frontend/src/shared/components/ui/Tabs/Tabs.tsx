/**
 * Tabs 标签页组件 — 统一的选项卡切换容器。
 */
import { type ReactNode } from 'react'
import styles from './Tabs.module.css'

interface TabItem {
  key: string
  label: ReactNode
  content: ReactNode
}

interface TabsProps {
  tabs: TabItem[]
  activeKey: string
  onChange: (key: string) => void
}

function Tabs({ tabs, activeKey, onChange }: TabsProps) {
  const activeTab = tabs.find((t) => t.key === activeKey)

  return (
    <div className={styles.tabs}>
      <div className={styles.tabList} role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`${styles.tab} ${activeKey === tab.key ? styles.active : ''}`}
            onClick={() => onChange(tab.key)}
            role="tab"
            aria-selected={activeKey === tab.key}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className={styles.tabPanel} role="tabpanel">
        {activeTab?.content}
      </div>
    </div>
  )
}

export { Tabs }
export type { TabsProps, TabItem }
