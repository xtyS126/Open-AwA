import type { ToolEventMeta } from '@/features/chat/types'
import { ToolParamViewer } from './ToolParamViewer'
import styles from './InlineToolCallCard.module.css'

interface InlineToolCallCardProps {
  tool: ToolEventMeta
  isLast: boolean
}

function getStatusLabel(status: string): string {
  switch (status) {
    case 'completed':
      return '已完成'
    case 'running':
      return '执行中'
    case 'error':
      return '失败'
    default:
      return '等待中'
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}

export function InlineToolCallCard({ tool, isLast }: InlineToolCallCardProps) {
  const duration =
    tool.startedAt && tool.completedAt
      ? tool.completedAt - tool.startedAt
      : undefined

  return (
    <div className={styles['card-wrapper']}>
      {/* 时间线连接线 */}
      <div className={styles['timeline-connector']}>
        <div className={styles['timeline-line']} />
        <div className={`${styles['timeline-dot']} ${styles[`dot-${tool.status}`]}`}>
          {tool.status === 'completed' && (
            <span className={styles['check-mark']}>✓</span>
          )}
          {tool.status === 'error' && (
            <span className={styles['error-mark']}>✕</span>
          )}
        </div>
        {!isLast && <div className={styles['timeline-line-bottom']} />}
      </div>

      {/* 卡片主体 */}
      <div className={`${styles['card']} ${styles[`card-${tool.status}`]}`}>
        {/* 卡片头部 */}
        <div className={styles['card-header']}>
          <div className={styles['card-header-left']}>
            <span className={styles['kind-badge']}>{tool.kind}</span>
            <span className={styles['tool-name']}>{tool.name}</span>
          </div>
          <div className={styles['card-header-right']}>
            {duration !== undefined && (
              <span className={styles['duration']}>{formatDuration(duration)}</span>
            )}
            <span className={`${styles['status-badge']} ${styles[`status-${tool.status}`]}`}>
              {getStatusLabel(tool.status)}
            </span>
          </div>
        </div>

        {/* 错误信息 */}
        {tool.status === 'error' && tool.detail && (
          <div className={styles['error-detail']}>{tool.detail}</div>
        )}

        {/* 输入参数 */}
        {tool.input && Object.keys(tool.input).length > 0 && (
          <ToolParamViewer
            data={tool.input}
            label="输入参数"
          />
        )}

        {/* 输出结果 */}
        {tool.output !== undefined && tool.output !== null && (
          <ToolParamViewer
            data={tool.output}
            label="执行结果"
          />
        )}
      </div>
    </div>
  )
}

export default InlineToolCallCard
