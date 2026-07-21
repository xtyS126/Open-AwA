import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { billingAPI, ModelPricing } from '@/features/billing/billingApi'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
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

/**
 * 计费配置 Tab 容器组件
 * 管理所有计费相关的状态和 API 调用
 */
export function BillingTabContainer() {
  const { showNotification } = useNotification(3000)

  // 模型价格列表状态
  const [models, setModels] = useState<ModelPricing[]>([])
  const [loadingModels, setLoadingModels] = useState(false)

  // 编辑状态
  const [editingModel, setEditingModel] = useState<number | null>(null)
  const [editPrices, setEditPrices] = useState({ input_price: '', output_price: '' })

  // 按供应商分组模型（计算属性）
  const groupedModels = useMemo(() => models.reduce((acc, model) => {
    if (!acc[model.provider]) {
      acc[model.provider] = []
    }
    acc[model.provider].push(model)
    return acc
  }, {} as Record<string, ModelPricing[]>), [models])

  // 加载计费数据
  const loadBillingData = useCallback(() => {
    setLoadingModels(true)
    billingAPI.getModels()
      .then(modelsRes => {
        setModels(modelsRes.data.models || [])
      })
      .catch(() => {
        appLogger.error({ event: 'billing_data_load_failed', message: 'Failed to load billing data', module: 'settings' })
      })
      .finally(() => {
        setLoadingModels(false)
      })
  }, [])

  // 组件挂载时加载数据
  useEffect(() => {
    loadBillingData()
  }, [loadBillingData])

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
      loadBillingData()
      showNotification({ type: 'success', text: '价格更新成功' })
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '价格更新失败') })
    }
  }, [editPrices, loadBillingData, showNotification])

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
        models={models}
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
