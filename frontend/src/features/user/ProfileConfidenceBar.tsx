/**
 * 置信度分布柱状图——纯 CSS 实现，无需额外图表库。
 */

import styles from './ProfileConfidenceBar.module.css'

interface Props {
  data: Record<string, number>
}

const LEVEL_ORDER = ['高', '中', '低']

function ProfileConfidenceBar({ data }: Props) {
  const total = Object.values(data).reduce((s, v) => s + v, 0) || 1
  const barColors: Record<string, string> = {
    '高': 'var(--color-success, #22c55e)',
    '中': 'var(--color-warning, #f59e0b)',
    '低': 'var(--color-danger, #ef4444)',
  }

  return (
    <div className={styles['bar-container']}>
      {LEVEL_ORDER.filter((level) => data[level] !== undefined).map((level) => {
        const count = data[level] || 0
        const pct = (count / total) * 100
        return (
          <div key={level} className={styles['bar-row']}>
            <span className={styles['bar-label']}>{level}置信度</span>
            <div className={styles['bar-track']}>
              <div
                className={styles['bar-fill']}
                style={{
                  width: `${pct}%`,
                  backgroundColor: barColors[level] || '#6b7280',
                }}
              />
            </div>
            <span className={styles['bar-value']}>{count} 条</span>
          </div>
        )
      })}
    </div>
  )
}

export default ProfileConfidenceBar
