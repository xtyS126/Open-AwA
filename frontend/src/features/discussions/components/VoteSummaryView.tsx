/**
 * VoteSummary 投票摘要可视化组件。
 *
 * 展示三个角色（critic / validator / approver）的最新投票状态。
 * 三态图标：
 *   - 待投票：灰色 Clock 图标
 *   - 已通过：绿色 Check 图标
 *   - 已拒绝：红色 X 图标
 *   - 弃权：黄色 Minus 图标
 *
 * 每个角色一行：图标 + 角色名 + 投票决策 + 理由摘要（hover Tooltip 显示完整理由）。
 *
 * [NOTE] 组件名 VoteSummaryView 是为避免与 discussionsApi.ts 中
 * 已导出的 VoteSummary 类型冲突。
 */
import React, { useMemo } from 'react'
import { Check, X, Minus, Clock } from 'lucide-react'
import { Tooltip } from '@/shared/components/ui'
import { useI18nStore } from '@/i18n'
import type {
  DiscussionRole,
  VoteDecision,
  VoteSummary as VoteSummaryData,
} from '@/shared/api/discussionsApi'
import styles from './VoteSummaryView.module.css'

interface VoteSummaryViewProps {
  /** 各角色最新投票摘要 */
  votes: VoteSummaryData | undefined
  /** 当前轮次，用于显示「第 N 轮」上下文 */
  currentRound: number
}

/** 角色固定展示顺序：critic -> validator -> approver */
const ROLE_ORDER: DiscussionRole[] = ['critic', 'validator', 'approver']

/** 投票决策 -> 图标与样式映射 */
const VOTE_ICON_MAP: Record<
  VoteDecision,
  { Icon: typeof Check; className: string }
> = {
  approve: { Icon: Check, className: styles.approve },
  reject: { Icon: X, className: styles.reject },
  abstain: { Icon: Minus, className: styles.abstain },
}

/**
 * 渲染单个角色的投票行。
 *
 * 无投票记录时显示「待投票」灰色 Clock 图标 + 「待投票」文案。
 */
const VoteRow: React.FC<{
  role: DiscussionRole
  vote: VoteSummaryData[DiscussionRole]
  t: (key: string, params?: Record<string, string>) => string
}> = React.memo(function VoteRow({ role, vote, t }) {
  const roleLabel = t(`discussions.role.${role}`)

  if (!vote) {
    return (
      <div className={styles.row} role="listitem">
        <Clock size={16} className={styles.pending} aria-hidden="true" />
        <span className={styles.roleName}>{roleLabel}</span>
        <span className={`${styles.decision} ${styles.pendingText}`}>
          {t('discussions.vote.pending')}
        </span>
      </div>
    )
  }

  const { Icon, className } = VOTE_ICON_MAP[vote.vote]
  const decisionLabel = t(`discussions.vote.${vote.vote}`)
  const reasonText = vote.reason ?? ''
  const truncatedReason = reasonText.length > 50 ? `${reasonText.slice(0, 50)}...` : reasonText

  const rowContent = (
    <div className={styles.row} role="listitem">
      <Icon size={16} className={className} aria-hidden="true" />
      <span className={styles.roleName}>{roleLabel}</span>
      <span className={`${styles.decision} ${className}`}>{decisionLabel}</span>
      {truncatedReason && (
        <span className={styles.reason} aria-label={t('discussions.form.reason')}>
          {truncatedReason}
        </span>
      )}
    </div>
  )

  // 完整理由通过 Tooltip 显示
  if (reasonText.length > 50) {
    return (
      <Tooltip content={reasonText} position="top">
        {rowContent}
      </Tooltip>
    )
  }

  return rowContent
})

const VoteSummaryView: React.FC<VoteSummaryViewProps> = ({ votes, currentRound }) => {
  const t = useI18nStore((s) => s.t)

  // 角色投票映射，便于按顺序遍历
  const roleVoteMap = useMemo<Record<DiscussionRole, VoteSummaryData[DiscussionRole]>>(() => ({
    critic: votes?.critic,
    validator: votes?.validator,
    approver: votes?.approver,
  }), [votes])

  return (
    <div className={styles.container} role="list" aria-live="polite">
      <div className={styles.header}>
        <span className={styles.roundLabel}>
          {t('discussions.round.label', { n: String(currentRound) })}
        </span>
      </div>
      {ROLE_ORDER.map((role) => (
        <VoteRow
          key={role}
          role={role}
          vote={roleVoteMap[role]}
          t={t}
        />
      ))}
    </div>
  )
}

export default React.memo(VoteSummaryView)
