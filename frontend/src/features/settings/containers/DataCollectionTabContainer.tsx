/**
 * 数据采集 Tab 容器组件
 * 管理所有状态和 API 调用，将数据与回调通过 props 传递给展示组件
 */
import { lazy, Suspense, useState, useEffect, useCallback } from 'react'
import { conversationAPI, ConversationRecordItem, ConversationCollectionStatusResponse } from '@/shared/api/api'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
import { Skeleton } from '@/shared/components/ui/Skeleton'

// 懒加载展示组件，通过 .then() 将命名导出映射为 default 导出
const DataCollectionTab = lazy(() => import('@/features/settings/components/DataCollectionTab').then(m => ({ default: m.DataCollectionTab })))

/** 懒加载组件的加载占位符：使用 Skeleton 模拟表单结构 */
function TabLoadingFallback() {
  return (
    <div style={{ padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <Skeleton variant="rectangular" height="var(--space-10)" width="40%" />
      <Skeleton.Paragraph lines={6} />
    </div>
  )
}

export function DataCollectionTabContainer() {
  // 采集开关与统计状态
  const [collectionEnabled, setCollectionEnabled] = useState(false)
  const [collectionStats, setCollectionStats] = useState<ConversationCollectionStatusResponse['stats'] | null>(null)
  const [updatingCollection, setUpdatingCollection] = useState(false)

  // 记录预览状态
  const [recordsPreview, setRecordsPreview] = useState<ConversationRecordItem[]>([])
  const [loadingRecordsPreview, setLoadingRecordsPreview] = useState(false)

  // 导出相关状态
  const [exportStartTime, setExportStartTime] = useState('')
  const [exportEndTime, setExportEndTime] = useState('')
  const [exportingRecords, setExportingRecords] = useState(false)

  // 清理相关状态
  const [cleanupDays, setCleanupDays] = useState(30)
  const [cleaningRecords, setCleaningRecords] = useState(false)

  const { message, showNotification } = useNotification(3000)

  // 加载采集状态
  const loadCollectionStatus = useCallback(async () => {
    try {
      const response = await conversationAPI.getCollectionStatus()
      setCollectionEnabled(Boolean(response.data.enabled))
      setCollectionStats(response.data.stats || null)
    } catch {
      appLogger.error({ event: 'collection_status_load_failed', message: '加载采集状态失败', module: 'settings' })
      showNotification({ type: 'error', text: '加载收集状态失败' })
    }
  }, [showNotification])

  // 加载记录预览
  const loadRecordsPreview = useCallback(async () => {
    setLoadingRecordsPreview(true)
    try {
      const response = await conversationAPI.getRecordsPreview(20)
      setRecordsPreview(response.data.records || [])
    } catch {
      appLogger.error({ event: 'records_preview_load_failed', message: '加载记录预览失败', module: 'settings' })
      showNotification({ type: 'error', text: '加载最近记录失败' })
    } finally {
      setLoadingRecordsPreview(false)
    }
  }, [showNotification])

  // 挂载时并行加载采集状态与记录预览
  useEffect(() => {
    loadCollectionStatus()
    loadRecordsPreview()
  }, [loadCollectionStatus, loadRecordsPreview])

  // 切换采集开关
  const handleToggleCollection = useCallback(async (enabled: boolean) => {
    setUpdatingCollection(true)
    try {
      await conversationAPI.updateCollectionStatus(enabled)
      setCollectionEnabled(enabled)
      await loadCollectionStatus()
      showNotification({ type: 'success', text: enabled ? '已开启数据收集' : '已关闭数据收集' })
    } catch {
      showNotification({ type: 'error', text: '更新收集开关失败' })
    } finally {
      setUpdatingCollection(false)
    }
  }, [loadCollectionStatus, showNotification])

  // 导出记录（blob 下载）
  const handleExportRecords = useCallback(async () => {
    setExportingRecords(true)
    try {
      const params: { start_time?: string; end_time?: string } = {}
      if (exportStartTime) {
        params.start_time = new Date(exportStartTime).toISOString()
      }
      if (exportEndTime) {
        params.end_time = new Date(exportEndTime).toISOString()
      }

      const response = await conversationAPI.exportRecords(params)
      const dispositionHeader = response.headers['content-disposition'] as string | undefined
      const matched = dispositionHeader?.match(/filename="?([^"]+)"?/) || null
      const filename = matched?.[1] || 'conversation_records.jsonl'

      const blob = new Blob([response.data], { type: 'application/x-ndjson' })
      const downloadUrl = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = downloadUrl
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(downloadUrl)

      showNotification({ type: 'success', text: '导出完成' })
    } catch {
      showNotification({ type: 'error', text: '导出失败' })
    } finally {
      setExportingRecords(false)
    }
  }, [exportStartTime, exportEndTime, showNotification])

  // 清理历史记录
  const handleCleanupRecords = useCallback(async () => {
    if (!confirm(`确认清理 ${cleanupDays} 天前的记录吗？`)) return

    setCleaningRecords(true)
    try {
      const response = await conversationAPI.cleanupRecords(cleanupDays)
      const deleted = response.data?.deleted_count ?? 0
      showNotification({ type: 'success', text: `清理完成：已删除 ${deleted} 条记录` })
      await loadRecordsPreview()
      await loadCollectionStatus()
    } catch {
      showNotification({ type: 'error', text: '清理失败' })
    } finally {
      setCleaningRecords(false)
    }
  }, [cleanupDays, loadRecordsPreview, loadCollectionStatus, showNotification])

  return (
    <Suspense fallback={<TabLoadingFallback />}>
      {message && (
        <div style={{ marginBottom: '1rem' }}>
          {message.text}
        </div>
      )}
      <DataCollectionTab
        collectionEnabled={collectionEnabled}
        collectionStats={collectionStats}
        updatingCollection={updatingCollection}
        recordsPreview={recordsPreview}
        loadingRecordsPreview={loadingRecordsPreview}
        exportStartTime={exportStartTime}
        exportEndTime={exportEndTime}
        exportingRecords={exportingRecords}
        cleanupDays={cleanupDays}
        cleaningRecords={cleaningRecords}
        onToggleCollection={handleToggleCollection}
        onLoadRecordsPreview={loadRecordsPreview}
        onExportRecords={handleExportRecords}
        onCleanupRecords={handleCleanupRecords}
        onExportStartTimeChange={setExportStartTime}
        onExportEndTimeChange={setExportEndTime}
        onCleanupDaysChange={setCleanupDays}
      />
    </Suspense>
  )
}

export default DataCollectionTabContainer
