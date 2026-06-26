/**
 * 数据保留设置容器
 * 管理所有状态与 API 调用，将数据与回调通过 props 传递给展示组件
 */
import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { billingAPI, RetentionConfig } from '@/features/billing/billingApi'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
import { getErrorMessage } from '@/shared/utils/errorMessages'

// 懒加载展示组件，减少首屏 bundle 体积
const DataRetentionTab = lazy(() => import('@/features/settings/components/DataRetentionTab').then(m => ({ default: m.DataRetentionTab })))

/** 懒加载占位符 */
function TabLoadingFallback() {
  return <div style={{ padding: '2rem', textAlign: 'center', color: '#9ca3af' }}>加载中...</div>
}

export function DataRetentionTabContainer() {
  // 保留配置数据
  const [retentionConfig, setRetentionConfig] = useState<RetentionConfig | null>(null)
  // 保留天数
  const [retentionDays, setRetentionDays] = useState(365)
  // 是否在保存后清理旧数据
  const [cleanupOld, setCleanupOld] = useState(false)
  // 加载状态
  const [loadingRetention, setLoadingRetention] = useState(false)
  // 保存状态
  const [saving, setSaving] = useState(false)

  const { showNotification } = useNotification(3000)

  // 加载保留配置
  const loadRetentionConfig = useCallback(async () => {
    setLoadingRetention(true)
    try {
      const response = await billingAPI.getRetention()
      setRetentionConfig(response.data)
      setRetentionDays(response.data.retention_days)
    } catch {
      appLogger.error({ event: 'retention_config_load_failed', message: 'Failed to load retention config', module: 'settings' })
    } finally {
      setLoadingRetention(false)
    }
  }, [])

  // 保存保留配置
  const handleSaveRetention = useCallback(async () => {
    setSaving(true)
    try {
      const response = await billingAPI.updateRetention({
        retention_days: retentionDays,
        cleanup: cleanupOld
      })
      showNotification({ type: 'success', text: `保存成功${cleanupOld && response.data.deleted_records > 0 ? `，已删除${response.data.deleted_records}条过期记录` : ''}` })
      await loadRetentionConfig()
      setCleanupOld(false)
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '保存失败') })
    } finally {
      setSaving(false)
    }
  }, [retentionDays, cleanupOld, showNotification, loadRetentionConfig])

  // 挂载时加载数据
  useEffect(() => {
    loadRetentionConfig()
  }, [loadRetentionConfig])

  return (
    <Suspense fallback={<TabLoadingFallback />}>
      <DataRetentionTab
        loadingRetention={loadingRetention}
        retentionConfig={retentionConfig}
        retentionDays={retentionDays}
        cleanupOld={cleanupOld}
        saving={saving}
        onLoadRetentionConfig={loadRetentionConfig}
        onSaveRetention={handleSaveRetention}
        onRetentionDaysChange={setRetentionDays}
        onCleanupOldChange={setCleanupOld}
      />
    </Suspense>
  )
}
