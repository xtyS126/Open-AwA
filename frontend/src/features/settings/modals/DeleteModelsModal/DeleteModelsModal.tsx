/**
 * 批量删除模型确认模态框组件
 */
import styles from '@/features/settings/SettingsPage.module.css'

interface DeleteModelsModalProps {
  /** 是否显示 */
  isOpen: boolean
  /** 已选中的模型数量 */
  selectedCount: number
  /** 是否正在删除 */
  deletingModels: boolean

  /** 关闭回调 */
  onClose: () => void
  /** 确认回调 */
  onConfirm: () => void
}

export function DeleteModelsModal({
  isOpen,
  selectedCount,
  deletingModels,
  onClose,
  onConfirm,
}: DeleteModelsModalProps) {
  if (!isOpen) {
    return null
  }

  return (
    <div className={styles['provider-modal-overlay']} onClick={onClose}>
      <div className={styles['provider-modal']} onClick={(e) => e.stopPropagation()}>
        <div className={styles['provider-modal-header']}>
          <h3>确认批量删除</h3>
        </div>
        <div className={styles['provider-modal-body']}>
          <p style={{ margin: '16px 0', lineHeight: 1.5 }}>
            确定要删除选中的 <strong>{selectedCount}</strong> 个模型吗？<br />
            这些模型将从当前配置中移除。
          </p>
        </div>
        <div className={styles['provider-modal-footer']}>
          <button
            className={`btn ${styles['btn-secondary']}`}
            onClick={onClose}
            disabled={deletingModels}
          >
            取消
          </button>
          <button
            className={`btn ${styles['btn-danger']}`}
            onClick={onConfirm}
            disabled={deletingModels}
          >
            {deletingModels ? '删除中...' : '确认删除'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default DeleteModelsModal
