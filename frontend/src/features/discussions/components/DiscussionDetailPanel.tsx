/**
 * DiscussionDetailPanel 讨论任务详情面板。
 *
 * 展示完整讨论历史（按轮次分组），每轮显示三个角色的发言与投票
 * （critic -> validator -> approver 顺序）。
 *
 * 布局：
 *   - 头部：任务标题、状态徽章、proposed_action 类型与 payload 摘要、description 文本
 *   - 中部：实时讨论流（DiscussionStream 组件）
 *   - 底部：根据状态显示不同操作（ReviseForm / 强制执行 / 执行结果）
 *
 * [PERF] 使用 React.memo 优化重渲染，仅在 task/状态变化时重渲染。
 */
import React, { useMemo, useState, useCallback } from 'react'
import { AlertTriangle, Zap, FileText } from 'lucide-react'
import { StatusBadge, type StatusBadgeVariant, Modal, Button } from '@/shared/components/ui'
import { useI18nStore } from '@/i18n'
import { useAuthStore } from '@/shared/store/authStore'
import { useDiscussionStore } from '../store/discussionStore'
import {
  groupVotesByRound,
  type DiscussionStatus,
  type DiscussionTaskDetail,
  type VoteDetail,
} from '@/shared/api/discussionsApi'
import VoteSummaryView from './VoteSummaryView'
import DiscussionStream from './DiscussionStream'
import ReviseForm from './ReviseForm'
import styles from './DiscussionDetailPanel.module.css'

interface DiscussionDetailPanelProps {
  /** 任务详情，null 时显示空状态 */
  task: DiscussionTaskDetail | null
  /** 详情是否加载中 */
  isLoading?: boolean
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

/** 判断状态是否为进行中（订阅 SSE） */
function isLiveStatus(status: DiscussionStatus): boolean {
  return (
    status === 'discussing' ||
    status === 'pending_approval' ||
    status === 'executing' ||
    status === 'created'
  )
}

/** 判断状态是否允许修订 */
function isReviseStatus(status: DiscussionStatus): boolean {
  return status === 'discussing' || status === 'pending_approval'
}

/** 判断当前用户是否为 admin */
function checkIsAdmin(role: string | undefined): boolean {
  return role === 'admin'
}

const DiscussionDetailPanel: React.FC<DiscussionDetailPanelProps> = ({
  task,
  isLoading,
}) => {
  const t = useI18nStore((s) => s.t)
  const user = useAuthStore((s) => s.user)
  const forceExecute = useDiscussionStore((s) => s.forceExecute)
  const isSubmitting = useDiscussionStore((s) => s.isSubmitting)
  const fetchList = useDiscussionStore((s) => s.fetchList)
  const selectTask = useDiscussionStore((s) => s.selectTask)

  // 强制执行确认 modal
  const [isForceExecuteModalOpen, setIsForceExecuteModalOpen] = useState(false)
  const [forceExecuteReason, setForceExecuteReason] = useState('')

  const isAdmin = useMemo(() => checkIsAdmin(user?.role), [user?.role])

  // 按轮次分组的投票记录
  const voteGroups = useMemo(() => {
    if (!task) return []
    return groupVotesByRound(task.votes)
  }, [task])

  // proposed_action payload 摘要（JSON 字符串截断）
  const payloadSummary = useMemo(() => {
    if (!task) return ''
    try {
      const json = JSON.stringify(task.proposed_action.payload)
      return json.length > 200 ? `${json.slice(0, 200)}...` : json
    } catch {
      return String(task.proposed_action.payload)
    }
  }, [task])

  // 处理 SSE 事件回调：刷新详情
  const handleStreamEvent = useCallback(() => {
    if (task) {
      // 收到 vote_cast / status_changed 后刷新详情
      void selectTask(task.id)
      void fetchList()
    }
  }, [task, selectTask, fetchList])

  // 处理强制执行
  const handleForceExecute = useCallback(async () => {
    if (!task) return
    if (!forceExecuteReason.trim()) return
    try {
      await forceExecute(task.id, { reason: forceExecuteReason })
      setIsForceExecuteModalOpen(false)
      setForceExecuteReason('')
    } catch {
      // 错误已由 store 处理
    }
  }, [task, forceExecute, forceExecuteReason])

  // 关闭强制执行 modal
  const handleCloseForceExecuteModal = useCallback(() => {
    if (isSubmitting) return
    setIsForceExecuteModalOpen(false)
    setForceExecuteReason('')
  }, [isSubmitting])

  if (isLoading) {
    return (
      <div className={styles.container} aria-busy="true">
        <p className={styles.loadingText}>{t('app.loading')}</p>
      </div>
    )
  }

  if (!task) {
    return (
      <div className={styles.container}>
        <p className={styles.emptyText}>{t('discussions.empty.no_task_selected')}</p>
      </div>
    )
  }

  const statusBadge: StatusBadgeVariant = STATUS_BADGE_MAP[task.status] ?? 'inactive'
  const statusLabel = t(`discussions.status.${task.status}`)
  const liveStatus = isLiveStatus(task.status)
  const reviseAllowed = isReviseStatus(task.status)
  const showForceExecute = isAdmin && task.status !== 'completed' && task.status !== 'failed' && task.status !== 'approved'

  return (
    <div className={styles.container}>
      {/* 头部：标题 + 状态 + 元信息 */}
      <header className={styles.header}>
        <div className={styles.headerTop}>
          <h2 className={styles.title}>{task.title}</h2>
          <StatusBadge status={statusBadge} label={statusLabel} size="md" />
        </div>
        <p className={styles.description}>{task.description}</p>

        {/* proposed_action 摘要 */}
        <div className={styles.actionSummary}>
          <div className={styles.actionType}>
            <Zap size={14} aria-hidden="true" />
            <span className={styles.actionTypeLabel}>
              {t('discussions.form.proposed_action.type')}:
            </span>
            <code className={styles.actionTypeValue}>{task.proposed_action.type}</code>
          </div>
          <div className={styles.actionPayload}>
            <FileText size={14} aria-hidden="true" />
            <span className={styles.actionTypeLabel}>
              {t('discussions.form.proposed_action.payload')}:
            </span>
            <code className={styles.payloadValue} title={payloadSummary}>
              {payloadSummary}
            </code>
          </div>
        </div>
      </header>

      {/* 中部：实时讨论流（仅进行中状态订阅） */}
      {liveStatus && (
        <section className={styles.streamSection} aria-label={t('discussions.title')}>
          <DiscussionStream
            discussionId={task.id}
            active={liveStatus}
            onEvent={handleStreamEvent}
          />
        </section>
      )}

      {/* 投票历史（按轮次分组） */}
      <section className={styles.historySection} aria-label={t('discussions.title')}>
        <h3 className={styles.sectionTitle}>{t('discussions.title')}</h3>
        {voteGroups.length === 0 ? (
          <p className={styles.emptyText}>{t('discussions.empty.no_tasks')}</p>
        ) : (
          <div className={styles.voteGroups}>
            {voteGroups.map((group) => (
              <div key={group.round} className={styles.voteGroup}>
                <div className={styles.roundHeader}>
                  {t('discussions.round.label', { n: String(group.round) })}
                </div>
                {group.votes.map((vote: VoteDetail) => (
                  <VoteDetailRow key={vote.id} vote={vote} t={t} />
                ))}
              </div>
            ))}
          </div>
        )}

        {/* 最新投票摘要（始终展示当前轮次的最新投票） */}
        <div className={styles.voteSummaryContainer}>
          <VoteSummaryView
            votes={task.vote_summary}
            currentRound={task.round}
          />
        </div>
      </section>

      {/* 底部操作区 */}
      <footer className={styles.footer}>
        {reviseAllowed && (
          <ReviseForm
            discussionId={task.id}
            currentRound={task.round}
            maxRounds={task.max_rounds}
            status={task.status}
            initialProposedAction={task.proposed_action}
          />
        )}

        {showForceExecute && (
          <div className={styles.forceExecuteSection}>
            <Button
              variant="danger"
              onClick={() => setIsForceExecuteModalOpen(true)}
              disabled={isSubmitting}
              aria-label={t('discussions.action.force_execute')}
            >
              <AlertTriangle size={14} />
              {t('discussions.action.force_execute')}
            </Button>
          </div>
        )}

        {/* 执行结果区（completed / failed） */}
        {(task.status === 'completed' || task.status === 'failed') && (
          <div className={styles.resultSection}>
            <h3 className={styles.sectionTitle}>
              {task.status === 'completed'
                ? t('discussions.status.completed')
                : t('discussions.status.failed')}
            </h3>
            {task.completed_at && (
              <p className={styles.completedAt}>
                {new Date(task.completed_at).toLocaleString()}
              </p>
            )}
            <p className={styles.resultText}>
              {task.status === 'completed'
                ? t('discussions.status.completed')
                : t('discussions.status.failed')}
            </p>
          </div>
        )}
      </footer>

      {/* 强制执行确认 modal */}
      <Modal
        open={isForceExecuteModalOpen}
        onClose={handleCloseForceExecuteModal}
        title={t('discussions.action.force_execute')}
        width="480px"
      >
        <div className={styles.forceExecuteForm}>
          <p className={styles.forceExecuteHint} role="alert">
            {t('discussions.action.force_execute_confirm')}
          </p>
          <textarea
            className={styles.forceExecuteReasonInput}
            value={forceExecuteReason}
            onChange={(e) => setForceExecuteReason(e.target.value)}
            placeholder={t('discussions.form.reason')}
            rows={4}
            disabled={isSubmitting}
            aria-label={t('discussions.form.reason')}
          />
          <div className={styles.forceExecuteActions}>
            <Button
              variant="secondary"
              onClick={handleCloseForceExecuteModal}
              disabled={isSubmitting}
            >
              {t('discussions.form.cancel')}
            </Button>
            <Button
              variant="danger"
              onClick={handleForceExecute}
              disabled={isSubmitting || !forceExecuteReason.trim()}
              loading={isSubmitting}
            >
              {t('discussions.action.force_execute')}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

/** 单条投票详情行 */
interface VoteDetailRowProps {
  vote: VoteDetail
  t: (key: string, params?: Record<string, string>) => string
}

const VoteDetailRow: React.FC<VoteDetailRowProps> = React.memo(function VoteDetailRow({
  vote,
  t,
}) {
  const reason = vote.reason ?? ''
  const truncatedReason = reason.length > 100 ? `${reason.slice(0, 100)}...` : reason
  const time = vote.created_at ? new Date(vote.created_at).toLocaleString() : ''

  return (
    <div className={styles.voteDetailRow} role="listitem">
      <div className={styles.voteDetailHeader}>
        <span className={styles.voteRole}>{t(`discussions.role.${vote.role}`)}</span>
        <span className={`${styles.voteDecision} ${styles[`vote_${vote.vote}`]}`}>
          {t(`discussions.vote.${vote.vote}`)}
        </span>
        {time && <time className={styles.voteTime}>{time}</time>}
      </div>
      {truncatedReason && <p className={styles.voteReason}>{truncatedReason}</p>}
    </div>
  )
})

export default React.memo(DiscussionDetailPanel)
