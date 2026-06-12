/**
 * 删除供应商确认模态框组件
 */
import styles from '@/features/settings/SettingsPage.module.css'

interface DeleteConfirmModalProps {
  /** 是否显示 */
  isOpen: boolean
  /** 供应商名称 */
  providerName: string
  /** 是否正在删除 */
  deletingProvider: boolean

  /** 关闭回调 */
  onClose: () => void
  /** 确认回调 */
  onConfirm: () => void
}

export function DeleteConfirmModal({
  isOpen,
  providerName,
  deletingProvider,
  onClose,
  onConfirm,
}: DeleteConfirmModalProps) {
  if (!isOpen) {
    return null
  }

  return (
    <div className={styles['provider-modal-overlay']} onClick={onClose}>
      <div className={styles['provider-modal']} onClick={(e) => e.stopPropagation()}>
        <div className={styles['provider-modal-header']}>
          <h3>确认删除</h3>
        </div>
        <div className={styles['provider-modal-body']}>
          <p style={{ margin: '16px 0', lineHeight: 1.5 }}>
            确定要删除供应商"<strong>{providerName}</strong>"吗？<br />
            该供应商下的配置将被永久删除，此操作不可恢复。
          </p>
        </div>
        <div className={styles['provider-modal-footer']}>
          <button
            className={`btn ${styles['btn-secondary']}`}
            onClick={onClose}
            disabled={deletingProvider}
          >
            取消
          </button>
          <button
            className={`btn ${styles['btn-danger']}`}
            onClick={onConfirm}
            disabled={deletingProvider}
          >
            {deletingProvider ? '删除中...' : '确认删除'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default DeleteConfirmModal
