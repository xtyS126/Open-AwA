import type { ToolEventMeta } from '@/features/chat/types'
import { ToolParamViewer } from './ToolParamViewer'
import { useI18nStore, t as i18nT } from '@/i18n'
import styles from './InlineToolCallCard.module.css'
import { useState } from 'react'
import { Undo2 } from 'lucide-react'

interface InlineToolCallCardProps {
  tool: ToolEventMeta
  onUndo?: (operationId: string) => Promise<void>
}

function getStatusLabel(status: string): string {
  switch (status) {
    case 'completed': return i18nT('chat.tool.completed')
    case 'running': return i18nT('chat.tool.running')
    case 'error': return i18nT('chat.tool.failed')
    default: return i18nT('chat.tool.waiting')
  }
}

export function InlineToolCallCard({ tool, onUndo }: InlineToolCallCardProps) {
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const t = useI18nStore(s => s.t)
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
             <ToolParamViewer data={tool.input} label={t('chat.tool.inputParams')} />
          )}
          {tool.output !== undefined && tool.output !== null && (
             <ToolParamViewer data={tool.output} label={t('chat.tool.result')} />
          )}
          {undoState === 'undone' ? (
            <span className={styles.undoneLabel}>✓ {t('chat.tool.undone')}</span>
          ) : canUndo && onUndo ? (
            <button
              className={styles.undoBtn}
              onClick={handleUndoClick}
              disabled={undoState === 'undoing'}
              title={t('chat.tool.undoAction')}
            >
              <Undo2 size={14} />
              <span>{t('chat.tool.undo')}</span>
            </button>
          ) : null}
        </div>
      )}
    </div>
  )
}

export default InlineToolCallCard
