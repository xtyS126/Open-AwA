/**
 * 添加配置表单组件
 */
import type { ModelProvider, ProviderModel } from '@/features/settings/modelsApi'
import styles from '@/features/settings/SettingsPage.module.css'

/** 表单字段值的类型：文本输入为 string，复选框为 boolean */
type FormFieldValue = string | boolean

interface AddConfigFormProps {
  /** 是否显示表单 */
  show: boolean
  /** 新配置数据 */
  newConfig: {
    provider: string
    model: string
    display_name: string
    description: string
    is_default: boolean
    is_image_generation: boolean
    image_generation_usage: string
  }
  /** 供应商列表 */
  providers: ModelProvider[]
  /** 供应商模型列表 */
  providerModels: ProviderModel[]
  /** 是否正在添加 */
  adding: boolean

  /** 关闭表单回调 */
  onClose: () => void
  /** 提供商变更回调 */
  onProviderChange: (provider: string) => void
  /** 模型选择变更回调 */
  onModelChange: (model: string) => void
  /** 其他字段变更回调 */
  onFieldChange: (field: string, value: FormFieldValue) => void
  /** 添加配置回调 */
  onAdd: () => void
}

export function AddConfigForm({
  show,
  newConfig,
  providers,
  providerModels,
  adding,
  onClose,
  onProviderChange,
  onModelChange,
  onFieldChange,
  onAdd,
}: AddConfigFormProps) {
  if (!show) {
    return null
  }

  return (
    <div className={styles['add-config-form']}>
      <div className={styles['form-row']}>
        <div className={styles['form-group']}>
          <label>提供商</label>
          <select
            value={newConfig.provider}
            onChange={(e) => onProviderChange(e.target.value)}
          >
            <option value="">选择提供商</option>
            {providers.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
        <div className={styles['form-group']}>
          <label>模型</label>
          <select
            value={newConfig.model}
            onChange={(e) => onModelChange(e.target.value)}
            disabled={!newConfig.provider}
          >
            <option value="">选择模型</option>
            {providerModels.map(m => (
              <option key={m.id} value={m.model}>{m.model}</option>
            ))}
          </select>
        </div>
      </div>
      <div className={styles['form-row']}>
        <div className={styles['form-group']}>
          <label>显示名称（可选）</label>
          <input
            type="text"
            value={newConfig.display_name}
            onChange={(e) => onFieldChange('display_name', e.target.value)}
            placeholder="例如：GPT-4.1"
          />
        </div>
      </div>
      <div className={styles['form-row']}>
        <div className={styles['form-group']}>
          <label>描述（可选）</label>
          <input
            type="text"
            value={newConfig.description}
            onChange={(e) => onFieldChange('description', e.target.value)}
            placeholder="模型描述"
          />
        </div>
      </div>
      <div className={styles['form-row']}>
        <div className={`${styles['form-group']} ${styles['checkbox-group']}`}>
          <input
            type="checkbox"
            id="is-image-generation-new"
            checked={newConfig.is_image_generation}
            onChange={(e) => onFieldChange('is_image_generation', e.target.checked)}
          />
          <label htmlFor="is-image-generation-new">生图模型（SD / GPT-Image / Qwen-Image 系列）</label>
        </div>
        <div className={`${styles['form-group']} ${styles['checkbox-group']}`}>
          <input
            type="checkbox"
            id="is-default-new"
            checked={newConfig.is_default}
            disabled={newConfig.is_image_generation}
            onChange={(e) => onFieldChange('is_default', e.target.checked)}
          />
          <label htmlFor="is-default-new">设为默认模型</label>
        </div>
      </div>
      {newConfig.is_image_generation && (
        <div className={styles['form-row']}>
          <div className={styles['form-group']}>
            <label>用途与限制（生图模型必填，供 AI 准确选择模型）</label>
            <textarea
              rows={3}
              value={newConfig.image_generation_usage}
              onChange={(e) => onFieldChange('image_generation_usage', e.target.value)}
              placeholder="例如：写实风格插画，支持 1024x1024 / 1536x1024，单张生成，不能生成文字内容"
            />
          </div>
        </div>
      )}
      <div className={styles['form-actions']}>
        <button className={`btn btn-primary`} onClick={onAdd} disabled={adding}>
          {adding ? '添加中...' : '添加'}
        </button>
        <button className={`btn ${styles['btn-secondary']}`} onClick={onClose}>
          取消
        </button>
      </div>
    </div>
  )
}

export default AddConfigForm
