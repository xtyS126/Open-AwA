/**
 * EmptyState 空状态组件 — 统一空数据占位展示。
 * 支持图标、标题、说明文字和操作按钮。
 */
import { type ReactNode } from 'react'
import { Inbox } from 'lucide-react'
import { Button } from '../Button'
import styles from './EmptyState.module.css'

interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: string
  actionLabel?: string
  onAction?: () => void
}

function EmptyState({ icon, title, description, actionLabel, onAction }: EmptyStateProps) {
  return (
    <div className={styles.empty}>
      <div className={styles.icon}>{icon || <Inbox size={48} strokeWidth={1.5} />}</div>
      <h3 className={styles.title}>{title}</h3>
      {description && <p className={styles.description}>{description}</p>}
      {actionLabel && onAction && (
        <Button variant="outline" size="sm" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  )
}

export { EmptyState }
export type { EmptyStateProps }
