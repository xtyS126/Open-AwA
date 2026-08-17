/**
 * 计费配置 Tab 容器组件
 * 管理所有计费相关的状态和 API 调用
 *
 * 改造说明（fix-performance-remaining-issues 模块 C）：
 *   - 原实现使用 useEffect + axios，每次 mount 都触发 /api/billing/models 请求
 *   - 现改用 useQuery + queryClient.invalidateQueries，多 Tab 切换时复用缓存
 *   - queryKey: ['billing', 'models']，与 GeneralTabContainer 共享缓存
 *   - 保存价格成功后失效缓存以触发刷新
 */
import { lazy, Suspense, useCallback, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { billingAPI, ModelPricing } from '@/features/billing/billingApi'
import { useNotification } from '@/shared/hooks/useNotification'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import { Skeleton } from '@/shared/components/ui/Skeleton'

// 懒加载 BillingTab 组件，减少首屏 bundle 体积
const BillingTab = lazy(() => import('@/features/settings/components/BillingTab').then(m => ({ default: m.BillingTab })))

/** 懒加载组件的加载占位符：使用 Skeleton 模拟表单结构 */
function TabLoadingFallback() {
  return (
    <div style={{ padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <Skeleton variant="rectangular" height="var(--space-10)" width="40%" />
      <Skeleton.Paragraph lines={6} />
    </div>
  )
}

/** 模型列表查询的 queryKey，供 GeneralTabContainer 共享缓存 */
export const BILLING_MODELS_QUERY_KEY = ['billing', 'models'] as const

export function BillingTabContainer() {
  const { showNotification } = useNotification(3000)
  const queryClient = useQueryClient()

  // 编辑状态
  const [editingModel, setEditingModel] = useState<number | null>(null)
  const [editPrices, setEditPrices] = useState({ input_price: '', output_price: '' })

  // 加载模型列表（与 GeneralTabContainer 共享 ['billing', 'models'] 缓存）
  // 不使用 initialData：否则 staleTime 内 React Query 会将初始值视为新鲜数据而不发起请求
  const { data: models, isLoading: loadingModels } = useQuery<ModelPricing[]>({
    queryKey: BILLING_MODELS_QUERY_KEY,
    queryFn: () => billingAPI.getModels().then(r => r.data.models || []),
  })

  // 按供应商分组模型（计算属性）
  const groupedModels = useMemo(() => (models || []).reduce((acc, model) => {
    if (!acc[model.provider]) {
      acc[model.provider] = []
    }
    acc[model.provider].push(model)
    return acc
  }, {} as Record<string, ModelPricing[]>), [models])

  // 开始编辑模型价格
  const handleEditModel = useCallback((model: ModelPricing) => {
    setEditingModel(model.id)
    setEditPrices({
      input_price: model.input_price.toString(),
      output_price: model.output_price.toString()
    })
  }, [])

  // 保存模型价格
  const handleSaveModelPrice = useCallback(async (modelId: number) => {
    try {
      await billingAPI.updateModelPricing(modelId, {
        input_price: parseFloat(editPrices.input_price),
        output_price: parseFloat(editPrices.output_price)
      })
      setEditingModel(null)
      // 失效缓存，触发 useQuery 重新拉取最新价格列表
      await queryClient.invalidateQueries({ queryKey: BILLING_MODELS_QUERY_KEY })
      showNotification({ type: 'success', text: '价格更新成功' })
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '价格更新失败') })
    }
  }, [editPrices, queryClient, showNotification])

  // 输入价格变更
  const handleInputPriceChange = useCallback((value: string) => {
    setEditPrices(prev => ({ ...prev, input_price: value }))
  }, [])

  // 输出价格变更
  const handleOutputPriceChange = useCallback((value: string) => {
    setEditPrices(prev => ({ ...prev, output_price: value }))
  }, [])

  // 取消编辑
  const handleCancelEdit = useCallback(() => {
    setEditingModel(null)
  }, [])

  return (
    <Suspense fallback={<TabLoadingFallback />}>
      <BillingTab
        loadingModels={loadingModels}
        models={models || []}
        editingModel={editingModel}
        editPrices={editPrices}
        groupedModels={groupedModels}
        onEditModel={handleEditModel}
        onInputPriceChange={handleInputPriceChange}
        onOutputPriceChange={handleOutputPriceChange}
        onSaveModelPrice={handleSaveModelPrice}
        onCancelEdit={handleCancelEdit}
      />
    </Suspense>
  )
}
