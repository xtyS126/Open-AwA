/**
 * Card 卡片组件 — 统一卡片容器。
 * 支持 header/body/footer 三区域插槽。
 */
import { type ReactNode } from 'react'
import styles from './Card.module.css'

interface CardProps {
  children: ReactNode
  className?: string
  onClick?: () => void
}

function Card({ children, className = '', onClick }: CardProps) {
  return (
    <div className={`${styles.card} ${className}`} onClick={onClick} role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined}>
      {children}
    </div>
  )
}

export { Card }
export type { CardProps }
