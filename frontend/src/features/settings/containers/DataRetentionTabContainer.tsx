/**
 * 数据保留设置容器
 * 管理所有状态与 API 调用，将数据与回调通过 props 传递给展示组件
 *
 * 改造说明（fix-performance-remaining-issues 模块 C）：
 *   - 原实现使用 useEffect + axios，每次 mount 都触发 /api/billing/retention 请求
 *   - 现改用 useQuery + queryClient.invalidateQueries，多 Tab 切换时复用缓存
 *   - queryKey: ['billing', 'retention']，保存成功后失效以触发刷新
 *   - Tab 组件的 mount effect 调用 onLoadRetentionConfig，此处置为稳定空函数，
 *     避免与 useQuery 的自动加载重复请求（useQuery 已接管 mount 时数据加载）
 */
import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { billingAPI, RetentionConfig } from '@/features/billing/billingApi'
import { useNotification } from '@/shared/hooks/useNotification'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import { Skeleton } from '@/shared/components/ui/Skeleton'

// 懒加载展示组件，减少首屏 bundle 体积
const DataRetentionTab = lazy(() => import('@/features/settings/components/DataRetentionTab').then(m => ({ default: m.DataRetentionTab })))

/** 懒加载占位符：使用 Skeleton 模拟表单结构 */
function TabLoadingFallback() {
  return (
    <div style={{ padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <Skeleton variant="rectangular" height="var(--space-10)" width="40%" />
      <Skeleton.Paragraph lines={6} />
    </div>
  )
}

/** 保留配置查询的 queryKey，供 invalidateQueries 复用 */
export const RETENTION_QUERY_KEY = ['billing', 'retention'] as const

export function DataRetentionTabContainer() {
  // 保留天数（用户可编辑）
  const [retentionDays, setRetentionDays] = useState(365)
  // 是否在保存后清理旧数据
  const [cleanupOld, setCleanupOld] = useState(false)
  // 保存状态
  const [saving, setSaving] = useState(false)

  const { showNotification } = useNotification(3000)
  const queryClient = useQueryClient()

  // 加载保留配置（React Query 缓存生效后，Tab 切换不会重复请求）
  const { data: retentionConfig, isLoading: loadingRetention } = useQuery<RetentionConfig>({
    queryKey: RETENTION_QUERY_KEY,
    queryFn: () => billingAPI.getRetention().then(r => r.data),
  })

  // 配置加载完成后同步 retentionDays（首次加载与保存后刷新均会触发）
  // 与原实现一致：加载数据后用服务端值回填输入框
  useEffect(() => {
    if (retentionConfig) {
      setRetentionDays(retentionConfig.retention_days)
    }
  }, [retentionConfig])

  // Tab 组件 mount effect 会调用此回调；useQuery 已接管数据加载，此处置为稳定空函数
  // 避免每次 Tab mount 触发 invalidateQueries 导致与 useQuery 自动加载重复请求
  const handleLoadRetentionConfig = useCallback(() => {
    // useQuery 自动管理数据加载，无需手动触发
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
      // 失效缓存，触发 useQuery 重新拉取最新配置
      await queryClient.invalidateQueries({ queryKey: RETENTION_QUERY_KEY })
      setCleanupOld(false)
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '保存失败') })
    } finally {
      setSaving(false)
    }
  }, [retentionDays, cleanupOld, showNotification, queryClient])

  return (
    <Suspense fallback={<TabLoadingFallback />}>
      <DataRetentionTab
        loadingRetention={loadingRetention}
        retentionConfig={retentionConfig ?? null}
        retentionDays={retentionDays}
        cleanupOld={cleanupOld}
        saving={saving}
        onLoadRetentionConfig={handleLoadRetentionConfig}
        onSaveRetention={handleSaveRetention}
        onRetentionDaysChange={setRetentionDays}
        onCleanupOldChange={setCleanupOld}
      />
    </Suspense>
  )
}
