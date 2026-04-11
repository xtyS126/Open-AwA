import { useState, useCallback, useEffect } from 'react'
import styles from './Toast.module.css'

/* Toast 通知组件的类型定义 */
interface ToastProps {
  message: string
  type: 'success' | 'error' | 'warning' | 'info'
  duration?: number
  onClose: () => void
}

/* Toast 列表项类型 */
export interface ToastItem {
  id: string
  message: string
  type: 'success' | 'error' | 'warning' | 'info'
}

/* 关闭按钮图标 */
const closeIcon = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
)

/* 不同类型的图标 */
const typeIcons = {
  success: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  ),
  error: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <line x1="15" y1="9" x2="9" y2="15" />
      <line x1="9" y1="9" x2="15" y2="15" />
    </svg>
  ),
  warning: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  info: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  ),
}

/* 单个 Toast 通知组件 */
function Toast({ message, type, duration = 3000, onClose }: ToastProps) {
  const [exiting, setExiting] = useState(false)

  useEffect(() => {
    /* 设置自动消失计时器 */
    const timer = setTimeout(() => {
      setExiting(true)
    }, duration)

    return () => clearTimeout(timer)
  }, [duration])

  useEffect(() => {
    /* 退场动画结束后触发关闭回调 */
    if (exiting) {
      const timer = setTimeout(onClose, 300)
      return () => clearTimeout(timer)
    }
  }, [exiting, onClose])

  const handleClose = () => {
    setExiting(true)
  }

  return (
    <div
      className={`${styles['toast']} ${styles[type]} ${exiting ? styles['exit'] : ''}`}
      role="alert"
    >
      <span className={styles['toast-icon']}>{typeIcons[type]}</span>
      <span className={styles['toast-message']}>{message}</span>
      <button className={styles['toast-close']} onClick={handleClose} title="关闭">
        {closeIcon}
      </button>
    </div>
  )
}

/* Toast 容器组件 - 渲染所有活跃的 Toast */
function ToastContainer({ toasts, removeToast }: {
  toasts: ToastItem[]
  removeToast: (id: string) => void
}) {
  if (toasts.length === 0) return null

  return (
    <div className={styles['toast-container']}>
      {toasts.map((toast) => (
        <Toast
          key={toast.id}
          message={toast.message}
          type={toast.type}
          onClose={() => removeToast(toast.id)}
        />
      ))}
    </div>
  )
}

/* useToast hook - 管理 Toast 通知的状态和操作 */
export function useToast() {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  /* 添加新的 Toast 通知 */
  const addToast = useCallback((message: string, type: ToastItem['type'] = 'info') => {
    const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
    setToasts((prev) => [...prev, { id, message, type }])
  }, [])

  /* 根据 id 移除指定 Toast */
  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  /* 渲染 Toast 容器的便捷组件 */
  const ToastContainerElement = useCallback(
    () => <ToastContainer toasts={toasts} removeToast={removeToast} />,
    [toasts, removeToast]
  )

  return { toasts, addToast, removeToast, ToastContainer: ToastContainerElement }
}

export default Toast
