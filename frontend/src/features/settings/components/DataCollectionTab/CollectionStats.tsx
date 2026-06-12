/**
 * 数据采集统计卡片组件
 */
import type { ConversationCollectionStatusResponse } from '@/shared/api/api'
import styles from '@/features/settings/SettingsPage.module.css'

interface CollectionStatsProps {
  /** 统计数据 */
  stats: ConversationCollectionStatusResponse['stats'] | null
}

export function CollectionStats({ stats }: CollectionStatsProps) {
  if (!stats) {
    return null
  }

  return (
    <div className={styles['collection-stats-grid']}>
      <div className={styles['collection-stat-card']}>
        <span className={styles['collection-stat-label']}>队列占用</span>
        <span className={styles['collection-stat-value']}>
          {stats.queue_size} / {stats.queue_maxsize}
        </span>
      </div>
      <div className={styles['collection-stat-card']}>
        <span className={styles['collection-stat-label']}>丢弃数量</span>
        <span className={styles['collection-stat-value']}>{stats.dropped_count}</span>
      </div>
      <div className={styles['collection-stat-card']}>
        <span className={styles['collection-stat-label']}>跟踪用户数</span>
        <span className={styles['collection-stat-value']}>{stats.tracked_user_count}</span>
      </div>
    </div>
  )
}

export default CollectionStats
