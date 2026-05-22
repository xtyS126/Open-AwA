import type { ToolEventMeta } from '@/features/chat/types'
import { ToolParamViewer } from './ToolParamViewer'
import styles from './InlineToolCallCard.module.css'
import { useState } from 'react'
import { Undo2 } from 'lucide-react'

interface InlineToolCallCardProps {
  tool: ToolEventMeta
  onUndo?: (operationId: string) => Promise<void>
}

function getStatusLabel(status: string): string {
  switch (status) {
    case 'completed': return '已完成'
    case 'running': return '执行中'
    case 'error': return '失败'
    default: return '等待中'
  }
}

export function InlineToolCallCard({ tool, onUndo }: InlineToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [undoState, setUndoState] = useState<'idle' | 'undoing' | 'undone'>('idle')
  const isRunning = tool.status === 'running'

  const canUndo = tool.status === 'completed'
    && ['write_file', 'delete_file', 'terminal_executor'].some(n => tool.name?.includes(n))
    && typeof (tool.output as Record<string, unknown> | undefined)?.operation_id === 'string'

  const handleUndoClick = async () => {
    if (!canUndo || !onUndo || undoState !== 'idle') return
    setUndoState('undoing')
    try {
      await onUndo(String((tool.output as Record<string, unknown>).operation_id))
      setUndoState('undone')
    } catch {
      setUndoState('idle')
    }
  }

  return (
    <div className={styles.inlineContainer}>
      <div 
        className={`${styles.inlineBadge} ${styles['status-' + tool.status]}`}
        onClick={() => setExpanded(!expanded)}
        title={`${tool.kind}: ${tool.name}`}
      >
        <span className={`${styles.statusText} ${isRunning ? styles.spin : ''}`}>{getStatusLabel(tool.status)}</span>
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
          {undoState === 'undone' ? (
            <span className={styles.undoneLabel}>✓ 已撤销</span>
          ) : canUndo && onUndo ? (
            <button
              className={styles.undoBtn}
              onClick={handleUndoClick}
              disabled={undoState === 'undoing'}
              title="撤销此操作（5分钟内有效）"
            >
              <Undo2 size={14} />
              <span>撤销</span>
            </button>
          ) : null}
        </div>
      )}
    </div>
  )
}

export default InlineToolCallCard
