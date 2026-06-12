/**
 * 最近记录预览组件
 */
import { useEffect } from 'react'
import type { ConversationRecordItem } from '@/shared/api/api'
import styles from '@/features/settings/SettingsPage.module.css'

interface RecordsPreviewProps {
  /** 预览记录数 */
  limit?: number
  /** 是否正在加载 */
  loadingRecordsPreview: boolean
  /** 记录列表 */
  recordsPreview: ConversationRecordItem[]

  /** 加载记录回调 */
  onLoadRecordsPreview: () => void
}

export function RecordsPreview({
  limit = 20,
  loadingRecordsPreview,
  recordsPreview,
  onLoadRecordsPreview,
}: RecordsPreviewProps) {
  const limitedRecords = recordsPreview.slice(0, limit)

  useEffect(() => {
    if (recordsPreview.length === 0) {
      onLoadRecordsPreview()
    }
  }, [onLoadRecordsPreview, recordsPreview.length])

  return (
    <div className={styles['collection-preview-panel']}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h3 style={{ margin: 0 }}>最近记录</h3>
        <button
          className={`btn ${styles['btn-secondary']}`}
          onClick={onLoadRecordsPreview}
          disabled={loadingRecordsPreview}
        >
          {loadingRecordsPreview ? '刷新中...' : '刷新'}
        </button>
      </div>
      {loadingRecordsPreview && recordsPreview.length === 0 ? (
        <div className={styles['loading']}>加载中...</div>
      ) : recordsPreview.length === 0 ? (
        <div className={styles['empty-state']}>
          <p>暂无记录</p>
        </div>
      ) : (
        <div className={styles['collection-record-list']}>
          {limitedRecords.map((record) => (
            <div key={record.id} className={styles['collection-record-item']}>
              <div className={styles['collection-record-row']}>
                <span className={styles['collection-record-node']}>{record.node_type}</span>
                <span className={`${styles['collection-record-status']} ${styles[record.status] || record.status}`}>
                  {record.status}
                </span>
              </div>
              <div className={`${styles['collection-record-row']} ${styles['muted']}`}>
                <span>会话: {record.session_id}</span>
                <span>{record.timestamp ? new Date(record.timestamp).toLocaleString('zh-CN') : '-'}</span>
              </div>
              <div className={`${styles['collection-record-row']} ${styles['muted']}`}>
                <span>模型: {record.provider || '-'} / {record.model || '-'}</span>
                <span>耗时: {record.execution_duration_ms ?? '-'} ms</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default RecordsPreview
