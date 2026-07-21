/**
 * Tooltip 文字提示组件 — 纯 CSS 实现，基于伪元素展示提示内容。
 * 支持 top / bottom / left / right 四个方向。
 */
import React from 'react'
import styles from './Tooltip.module.css'

type TooltipPosition = 'top' | 'bottom' | 'left' | 'right'

interface TooltipProps {
  content: string
  position?: TooltipPosition
  children: React.ReactNode
  className?: string
}

const Tooltip: React.FC<TooltipProps> = ({
  content,
  position = 'top',
  children,
  className = '',
}) => {
  return (
    <span
      className={[styles.wrapper, styles[position], className].filter(Boolean).join(' ')}
      data-tip={content}
    >
      {children}
    </span>
  )
}

export { Tooltip }
export type { TooltipProps, TooltipPosition }
