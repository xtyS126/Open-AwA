/**
 * 价格编辑器子组件
 * 内嵌在表格中，提供价格输入框
 */
import { useState } from 'react'
import { billingAPI } from '@/features/billing/billingApi'
import styles from '@/features/settings/SettingsPage.module.css'

interface PriceEditorProps {
  /** 模型ID */
  modelId: number
  /** 当前编辑的价格 */
  inputPrice: string
  outputPrice: string
  /** 是否正在编辑 */
  isEditing: boolean

  /** 输入价格变更回调 */
  onInputPriceChange: (value: string) => void
  /** 输出价格变更回调 */
  onOutputPriceChange: (value: string) => void
  /** 保存回调 */
  onSave: () => void
  /** 取消回调 */
  onCancel: () => void
}

export function PriceEditor({
  modelId,
  inputPrice,
  outputPrice,
  isEditing,
  onInputPriceChange,
  onOutputPriceChange,
  onSave,
  onCancel,
}: PriceEditorProps) {
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    const input = parseFloat(inputPrice)
    const output = parseFloat(outputPrice)

    if (isNaN(input) || isNaN(output)) {
      return
    }

    setSaving(true)
    try {
      await billingAPI.updateModelPricing(modelId, {
        input_price: input,
        output_price: output,
      })
      onSave()
    } catch {
      // 错误由父组件处理
    } finally {
      setSaving(false)
    }
  }

  if (!isEditing) {
    return null
  }

  return (
    <div className={styles['action-buttons']}>
      <input
        type="number"
        value={inputPrice}
        onChange={(e) => onInputPriceChange(e.target.value)}
        className={styles['price-input']}
        step="0.0001"
        min="0"
      />
      <input
        type="number"
        value={outputPrice}
        onChange={(e) => onOutputPriceChange(e.target.value)}
        className={styles['price-input']}
        step="0.0001"
        min="0"
      />
      <button
        className={`btn ${styles['btn-small']} btn-primary`}
        onClick={handleSave}
        disabled={saving}
      >
        {saving ? '保存中...' : '保存'}
      </button>
      <button
        className={`btn ${styles['btn-small']}`}
        onClick={onCancel}
        disabled={saving}
      >
        取消
      </button>
    </div>
  )
}

export default PriceEditor
