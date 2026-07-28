import type { Probe } from './soulApi'
import styles from './ProbeNotification.module.css'

interface ProbeNotificationProps {
  probes: Probe[]
  onRespond: (probeId: number, status: 'confirmed' | 'rejected') => void
}

export default function ProbeNotification({
  probes,
  onRespond,
}: ProbeNotificationProps) {
  if (probes.length === 0) {
    return null
  }

  return (
    <div className={styles['probe-section']}>
      <h3 className={styles['section-title']}>
        待确认的兴趣探针 ({probes.length})
      </h3>
      <div className={styles['probe-list']}>
        {probes.map((probe) => (
          <div key={probe.id} className={styles['probe-item']}>
            <div className={styles['probe-content']}>
              <p className={styles['probe-question']}>{probe.probe_question}</p>
              <p className={styles['probe-hypothesis']}>
                假设: {probe.hypothesis}
              </p>
              <span className={styles['probe-confidence']}>
                置信度 {Math.round(probe.confidence * 100)}%
              </span>
            </div>
            <div className={styles['probe-actions']}>
              <button
                className={styles['confirm-btn']}
                onClick={() => onRespond(probe.id, 'confirmed')}
                type="button"
              >
                确认
              </button>
              <button
                className={styles['reject-btn']}
                onClick={() => onRespond(probe.id, 'rejected')}
                type="button"
              >
                拒绝
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}