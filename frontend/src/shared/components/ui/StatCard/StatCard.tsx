/**
 * StatCard 统计卡片组件 —— 对齐 Canvas dashboard 的统计卡片模式。
 * 顶部一行（标签 + 图标），中部大号数值，底部可选趋势徽章。
 */
import React, { useMemo } from 'react'
import styles from './StatCard.module.css'

interface StatCardProps {
  /** 标签文字（如：今日交互） */
  label: string
  /** 主要数值，支持字符串或数字 */
  value: string | number
  /** 右上角图标节点（建议 18x18） */
  icon?: React.ReactNode
  /** 底部趋势徽章节点（推荐使用 Badge 组件） */
  trend?: React.ReactNode
  /** 图标强调色（CSS 颜色值或 var() 引用），不传则使用默认主色 */
  accentColor?: string
  /** 自定义类名 */
  className?: string
}

const StatCard: React.FC<StatCardProps> = ({
  label,
  value,
  icon,
  trend,
  accentColor,
  className = '',
}) => {
  // 仅在传入 accentColor 时生成内联样式，避免每次渲染都生成对象
  const iconStyle = useMemo<React.CSSProperties | undefined>(() => {
    if (!accentColor) return undefined
    return { color: accentColor }
  }, [accentColor])

  const containerCls = [styles.statCard, className].filter(Boolean).join(' ')

  return (
    <div className={containerCls}>
      {/* 顶部行 —— 标签 + 图标 */}
      <div className={styles.topRow}>
        <span className={styles.label}>{label}</span>
        {icon ? (
          <span className={styles.icon} style={iconStyle}>
            {icon}
          </span>
        ) : null}
      </div>
      {/* 大号数值 */}
      <div className={styles.value}>{value}</div>
      {/* 底部趋势徽章（可选） */}
      {trend ? <div className={styles.trend}>{trend}</div> : null}
    </div>
  )
}

export { StatCard }
export type { StatCardProps }
