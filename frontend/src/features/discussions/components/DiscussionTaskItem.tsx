/**
 * DiscussionTaskItem 任务列表项卡片。
 *
 * 展示：标题、状态徽章、轮次（第 N 轮）、最新投票摘要。
 * hover 高亮 + 点击选中，选中状态用边框颜色区分。
 *
 * [PERF] 使用 React.memo 优化重渲染，仅在 task/isSelected 变化时重渲染。
 */
import React, { useMemo } from 'react'
import { StatusBadge, type StatusBadgeVariant } from '@/shared/components/ui'
import { useI18nStore } from '@/i18n'
import type {
  DiscussionStatus,
  DiscussionTaskListItem,
  VoteSummary as VoteSummaryData,
} from '@/shared/api/discussionsApi'
import styles from './DiscussionTaskItem.module.css'

interface DiscussionTaskItemProps {
  /** 任务列表项数据 */
  task: DiscussionTaskListItem
  /** 是否选中 */
  isSelected: boolean
  /** 点击回调 */
  onClick: (id: string) => void
}

/** 讨论状态 -> StatusBadge 变体映射 */
const STATUS_BADGE_MAP: Record<DiscussionStatus, StatusBadgeVariant> = {
  created: 'pending',
  discussing: 'active',
  pending_approval: 'pending',
  approved: 'active',
  rejected: 'error',
  executing: 'active',
  completed: 'inactive',
  failed: 'error',
}

/** 投票摘要预览：返回三个角色的投票决策字符（用于一行展示） */
function formatVotePreview(
  voteSummary: VoteSummaryData | undefined
): { critic?: string; validator?: string; approver?: string } {
  if (!voteSummary) return {}
  return {
    critic: voteSummary.critic?.vote,
    validator: voteSummary.validator?.vote,
    approver: voteSummary.approver?.vote,
  }
}

const DiscussionTaskItem: React.FC<DiscussionTaskItemProps> = ({
  task,
  isSelected,
  onClick,
}) => {
  const t = useI18nStore((s) => s.t)

  // 计算状态徽章
  const statusBadge = useMemo(() => {
    const variant = STATUS_BADGE_MAP[task.status] ?? 'inactive'
    const label = t(`discussions.status.${task.status}`)
    return { variant, label }
  }, [task.status, t])

  // 投票摘要预览
  const votePreview = useMemo(
    () => formatVotePreview(task.vote_summary),
    [task.vote_summary]
  )

  // 创建时间格式化
  const createdAt = useMemo(() => {
    if (!task.created_at) return ''
    try {
      return new Date(task.created_at).toLocaleString()
    } catch {
      return task.created_at
    }
  }, [task.created_at])

  // 单个投票决策的小徽标颜色
  const voteBadgeClass = (vote?: string): string => {
    if (!vote) return styles.votePending
    if (vote === 'approve') return styles.voteApprove
    if (vote === 'reject') return styles.voteReject
    if (vote === 'abstain') return styles.voteAbstain
    return styles.votePending
  }

  return (
    <div
      className={`${styles.item} ${isSelected ? styles.selected : ''}`}
      onClick={() => onClick(task.id)}
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      aria-label={`${task.title} - ${statusBadge.label}`}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick(task.id)
        }
      }}
    >
      <div className={styles.header}>
        <h4 className={styles.title} title={task.title}>
          {task.title}
        </h4>
        <StatusBadge status={statusBadge.variant} label={statusBadge.label} size="sm" />
      </div>

      <div className={styles.meta}>
        <span className={styles.round}>
          {t('discussions.round.label', { n: String(task.round) })}
          {' / '}
          {task.max_rounds}
        </span>
        {createdAt && (
          <>
            <span className={styles.divider} aria-hidden="true">|</span>
            <time className={styles.time} dateTime={task.created_at ?? undefined}>
              {createdAt}
            </time>
          </>
        )}
      </div>

      <div className={styles.votePreview} aria-label={t('discussions.role.critic')}>
        <span className={`${styles.voteBadge} ${voteBadgeClass(votePreview.critic)}`}>
          {votePreview.critic ? t(`discussions.vote.${votePreview.critic}`) : t('discussions.vote.pending')}
        </span>
        <span className={styles.voteDivider} aria-hidden="true">·</span>
        <span className={`${styles.voteBadge} ${voteBadgeClass(votePreview.validator)}`}>
          {votePreview.validator ? t(`discussions.vote.${votePreview.validator}`) : t('discussions.vote.pending')}
        </span>
        <span className={styles.voteDivider} aria-hidden="true">·</span>
        <span className={`${styles.voteBadge} ${voteBadgeClass(votePreview.approver)}`}>
          {votePreview.approver ? t(`discussions.vote.${votePreview.approver}`) : t('discussions.vote.pending')}
        </span>
      </div>
    </div>
  )
}

export default React.memo(DiscussionTaskItem)
