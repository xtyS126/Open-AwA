/**
 * 苏格拉底式探针卡片组件。
 * 检测到 pending 探针时展示，每个探针显示 probe_question（或 hypothesis 兜底），
 * 提供"确认/拒绝"两个操作。响应后由父组件从列表中移除该探针。
 *
 * 纯展示组件：所有数据与回调均由父组件传入，使用 React.memo 避免无关重渲染。
 */
import React from 'react'
import type { InterestProbe, ProbeResponse } from './UserProfileApi'
import styles from './UserProfileProbe.module.css'

interface UserProfileProbeProps {
  /** pending 状态的探针列表 */
  probes: InterestProbe[]
  /** 响应探针的回调（确认/拒绝） */
  onRespond: (probeId: number, response: ProbeResponse) => void
  /** 当前正在响应的探针 ID（用于禁用按钮，避免重复提交） */
  respondingProbeId: number | null
}

/** 格式化探针创建时间为本地可读字符串 */
function formatProbeDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateStr
  }
}

function UserProfileProbeImpl({
  probes,
  onRespond,
  respondingProbeId,
}: UserProfileProbeProps) {
  if (probes.length === 0) {
    return null
  }

  return (
    <section className={styles['probe-section']} aria-label="待确认的兴趣探针">
      <div className={styles['section-header']}>
        <h3 className={styles['section-title']}>
          AI 想向你确认几件事
        </h3>
        <span className={styles['probe-count']}>{probes.length} 个待确认</span>
      </div>

      <div className={styles['probe-list']}>
        {probes.map((probe) => {
          const isResponding = respondingProbeId === probe.id
          const question = probe.probe_question?.trim() || probe.hypothesis
          return (
            <article key={probe.id} className={styles['probe-item']}>
              <div className={styles['probe-content']}>
                <p className={styles['probe-question']}>{question}</p>
                {probe.probe_question && probe.hypothesis && (
                  <p className={styles['probe-hypothesis']}>
                    背景：{probe.hypothesis}
                  </p>
                )}
                <span className={styles['probe-meta']}>
                  生成于 {formatProbeDate(probe.created_at)}
                </span>
              </div>

              <div className={styles['probe-actions']}>
                <button
                  type="button"
                  className={styles['confirm-btn']}
                  onClick={() => onRespond(probe.id, 'confirmed')}
                  disabled={isResponding}
                  aria-label="确认此探针"
                >
                  确认
                </button>
                <button
                  type="button"
                  className={styles['reject-btn']}
                  onClick={() => onRespond(probe.id, 'rejected')}
                  disabled={isResponding}
                  aria-label="拒绝此探针"
                >
                  拒绝
                </button>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}

const UserProfileProbe = React.memo(UserProfileProbeImpl)
export default UserProfileProbe
