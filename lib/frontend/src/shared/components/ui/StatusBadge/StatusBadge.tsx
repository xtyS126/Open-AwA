/**
 * StatusBadge 状态徽章组件 —— 对齐 Canvas 设计参考。
 * 带圆点指示器的 pill 形状态标签，支持 4 种状态变体。
 */
import React from 'react'
import styles from './StatusBadge.module.css'

type StatusBadgeVariant = 'active' | 'inactive' | 'pending' | 'error'
type StatusBadgeSize = 'sm' | 'md'

interface StatusBadgeProps {
  /** 状态变体 */
  status: StatusBadgeVariant
  /** 自定义文案，未传时使用状态默认文案 */
  label?: string
  /** 尺寸，默认 md */
  size?: StatusBadgeSize
  /** 自定义类名 */
  className?: string
}

// 状态默认文案
const defaultLabelMap: Record<StatusBadgeVariant, string> = {
  active: '运行中',
  inactive: '已停用',
  pending: '等待中',
  error: '异常',
}

const variantClassMap: Record<StatusBadgeVariant, string> = {
  active: styles.active,
  inactive: styles.inactive,
  pending: styles.pending,
  error: styles.error,
}

const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  label,
  size = 'md',
  className = '',
}) => {
  const variantCls = variantClassMap[status]
  const displayLabel = label ?? defaultLabelMap[status]

  const containerCls = [
    styles.badge,
    variantCls,
    styles[size],
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <span className={containerCls} role="status">
      <span className={styles.dot} aria-hidden="true" />
      <span>{displayLabel}</span>
    </span>
  )
}

export { StatusBadge }
export type { StatusBadgeProps, StatusBadgeVariant, StatusBadgeSize }
