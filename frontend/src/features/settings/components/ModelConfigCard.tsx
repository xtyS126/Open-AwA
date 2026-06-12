/**
 * 模型配置卡片组件，支持手风琴式展开/折叠，内嵌模型参数编辑器。
 * 每个卡片对应一个已导入的模型，可独立编辑参数并保存/重置。
 */
import { ModelParameterEditor, type ModelEditParams } from './ModelParameterEditor'
import styles from '@/features/settings/SettingsPage.module.css'

interface ModelConfigCardProps {
  /** 模型名称 */
  modelName: string
  /** 当前模型的可编辑参数 */
  params: ModelEditParams | undefined
  /** 是否展开 */
  isExpanded: boolean
  /** 是否正在保存 */
  isSaving: boolean
  /** 点击卡片头部切换展开/折叠 */
  onToggle: (modelName: string) => void
  /** 保存当前参数 */
  onSave: (modelName: string) => void
  /** 重置为默认参数 */
  onReset: (modelName: string) => void
  /** 参数变更回调 */
  onParamChange: (modelName: string, field: keyof ModelEditParams, value: number) => void
  /** 供应商 API 端点（只读展示） */
  apiEndpoint: string
  /** 复选框是否选中（用于批量删除） */
  checked: boolean
  /** 复选框变更回调 */
  onCheckChange: (modelName: string, checked: boolean) => void
  /** 参数摘要文本（折叠态展示） */
  summary: string
}

export function ModelConfigCard({
  modelName,
  params,
  isExpanded,
  isSaving,
  onToggle,
  onSave,
  onReset,
  onParamChange,
  apiEndpoint,
  checked,
  onCheckChange,
  summary,
}: ModelConfigCardProps) {
  return (
    <div className={styles['model-config-card']}>
      {/* 卡片头部：模型名 + 摘要 + 展开箭头 + 删除复选框 */}
      <div
        className={styles['model-config-card-header']}
        onClick={() => onToggle(modelName)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onToggle(modelName)
          }
        }}
      >
        <div className={styles['model-config-card-title']}>
          <span className={`${styles['model-config-card-arrow']} ${isExpanded ? styles['expanded'] : ''}`}>
            ▶
          </span>
          <span className={styles['model-config-card-name']}>{modelName}</span>
          {!isExpanded && (
            <span className={styles['model-config-card-summary']}>{summary}</span>
          )}
        </div>
        <label
          className={styles['model-config-card-checkbox']}
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => onCheckChange(modelName, e.target.checked)}
            aria-label={modelName}
          />
        </label>
      </div>

      {/* 展开后的卡片内容：固定信息 + 参数编辑器 + 操作按钮 */}
      {isExpanded && params && (
        <div className={styles['model-config-card-body']}>
          {/* 固定字段（不可编辑） */}
          <div className={styles['model-config-fixed-fields']}>
            <div className={styles['form-group']}>
              <label>API Key</label>
              <input
                type="text"
                value="由供应商配置"
                disabled
                className={styles['model-config-disabled-input']}
              />
              <span className={styles['param-hint']}>API Key 在供应商级别统一管理</span>
            </div>
            <div className={styles['form-group']}>
              <label>API 基础地址</label>
              <input
                type="text"
                value={apiEndpoint || '未配置'}
                disabled
                className={styles['model-config-disabled-input']}
              />
              <span className={styles['param-hint']}>基础地址在供应商级别统一管理</span>
            </div>
          </div>

          {/* 可编辑参数 */}
          <ModelParameterEditor
            params={params}
            onChange={(field, value) => onParamChange(modelName, field, value)}
            disabled={isSaving}
          />

          {/* 操作按钮 */}
          <div className={styles['model-config-card-actions']}>
            <button
              className="btn btn-primary"
              onClick={() => onSave(modelName)}
              disabled={isSaving}
            >
              {isSaving ? '保存中...' : '保存参数'}
            </button>
            <button
              className={`btn ${styles['btn-secondary']}`}
              onClick={() => onReset(modelName)}
              disabled={isSaving}
            >
              重置为默认
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default ModelConfigCard
