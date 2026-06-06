/**
 * Modal 模态框组件 — 统一弹窗行为。
 * 支持标题、内容、底部操作区，点击遮罩或 ESC 关闭。
 */
import { useEffect, useCallback, type ReactNode } from 'react'
import { X } from 'lucide-react'
import styles from './Modal.module.css'

interface ModalProps {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  footer?: ReactNode
  width?: string
}

function Modal({ open, onClose, title, children, footer, width }: ModalProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    },
    [onClose]
  )

  useEffect(() => {
    if (open) {
      document.addEventListener('keydown', handleKeyDown)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [open, handleKeyDown])

  if (!open) return null

  return (
    <div className={styles.overlay} onClick={onClose} role="dialog" aria-modal="true" aria-label={title || '对话框'}>
      <div
        className={styles.modal}
        style={width ? { maxWidth: width } : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div className={styles.header}>
            <h2 className={styles.title}>{title}</h2>
            <button className={styles.closeBtn} onClick={onClose} aria-label="关闭">
              <X size={18} />
            </button>
          </div>
        )}
        <div className={styles.body}>{children}</div>
        {footer && <div className={styles.footer}>{footer}</div>}
      </div>
    </div>
  )
}

export { Modal }
export type { ModalProps }
