import type { ReactNode } from 'react'
import styles from './LoadingState.module.css'

interface LoadingStateProps {
  loading: boolean
  empty: boolean
  emptyText?: string
  children: ReactNode
}

/* 空状态图标 */
const emptyIcon = (
  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
  </svg>
)

/* 统一的加载/空状态组件 */
function LoadingState({
  loading,
  empty,
  emptyText = '暂无数据',
  children,
}: LoadingStateProps) {
  /* 加载中状态 */
  if (loading) {
    return (
      <div className={styles['loading-wrapper']}>
        <div className={styles['spinner']} />
        <span className={styles['loading-text']}>加载中...</span>
      </div>
    )
  }

  /* 空数据状态 */
  if (empty) {
    return (
      <div className={styles['empty-wrapper']}>
        <span className={styles['empty-icon']}>{emptyIcon}</span>
        <span className={styles['empty-text']}>{emptyText}</span>
      </div>
    )
  }

  /* 正常状态 - 渲染子内容 */
  return <>{children}</>
}

export default LoadingState
