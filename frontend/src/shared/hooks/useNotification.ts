/**
 * 通知消息管理 Hook
 * 提供统一的通知显示与自动清除机制，替代分散的 setTimeout 模式。
 * 支持自定义消息持续时间和回调清理。
 */
import { useState, useCallback, useRef, useEffect } from 'react'

/** 通知消息类型定义 */
export interface NotificationMessage {
  type: 'success' | 'error'
  text: string
}

/**
 * 通知消息管理自定义 Hook。
 * 自动在指定时间后清除消息，组件卸载时清理定时器防止内存泄漏。
 *
 * @param duration - 消息自动消失的持续时间（毫秒），默认 3000ms
 * @returns message 当前通知消息（null 表示无消息）和 showNotification 显示通知的方法
 *
 * 使用示例:
 *   const { message, showNotification } = useNotification()
 *   showNotification({ type: 'success', text: '保存成功' })
 */
export function useNotification(duration: number = 3000) {
  const [message, setMessage] = useState<NotificationMessage | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  /** 清除当前定时器，防止消息覆盖时旧定时器干扰 */
  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  /** 显示一条通知消息，自动在指定时间后清除 */
  const showNotification = useCallback(
    (msg: NotificationMessage) => {
      clearTimer()
      setMessage(msg)
      timerRef.current = setTimeout(() => {
        setMessage(null)
        timerRef.current = null
      }, duration)
    },
    [duration, clearTimer],
  )

  /** 组件卸载时清理定时器，防止内存泄漏 */
  useEffect(() => {
    return () => clearTimer()
  }, [clearTimer])

  return { message, showNotification }
}
