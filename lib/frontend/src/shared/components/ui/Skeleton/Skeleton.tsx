/**
 * Skeleton 骨架屏组件 — 用于加载状态的占位内容。
 * 支持多种变体：text/circular/rectangular，尺寸可自定义。
 */
import styles from './Skeleton.module.css'

type SkeletonVariant = 'text' | 'circular' | 'rectangular'

interface SkeletonProps {
  variant?: SkeletonVariant
  width?: string | number
  height?: string | number
  className?: string
}

function Skeleton({ variant = 'text', width, height, className = '' }: SkeletonProps) {
  const style: Record<string, string | number> = {}
  if (width) style.width = typeof width === 'number' ? `${width}px` : width
  if (height) style.height = typeof height === 'number' ? `${height}px` : height

  return (
    <div
      className={`${styles.skeleton} ${styles[variant]} ${className}`}
      style={style}
      aria-hidden="true"
    />
  )
}

/** 模拟段落骨架：多行文本加载态 */
function SkeletonParagraph({ lines = 3 }: { lines?: number }) {
  return (
    <div className={styles.paragraph} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} variant="text" height={16} width={i === lines - 1 ? '60%' : '100%'} />
      ))}
    </div>
  )
}

/** 模拟卡片骨架：标题 + 内容 + 操作区 */
function SkeletonCard() {
  return (
    <div className={styles.card} aria-hidden="true">
      <Skeleton variant="rectangular" height={160} />
      <div className={styles.cardBody}>
        <Skeleton variant="text" height={20} width="70%" />
        <SkeletonParagraph lines={2} />
      </div>
    </div>
  )
}

Skeleton.Paragraph = SkeletonParagraph
Skeleton.Card = SkeletonCard

export { Skeleton }
export type { SkeletonProps, SkeletonVariant }
