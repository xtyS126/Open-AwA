/**
 * 模型价格配置组件
 * 配置各AI厂商的模型API价格（单位：百万tokens）
 */
import type { ModelPricing } from '@/features/billing/billingApi'
import { PricingTableGroup } from './PricingTableGroup'
import styles from '@/features/settings/SettingsPage.module.css'

interface BillingTabProps {
  /** 是否正在加载 */
  loadingModels: boolean
  /** 所有价格模型（保留以保持接口一致） */
  models: ModelPricing[]
  /** 当前编辑的模型ID */
  editingModel: number | null
  /** 编辑中的价格数据 */
  editPrices: { input_price: string; output_price: string }
  /** 按供应商分组的模型 */
  groupedModels: Record<string, ModelPricing[]>

  /** 开始编辑模型回调 */
  onEditModel: (model: ModelPricing) => void
  /** 输入价格变更回调 */
  onInputPriceChange: (value: string) => void
  /** 输出价格变更回调 */
  onOutputPriceChange: (value: string) => void
  /** 保存价格回调 */
  onSaveModelPrice: (modelId: number) => void
  /** 取消编辑回调 */
  onCancelEdit: () => void
}

export function BillingTab({
  loadingModels,
  editingModel,
  editPrices,
  groupedModels,
  onEditModel,
  onInputPriceChange,
  onOutputPriceChange,
  onSaveModelPrice,
  onCancelEdit,
}: BillingTabProps) {
  return (
    <div className={styles['settings-section']}>
      <h2>模型价格配置</h2>
      <p className={styles['section-desc']}>
        配置各AI厂商的模型API价格（单位：百万tokens）
      </p>

      {loadingModels ? (
        <div className={styles['loading']}>加载中...</div>
      ) : (
        <div className={styles['pricing-table-container']}>
          {Object.entries(groupedModels).map(([provider, providerModels]) => (
            <PricingTableGroup
              key={provider}
              provider={provider}
              models={providerModels}
              editingModelId={editingModel}
              editPrices={editPrices}
              isMultimodal={providerModels.some(m => m.is_multimodal)}
              supportsVision={providerModels.some(m => m.supports_vision)}
              onEdit={onEditModel}
              onInputPriceChange={onInputPriceChange}
              onOutputPriceChange={onOutputPriceChange}
              onSave={onSaveModelPrice}
              onCancel={onCancelEdit}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default BillingTab
