import { useMemo } from 'react'
import { CheckCircle2, Circle, Loader2, ListTodo } from 'lucide-react'
import styles from './TodoPanel.module.css'

export interface TodoItem {
  id: string
  content: string
  status: 'pending' | 'in_progress' | 'completed'
}

interface TodoPanelProps {
  items: TodoItem[]
  summary?: string
}

export function TodoPanel({ items, summary }: TodoPanelProps) {
  if (items.length === 0) return null

  const pendingItems = useMemo(() => items.filter(i => i.status === 'pending'), [items])
  const inProgressItems = useMemo(() => items.filter(i => i.status === 'in_progress'), [items])
  const completedItems = useMemo(() => items.filter(i => i.status === 'completed'), [items])

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <ListTodo size={16} />
        <span className={styles.title}>任务清单</span>
        {summary && <span className={styles.summary}>{summary}</span>}
      </div>

      {inProgressItems.length > 0 && (
        <div className={styles.section}>
          {inProgressItems.map(item => (
            <div key={item.id} className={styles.item}>
              <Loader2 size={14} className={styles['icon-running']} />
              <span className={styles['item-text']}>{item.content}</span>
            </div>
          ))}
        </div>
      )}

      {pendingItems.length > 0 && (
        <div className={styles.section}>
          {pendingItems.map(item => (
            <div key={item.id} className={styles.item}>
              <Circle size={14} className={styles['icon-pending']} />
              <span className={styles['item-text']}>{item.content}</span>
            </div>
          ))}
        </div>
      )}

      {completedItems.length > 0 && (
        <div className={styles.section}>
          {completedItems.map(item => (
            <div key={item.id} className={styles['item-completed']}>
              <CheckCircle2 size={14} className={styles['icon-completed']} />
              <span className={styles['item-text-completed']}>{item.content}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
