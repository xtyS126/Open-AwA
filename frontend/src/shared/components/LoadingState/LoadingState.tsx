import type { ReactNode } from 'react'
import { PackageOpen } from 'lucide-react'
import styles from './LoadingState.module.css'

interface LoadingStateProps {
  loading: boolean
  empty: boolean
  emptyText?: string
  children: ReactNode
}

/* 空状态图标 */
const emptyIcon = <PackageOpen size={48} strokeWidth={1.5} />

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
