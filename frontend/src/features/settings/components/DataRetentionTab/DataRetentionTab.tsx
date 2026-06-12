/**
 * 数据保留设置组件
 * 配置计费数据的保留天数，超出保留期限的数据将被自动清理
 */
import { useEffect } from 'react'
import type { RetentionConfig } from '@/features/billing/billingApi'
import styles from '@/features/settings/SettingsPage.module.css'

interface DataRetentionTabProps {
  /** 是否正在加载 */
  loadingRetention: boolean
  /** 保留配置数据 */
  retentionConfig: RetentionConfig | null
  /** 保留天数 */
  retentionDays: number
  /** 是否保存后清理旧数据 */
  cleanupOld: boolean
  /** 是否正在保存 */
  saving: boolean

  /** 加载保留配置回调 */
  onLoadRetentionConfig: () => void
  /** 保存保留配置回调 */
  onSaveRetention: () => void
  /** 保留天数变更回调 */
  onRetentionDaysChange: (days: number) => void
  /** 清理旧数据勾选变更回调 */
  onCleanupOldChange: (checked: boolean) => void
}

export function DataRetentionTab({
  loadingRetention,
  retentionConfig,
  retentionDays,
  cleanupOld,
  saving,
  onLoadRetentionConfig,
  onSaveRetention,
  onRetentionDaysChange,
  onCleanupOldChange,
}: DataRetentionTabProps) {
  useEffect(() => {
    onLoadRetentionConfig()
  }, [onLoadRetentionConfig])

  const handleRetentionDaysChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseInt(e.target.value, 10)
    if (!isNaN(value)) {
      onRetentionDaysChange(value)
    }
  }

  return (
    <div className={styles['settings-section']}>
      <h2>数据保留设置</h2>
      <p className={styles['section-desc']}>
        配置计费数据的保留天数，超出保留期限的数据将被自动清理
      </p>

      {loadingRetention ? (
        <div className={styles['loading']}>加载中...</div>
      ) : (
        <>
          <div className={styles['setting-item']}>
            <label>最大保存天数</label>
            <input
              type="number"
              value={retentionDays}
              onChange={handleRetentionDaysChange}
              min={1}
              max={3650}
              style={{ width: '150px' }}
            />
            <span style={{ marginLeft: '8px', color: 'var(--color-text-secondary)', fontSize: '14px' }}>
              天（范围：1-3650）
            </span>
          </div>

          {retentionConfig && (
            <div className={styles['setting-item']}>
              <label>当前数据状态</label>
              <div style={{ fontSize: '14px', color: 'var(--color-text-secondary)', marginTop: '8px' }}>
                <p>总记录数：{retentionConfig.total_records}</p>
                <p>
                  数据范围：
                  {retentionConfig.oldest_record
                    ? new Date(retentionConfig.oldest_record).toLocaleDateString('zh-CN')
                    : '无'}
                  {' - '}
                  {retentionConfig.newest_record
                    ? new Date(retentionConfig.newest_record).toLocaleDateString('zh-CN')
                    : '无'}
                </p>
              </div>
            </div>
          )}

          <div className={`${styles['setting-item']} ${styles['checkbox']}`}>
            <input
              type="checkbox"
              id="cleanup-old"
              checked={cleanupOld}
              onChange={(e) => onCleanupOldChange(e.target.checked)}
            />
            <label htmlFor="cleanup-old">
              保存后清理超出保留期限的旧数据
            </label>
          </div>

          <button
            className={`btn btn-primary`}
            onClick={onSaveRetention}
            disabled={saving}
          >
            {saving ? '保存中...' : '保存设置'}
          </button>
        </>
      )}
    </div>
  )
}

export default DataRetentionTab
