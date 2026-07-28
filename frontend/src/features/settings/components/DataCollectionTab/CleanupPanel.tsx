/**
 * 清理历史数据面板组件
 */
import styles from '@/features/settings/SettingsPage.module.css'

interface CleanupPanelProps {
  /** 清理天数 */
  cleanupDays: number
  /** 是否正在清理 */
  cleaningRecords: boolean

  /** 清理天数变更回调 */
  onCleanupDaysChange: (days: number) => void
  /** 清理回调 */
  onCleanupRecords: () => void
}

export function CleanupPanel({
  cleanupDays,
  cleaningRecords,
  onCleanupDaysChange,
  onCleanupRecords,
}: CleanupPanelProps) {
  const handleCleanup = () => {
    if (!confirm(`确认清理 ${cleanupDays} 天前的记录吗？`)) {
      return
    }
    onCleanupRecords()
  }

  return (
    <div className={styles['collection-cleanup-panel']}>
      <h3>清理历史数据</h3>
      <div className={styles['form-row']}>
        <div className={styles['form-group']}>
          <label>删除早于以下天数的记录</label>
          <input
            type="number"
            min={0}
            max={3650}
            value={cleanupDays}
            onChange={(e) => onCleanupDaysChange(parseInt(e.target.value) || 30)}
          />
        </div>
      </div>
      <button
        className={`btn ${styles['btn-danger']}`}
        onClick={handleCleanup}
        disabled={cleaningRecords}
      >
        {cleaningRecords ? '清理中...' : '执行清理'}
      </button>
    </div>
  )
}

export default CleanupPanel
