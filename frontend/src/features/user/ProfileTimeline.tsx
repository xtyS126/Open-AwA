/**
 * 画像提取时间线组件——展示提取日志的摘要。
 */

import type { ExtractionLog } from '@/shared/api/profileApi'
import styles from './ProfileTimeline.module.css'

interface Props {
  logs: ExtractionLog[]
}

function triggerLabel(type: string): string {
  switch (type) {
    case 'auto': return '自动提取'
    case 'manual': return '手动提取'
    case 'scheduled': return '定时任务'
    default: return type
  }
}

function statusIcon(status: string): string {
  switch (status) {
    case 'success': return '●'
    case 'partial': return '◐'
    case 'failed': return '✕'
    case 'skipped': return '○'
    default: return '●'
  }
}

function statusClass(status: string): string {
  switch (status) {
    case 'success': return styles['status-success']
    case 'partial': return styles['status-partial']
    case 'failed': return styles['status-failed']
    case 'skipped': return styles['status-skipped']
    default: return ''
  }
}

function ProfileTimeline({ logs }: Props) {
  return (
    <div className={styles['timeline']}>
      {logs.map((log) => (
        <div key={log.id} className={styles['timeline-item']}>
          <div className={styles['timeline-dot']}>
            <span className={`${styles['dot-icon']} ${statusClass(log.status)}`}>
              {statusIcon(log.status)}
            </span>
          </div>
          <div className={styles['timeline-content']}>
            <div className={styles['timeline-header']}>
              <span className={styles['trigger-type']}>{triggerLabel(log.trigger_type)}</span>
              <span className={styles['timestamp']}>
                {log.created_at ? new Date(log.created_at).toLocaleString('zh-CN') : ''}
              </span>
            </div>
            <div className={styles['timeline-stats']}>
              {log.status === 'failed' ? (
                <span className={styles['error-msg']}>{log.error_message || '提取失败'}</span>
              ) : (
                <span>
                  新增 {log.facts_added} · 更新 {log.facts_updated} · 删除 {log.facts_deleted}
                  {log.extraction_duration_ms ? ` · ${(log.extraction_duration_ms / 1000).toFixed(1)}s` : ''}
                </span>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default ProfileTimeline
