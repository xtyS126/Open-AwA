import { useEffect, useCallback } from 'react'
import styles from './ConfirmDialog.module.css'

interface ConfirmDialogProps {
  isOpen: boolean
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  type?: 'danger' | 'warning' | 'info'
  onConfirm: () => void
  onCancel: () => void
}

/* 确认对话框组件 - 替代浏览器原生 confirm */
function ConfirmDialog({
  isOpen,
  title,
  message,
  confirmText = '确认',
  cancelText = '取消',
  type = 'info',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  /* 监听 ESC 键关闭对话框 */
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCancel()
      }
    },
    [onCancel]
  )

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown)
      /* 打开时阻止背景滚动 */
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [isOpen, handleKeyDown])

  if (!isOpen) return null

  return (
    <div className={styles['overlay']} role="dialog" aria-modal="true">
      <div className={styles['dialog']}>
        <h3 className={styles['dialog-title']}>{title}</h3>
        <p className={styles['dialog-message']}>{message}</p>
        <div className={styles['dialog-actions']}>
          <button
            className={styles['btn-cancel']}
            onClick={onCancel}
          >
            {cancelText}
          </button>
          <button
            className={`${styles['btn-confirm']} ${styles[type]}`}
            onClick={onConfirm}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ConfirmDialog
