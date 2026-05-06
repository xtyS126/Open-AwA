import { MessageContent } from './MessageContent'
import styles from './SubagentExecutionContainer.module.css'

export interface SubagentExecutionProps {
  id: string
  name: string
  status: 'running' | 'completed' | 'error'
  logs: string
  statusLabel?: string
  truncated?: boolean
}

function getStatusLabel(status: SubagentExecutionProps['status'], statusLabel?: string): string {
  if (statusLabel) {
    return statusLabel
  }

  switch (status) {
    case 'completed':
      return '已完成'
    case 'error':
      return '异常'
    default:
      return '运行中'
  }
}

export function SubagentExecutionContainer({
  id,
  name,
  status,
  logs,
  statusLabel,
  truncated = false,
}: SubagentExecutionProps) {
  const statusClass = styles[`status-${status}`]
  const resolvedStatusLabel = getStatusLabel(status, statusLabel)

  return (
    <div className={styles.container} data-testid={`subagent-container-${id}`}>
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <div className={styles.title}>{name}</div>
          {truncated && <div className={styles.notice}>日志过长，已截断</div>}
        </div>
        <div className={styles.statusMeta}>
          <span className={styles.statusText}>{resolvedStatusLabel}</span>
          <div className={`${styles.statusLight} ${statusClass}`} title={status} />
        </div>
      </div>
      <div className={styles.content}>
        <MessageContent content={logs} role="assistant" />
      </div>
    </div>
  )
}
