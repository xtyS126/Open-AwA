import { useEffect, useCallback, useRef } from 'react'
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

/* 可聚焦元素选择器 */
const FOCUSABLE_SELECTORS = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

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
  const dialogRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  /* 监听 ESC 键关闭对话框，并处理 Tab 焦点陷阱 */
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCancel()
        return
      }
      /* Tab 键焦点陷阱 */
      if (e.key === 'Tab' && dialogRef.current) {
        const focusableElements = Array.from(
          dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS)
        )
        if (focusableElements.length === 0) return
        const firstElement = focusableElements[0]
        const lastElement = focusableElements[focusableElements.length - 1]
        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            e.preventDefault()
            lastElement.focus()
          }
        } else {
          if (document.activeElement === lastElement) {
            e.preventDefault()
            firstElement.focus()
          }
        }
      }
    },
    [onCancel]
  )

  useEffect(() => {
    if (isOpen) {
      /* 记录上一个焦点元素 */
      previousFocusRef.current = document.activeElement as HTMLElement | null
      document.addEventListener('keydown', handleKeyDown)
      /* 打开时阻止背景滚动 */
      document.body.style.overflow = 'hidden'
      /* 将焦点移到第一个可聚焦元素（取消按钮） */
      setTimeout(() => {
        const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS)
        if (focusable && focusable.length > 0) {
          focusable[0].focus()
        }
      }, 0)
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
      /* 关闭时恢复上一个焦点 */
      if (previousFocusRef.current) {
        previousFocusRef.current.focus()
        previousFocusRef.current = null
      }
    }
  }, [isOpen, handleKeyDown])

  if (!isOpen) return null

  return (
    <div className={styles['overlay']}>
      <div
        ref={dialogRef}
        className={styles['dialog']}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
      >
        <h3 id="confirm-dialog-title" className={styles['dialog-title']}>{title}</h3>
        <p id="confirm-dialog-message" className={styles['dialog-message']}>{message}</p>
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
