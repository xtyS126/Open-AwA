import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { ParsedSubagentLogs } from './ParsedSubagentLogs'
import styles from './SubagentExecutionContainer.module.css'

export interface SubagentExecutionProps {
  id: string
  name: string
  status: 'running' | 'completed' | 'error'
  logs: string
  statusLabel?: string
  truncated?: boolean
  /** 嵌套深度，用于缩进和左侧竖线颜色 */
  depth?: number
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

/** 根据状态返回左侧深度线的样式类名 */
function getDepthLineClass(status: SubagentExecutionProps['status']): string {
  switch (status) {
    case 'running':
      return styles.depthLineRunning
    case 'completed':
      return styles.depthLineCompleted
    case 'error':
      return styles.depthLineError
    default:
      return styles.depthLineRunning
  }
}

export function SubagentExecutionContainer({
  id,
  name,
  status,
  logs,
  statusLabel,
  truncated = false,
  depth = 0,
}: SubagentExecutionProps) {
  const [expanded, setExpanded] = useState(status === 'running')
  const statusClass = styles[`status-${status}`]
  const resolvedStatusLabel = getStatusLabel(status, statusLabel)

  // 深度缩进：每层 20px
  const depthPadding = depth * 20

  return (
    <div
      className={styles.container}
      data-testid={`subagent-container-${id}`}
      style={{ paddingLeft: depthPadding > 0 ? `${depthPadding}px` : undefined }}
    >
      {/* 左侧深度竖线 */}
      {depth > 0 && (
        <div className={`${styles.depthLine} ${getDepthLineClass(status)}`} />
      )}

      <div
        className={`${styles.header} ${expanded ? styles.headerExpanded : ''}`}
        onClick={() => setExpanded(!expanded)}
      >
        <div className={styles.titleBlock}>
          <ChevronRight
            className={`${styles.chevron} ${expanded ? styles.chevronExpanded : ''}`}
            size={14}
          />
          <div className={styles.title}>{name}</div>
          {truncated && <div className={styles.notice}>日志过长，已截断</div>}
        </div>
        <div className={styles.statusMeta}>
          <span className={styles.statusText}>{resolvedStatusLabel}</span>
          <div className={`${styles.statusLight} ${statusClass}`} title={status} />
        </div>
      </div>

      <div className={`${styles.content} ${expanded ? styles.contentExpanded : styles.contentCollapsed}`}>
        <ParsedSubagentLogs logs={logs} />
      </div>
    </div>
  )
}
