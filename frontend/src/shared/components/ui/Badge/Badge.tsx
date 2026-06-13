/**
 * Badge 徽标组件 — 用于展示状态标记或文字标签。
 * 支持 4 种语义变体和 2 种展示模式（dot / text）。
 */
import React from 'react'
import styles from './Badge.module.css'

type BadgeVariant = 'primary' | 'success' | 'warning' | 'error'
type BadgeMode = 'dot' | 'text'

interface BadgeProps {
  variant?: BadgeVariant
  mode?: BadgeMode
  text?: string
  className?: string
}

const variantMap: Record<BadgeVariant, string> = {
  primary: styles.primary,
  success: styles.success,
  warning: styles.warning,
  error: styles.error,
}

const Badge: React.FC<BadgeProps> = ({
  variant = 'primary',
  mode = 'text',
  text = '',
  className = '',
}) => {
  const variantClass = variantMap[variant]

  if (mode === 'dot') {
    return (
      <span
        className={[styles.dot, variantClass, className].filter(Boolean).join(' ')}
        aria-hidden="true"
      />
    )
  }

  return (
    <span
      className={[styles.text, variantClass, className].filter(Boolean).join(' ')}
    >
      {text}
    </span>
  )
}

export { Badge }
export type { BadgeProps, BadgeVariant, BadgeMode }
