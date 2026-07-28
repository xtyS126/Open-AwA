/**
 * 导入模型模态框组件
 */
import type { ProviderModel } from '@/features/settings/modelsApi'
import styles from '@/features/settings/SettingsPage.module.css'

interface ImportModelsModalProps {
  /** 是否显示 */
  isOpen: boolean
  /** 获取到的远端模型列表 */
  fetchedRemoteModels: ProviderModel[]
  /** 已选中的模型列表 */
  modalSelectedModels: string[]
  /** 是否正在导入 */
  importing: boolean

  /** 关闭回调 */
  onClose: () => void
  /** 切换模型选中状态 */
  onToggleModel: (modelName: string, checked: boolean) => void
  /** 确认导入回调 */
  onImport: () => void
}

export function ImportModelsModal({
  isOpen,
  fetchedRemoteModels,
  modalSelectedModels,
  importing,
  onClose,
  onToggleModel,
  onImport,
}: ImportModelsModalProps) {
  if (!isOpen) {
    return null
  }

  return (
    <div className={styles['provider-modal-overlay']} onClick={onClose}>
      <div className={styles['provider-modal']} onClick={(e) => e.stopPropagation()} style={{ maxWidth: '600px', maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}>
        <div className={styles['provider-modal-header']}>
          <h3>导入模型</h3>
        </div>
        <div className={styles['provider-modal-body']} style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
          <p style={{ marginBottom: '16px', color: 'var(--text-secondary)' }}>请勾选需要导入的模型，未勾选的模型不会出现在聊天界面中。</p>
          <div className={styles['provider-model-list']} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
            {fetchedRemoteModels.map(model => {
              const checked = modalSelectedModels.includes(model.model)
              return (
                <label key={model.id || model.model} className={styles['provider-model-item']}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => onToggleModel(model.model, e.target.checked)}
                  />
                  <span className={styles['provider-model-name']}>{model.model}</span>
                </label>
              )
            })}
          </div>
        </div>
        <div className={styles['provider-modal-footer']} style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', padding: '16px', borderTop: '1px solid var(--border-color)' }}>
          <button
            className={`btn ${styles['btn-secondary']}`}
            onClick={onClose}
            disabled={importing}
          >
            取消
          </button>
          <button
            className={`btn btn-primary`}
            onClick={onImport}
            disabled={importing}
          >
            {importing ? '导入中...' : '确认导入'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ImportModelsModal
