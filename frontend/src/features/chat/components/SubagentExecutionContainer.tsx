import { useEffect, useMemo, useRef } from 'react'
import Convert from 'ansi-to-html'
import styles from './SubagentExecutionContainer.module.css'

const convert = new Convert({
  newline: true,
  escapeXML: true,
})

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
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  const statusClass = styles[`status-${status}`]
  const parsedLogs = useMemo(() => convert.toHtml(logs), [logs])
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
      <div className={styles.content} ref={scrollRef}>
        <pre dangerouslySetInnerHTML={{ __html: parsedLogs }} />
      </div>
    </div>
  )
}
