/**
 * 价格表格分组组件
 * 按供应商分组的模型价格表格
 */
import type { ModelPricing } from '@/features/billing/billingApi'
import { PriceEditor } from './PriceEditor'
import { formatPrice } from '@/features/settings/SettingsPage.utils.tsx'
import styles from '@/features/settings/SettingsPage.module.css'

interface PricingTableGroupProps {
  /** 供应商标识 */
  provider: string
  /** 该供应商的模型列表 */
  models: ModelPricing[]
  /** 当前正在编辑的模型ID */
  editingModelId: number | null
  /** 编辑中的价格数据 */
  editPrices: { input_price: string; output_price: string }
  /** 是否多模态 */
  isMultimodal?: boolean
  /** 是否支持视觉 */
  supportsVision?: boolean

  /** 开始编辑回调 */
  onEdit: (model: ModelPricing) => void
  /** 价格输入变更回调 */
  onInputPriceChange: (value: string) => void
  /** 价格输出变更回调 */
  onOutputPriceChange: (value: string) => void
  /** 保存价格回调 */
  onSave: (modelId: number) => void
  /** 取消编辑回调 */
  onCancel: () => void
}

export function PricingTableGroup({
  provider,
  models,
  editingModelId,
  editPrices,
  isMultimodal,
  supportsVision,
  onEdit,
  onInputPriceChange,
  onOutputPriceChange,
  onSave,
  onCancel,
}: PricingTableGroupProps) {
  return (
    <div key={provider} className={styles['pricing-provider-group']}>
      <h3 className={styles['provider-title']}>{provider.toUpperCase()}</h3>
      <table className={styles['pricing-table']}>
        <thead>
          <tr>
            <th>模型</th>
            <th>模态</th>
            <th>输入价格</th>
            <th>输出价格</th>
            <th>缓存价格</th>
            <th>上下文窗口</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {models.map((model) => (
            <tr key={model.id}>
              <td className={styles['model-name']}>{model.model}</td>
              <td>
                <span
                  className={[
                    styles['modality-badge'],
                    isMultimodal ? styles['modality-multimodal'] :
                    supportsVision ? styles['modality-vision'] :
                    styles['modality-text'],
                  ].join(' ')}
                >
                  {isMultimodal ? '文本+图像+音视频' :
                   supportsVision ? '文本+图像' :
                   '文本'}
                </span>
              </td>
              <td>
                {editingModelId === model.id ? (
                  <input
                    type="number"
                    value={editPrices.input_price}
                    onChange={(e) => onInputPriceChange(e.target.value)}
                    className={styles['price-input']}
                    step="0.0001"
                  />
                ) : (
                  formatPrice(model.input_price, model.currency)
                )}
              </td>
              <td>
                {editingModelId === model.id ? (
                  <input
                    type="number"
                    value={editPrices.output_price}
                    onChange={(e) => onOutputPriceChange(e.target.value)}
                    className={styles['price-input']}
                    step="0.0001"
                  />
                ) : (
                  formatPrice(model.output_price, model.currency)
                )}
              </td>
              <td>
                {model.cache_hit_price
                  ? formatPrice(model.cache_hit_price, model.currency)
                  : '-'}
              </td>
              <td>
                {model.context_window
                  ? `${(model.context_window / 1000).toFixed(0)}K`
                  : '-'}
              </td>
              <td>
                <PriceEditor
                  modelId={model.id}
                  inputPrice={editPrices.input_price}
                  outputPrice={editPrices.output_price}
                  isEditing={editingModelId === model.id}
                  onInputPriceChange={onInputPriceChange}
                  onOutputPriceChange={onOutputPriceChange}
                  onSave={() => onSave(model.id)}
                  onCancel={onCancel}
                />
                {editingModelId !== model.id && (
                  <button
                    className={`btn ${styles['btn-small']}`}
                    onClick={() => onEdit(model)}
                  >
                    编辑
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default PricingTableGroup
