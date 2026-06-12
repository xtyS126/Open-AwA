/**
 * 数据采集与导出组件
 * 管理对话数据采集、预览、导出和清理
 */
import { useState, useEffect } from 'react'
import type { ConversationCollectionStatusResponse, ConversationRecordItem } from '@/shared/api/api'
import styles from '@/features/settings/SettingsPage.module.css'
import { CollectionStats } from './CollectionStats'
import { ExportPanel } from './ExportPanel'
import { CleanupPanel } from './CleanupPanel'
import { RecordsPreview } from './RecordsPreview'

interface DataCollectionTabProps {
  /** 采集是否启用 */
  collectionEnabled: boolean
  /** 统计数据 */
  collectionStats: ConversationCollectionStatusResponse['stats'] | null
  /** 是否正在更新采集开关 */
  updatingCollection: boolean
  /** 预览记录列表 */
  recordsPreview: ConversationRecordItem[]
  /** 是否正在加载预览 */
  loadingRecordsPreview: boolean
  /** 导出开始时间 */
  exportStartTime: string
  /** 导出结束时间 */
  exportEndTime: string
  /** 是否正在导出 */
  exportingRecords: boolean
  /** 清理天数 */
  cleanupDays: number
  /** 是否正在清理 */
  cleaningRecords: boolean

  /** 切换采集开关回调 */
  onToggleCollection: (enabled: boolean) => void
  /** 加载记录预览回调 */
  onLoadRecordsPreview: () => void
  /** 导出记录回调 */
  onExportRecords: () => void
  /** 清理记录回调 */
  onCleanupRecords: () => void
  /** 导出开始时间变更回调 */
  onExportStartTimeChange: (time: string) => void
  /** 导出结束时间变更回调 */
  onExportEndTimeChange: (time: string) => void
  /** 清理天数变更回调 */
  onCleanupDaysChange: (days: number) => void
}

export function DataCollectionTab({
  collectionEnabled,
  collectionStats,
  updatingCollection,
  recordsPreview,
  loadingRecordsPreview,
  exportStartTime,
  exportEndTime,
  exportingRecords,
  cleanupDays,
  cleaningRecords,
  onToggleCollection,
  onLoadRecordsPreview,
  onExportRecords,
  onCleanupRecords,
  onExportStartTimeChange,
  onExportEndTimeChange,
  onCleanupDaysChange,
}: DataCollectionTabProps) {
  const [localCleanupDays, setLocalCleanupDays] = useState(cleanupDays)

  useEffect(() => {
    setLocalCleanupDays(cleanupDays)
  }, [cleanupDays])

  const handleCleanupDaysChange = (value: number) => {
    setLocalCleanupDays(value)
    onCleanupDaysChange(value)
  }

  return (
    <div className={styles['settings-section']}>
      <h2>对话数据采集</h2>
      <p className={styles['section-desc']}>
        采集调用链数据，预览最近记录，导出 JSONL，并清理历史数据。
      </p>

      <div className={`${styles['setting-item']} ${styles['checkbox']}`}>
        <input
          type="checkbox"
          id="conversation-collection"
          checked={collectionEnabled}
          onChange={(e) => onToggleCollection(e.target.checked)}
          disabled={updatingCollection}
        />
        <label htmlFor="conversation-collection">
          {updatingCollection ? '更新中...' : '启用对话数据采集'}
        </label>
      </div>

      <CollectionStats stats={collectionStats} />

      <div className={styles['collection-actions-row']}>
        <RecordsPreview
          limit={20}
          loadingRecordsPreview={loadingRecordsPreview}
          recordsPreview={recordsPreview}
          onLoadRecordsPreview={onLoadRecordsPreview}
        />
      </div>

      <ExportPanel
        exportStartTime={exportStartTime}
        exportEndTime={exportEndTime}
        exportingRecords={exportingRecords}
        onExportStartTimeChange={onExportStartTimeChange}
        onExportEndTimeChange={onExportEndTimeChange}
        onExportRecords={onExportRecords}
      />

      <CleanupPanel
        cleanupDays={localCleanupDays}
        cleaningRecords={cleaningRecords}
        onCleanupDaysChange={handleCleanupDaysChange}
        onCleanupRecords={onCleanupRecords}
      />
    </div>
  )
}

export default DataCollectionTab
