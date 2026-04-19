import { useState, useCallback, useEffect } from 'react'
import { X, CheckCircle, XCircle, AlertTriangle, Info } from 'lucide-react'
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
const closeIcon = <X size={14} />

/* 不同类型的图标 */
const typeIcons = {
  success: <CheckCircle size={18} />,
  error: <XCircle size={18} />,
  warning: <AlertTriangle size={18} />,
  info: <Info size={18} />,
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
