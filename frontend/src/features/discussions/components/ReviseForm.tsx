/**
 * ReviseForm 修订表单组件。
 *
 * 仅在状态为 `discussing` 或 `pending_approval` 且 `round < max_rounds` 时启用。
 * 字段：proposed_action.type、proposed_action.payload、reason（必填）。
 *
 * 提交调用 store.reviseTask，成功后清空表单并触发刷新。
 * 使用 zod 进行表单校验，错误信息显示在字段下方。
 *
 * [SAFE] 表单提交时使用 AbortController 取消未完成请求，
 * 组件卸载时清理定时器与请求，避免内存泄漏。
 */
import React, { useEffect, useRef, useState } from 'react'
import { z } from 'zod'
import { Input, Textarea, Button } from '@/shared/components/ui'
import { useI18nStore } from '@/i18n'
import { useDiscussionStore } from '../store/discussionStore'
import type { ProposedAction } from '@/shared/api/discussionsApi'
import styles from './ReviseForm.module.css'

interface ReviseFormProps {
  /** 讨论任务 ID */
  discussionId: string
  /** 当前轮次 */
  currentRound: number
  /** 最大轮次 */
  maxRounds: number
  /** 当前状态 */
  status: string
  /** 初始 proposed_action（用于回填表单） */
  initialProposedAction?: ProposedAction
}

/** 动作类型白名单（与后端 pattern 一致） */
const ACTION_TYPES = [
  'plugin_command',
  'tool_call',
  'subagent_delegate',
] as const

/** zod 校验 schema */
const reviseSchema = z.object({
  actionType: z.enum(ACTION_TYPES, {
    errorMap: () => ({ message: '请选择有效的动作类型' }),
  }),
  actionPayload: z.string().min(1, '动作参数不能为空').refine(
    (val) => {
      try {
        const parsed = JSON.parse(val)
        return typeof parsed === 'object' && parsed !== null
      } catch {
        return false
      }
    },
    { message: '动作参数必须是合法的 JSON 对象' }
  ),
  reason: z.string().min(1, '修订理由不能为空').max(2000, '修订理由最多 2000 字符'),
})

/** 表单值类型 */
interface FormValues {
  actionType: string
  actionPayload: string
  reason: string
}

/** 表单错误类型 */
type FormErrors = Partial<Record<keyof FormValues, string>>

/** 默认动作类型 */
const DEFAULT_ACTION_TYPE = 'plugin_command'

/** 默认动作参数（空 JSON 对象） */
const DEFAULT_ACTION_PAYLOAD = '{}'

/**
 * 判断当前状态是否允许修订。
 *
 * 后端规则：仅 `discussing` 或 `pending_approval` 状态可修订。
 */
function isReviseAllowed(status: string, currentRound: number, maxRounds: number): boolean {
  if (status !== 'discussing' && status !== 'pending_approval') return false
  if (currentRound >= maxRounds) return false
  return true
}

const ReviseForm: React.FC<ReviseFormProps> = ({
  discussionId,
  currentRound,
  maxRounds,
  status,
  initialProposedAction,
}) => {
  const t = useI18nStore((s) => s.t)
  const reviseTask = useDiscussionStore((s) => s.reviseTask)
  const isSubmitting = useDiscussionStore((s) => s.isSubmitting)

  // 表单值
  const [values, setValues] = useState<FormValues>({
    actionType: initialProposedAction?.type ?? DEFAULT_ACTION_TYPE,
    actionPayload: initialProposedAction
      ? JSON.stringify(initialProposedAction.payload, null, 2)
      : DEFAULT_ACTION_PAYLOAD,
    reason: '',
  })
  // 表单错误
  const [errors, setErrors] = useState<FormErrors>({})
  // AbortController，用于组件卸载时取消未完成请求
  const abortControllerRef = useRef<AbortController | null>(null)

  // 初始 proposed_action 变化时重置表单
  useEffect(() => {
    setValues({
      actionType: initialProposedAction?.type ?? DEFAULT_ACTION_TYPE,
      actionPayload: initialProposedAction
        ? JSON.stringify(initialProposedAction.payload, null, 2)
        : DEFAULT_ACTION_PAYLOAD,
      reason: '',
    })
    setErrors({})
  }, [initialProposedAction, discussionId])

  // 组件卸载时取消未完成请求
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
        abortControllerRef.current = null
      }
    }
  }, [])

  const allowed = isReviseAllowed(status, currentRound, maxRounds)

  /** 处理字段变更 */
  const handleChange = (field: keyof FormValues, value: string) => {
    setValues((prev) => ({ ...prev, [field]: value }))
    // 清空该字段错误
    if (errors[field]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }))
    }
  }

  /** 提交表单 */
  const handleSubmit = async () => {
    // zod 校验
    const result = reviseSchema.safeParse(values)
    if (!result.success) {
      const fieldErrors: FormErrors = {}
      for (const issue of result.error.issues) {
        const field = issue.path[0] as keyof FormValues
        if (field && !fieldErrors[field]) {
          fieldErrors[field] = issue.message
        }
      }
      setErrors(fieldErrors)
      return
    }

    // 取消上一个未完成请求
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    abortControllerRef.current = new AbortController()

    try {
      let payload: Record<string, unknown>
      try {
        payload = JSON.parse(values.actionPayload) as Record<string, unknown>
      } catch {
        setErrors({ actionPayload: '动作参数 JSON 解析失败' })
        return
      }

      await reviseTask(discussionId, {
        proposed_action: {
          type: values.actionType,
          payload,
        },
        reason: values.reason,
      })

      // 提交成功后清空表单
      setValues((prev) => ({ ...prev, reason: '' }))
      setErrors({})
    } catch {
      // 错误已由 store 处理，此处仅捕获以避免未处理 Promise 拒绝
      // store.error 会通过 Toast 在父组件展示
    }
  }

  return (
    <div className={styles.container} aria-label={t('discussions.action.revise')}>
      <div className={styles.header}>
        <h3 className={styles.title}>{t('discussions.action.revise')}</h3>
        <span className={styles.roundHint}>
          {t('discussions.round.label', { n: String(currentRound) })}
          {' / '}
          {t('discussions.form.max_rounds')}: {maxRounds}
        </span>
      </div>

      {!allowed && (
        <div className={styles.disabledHint} role="alert">
          {currentRound >= maxRounds
            ? t('discussions.error.revise_failed')
            : t('discussions.stream.disconnected')}
        </div>
      )}

      <div className={styles.form}>
        <Input
          label={t('discussions.form.proposed_action.type')}
          value={values.actionType}
          onChange={(e) => handleChange('actionType', e.target.value)}
          error={errors.actionType}
          disabled={!allowed || isSubmitting}
          aria-label={t('discussions.form.proposed_action.type')}
        />

        <Textarea
          label={t('discussions.form.proposed_action.payload')}
          value={values.actionPayload}
          onChange={(e) => handleChange('actionPayload', e.target.value)}
          error={errors.actionPayload}
          disabled={!allowed || isSubmitting}
          rows={6}
          aria-label={t('discussions.form.proposed_action.payload')}
          placeholder='{"key": "value"}'
        />

        <Textarea
          label={t('discussions.form.reason')}
          value={values.reason}
          onChange={(e) => handleChange('reason', e.target.value)}
          error={errors.reason}
          disabled={!allowed || isSubmitting}
          rows={3}
          aria-label={t('discussions.form.reason')}
        />

        <div className={styles.actions}>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={!allowed || isSubmitting}
            loading={isSubmitting}
            aria-label={t('discussions.form.submit')}
          >
            {t('discussions.form.submit')}
          </Button>
        </div>
      </div>
    </div>
  )
}

export default ReviseForm
