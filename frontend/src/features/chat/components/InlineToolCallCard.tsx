import type { ToolEventMeta } from '@/features/chat/types'
import { ToolParamViewer } from './ToolParamViewer'
import styles from './InlineToolCallCard.module.css'
import { useState } from 'react'

interface InlineToolCallCardProps {
  tool: ToolEventMeta
  isLast: boolean
}

function getStatusIcon(status: string): string {
  switch (status) {
    case 'completed': return '✅'
    case 'running': return '🔄'
    case 'error': return '❌'
    default: return '⏳'
  }
}

export function InlineToolCallCard({ tool }: InlineToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)
  const isRunning = tool.status === 'running'
  return (
    <div className={styles.inlineContainer}>
      <div 
        className={`${styles.inlineBadge} ${styles['status-' + tool.status]}`}
        onClick={() => setExpanded(!expanded)}
        title={`${tool.kind}: ${tool.name}`}
      >
        <span className={isRunning ? styles.spin : ''}>{getStatusIcon(tool.status)}</span>
        <span className={styles.inlineText}>{tool.name}</span>
      </div>
      {expanded && (
        <div className={styles.expandedDetails}>
          {tool.status === 'error' && tool.detail && (
            <div className={styles.errorText}>{tool.detail}</div>
          )}
          {tool.input && Object.keys(tool.input).length > 0 && (
             <ToolParamViewer data={tool.input} label="输入参数" />
          )}
          {tool.output !== undefined && tool.output !== null && (
             <ToolParamViewer data={tool.output} label="执行结果" />
          )}
        </div>
      )}
    </div>
  )
}

export default InlineToolCallCard
