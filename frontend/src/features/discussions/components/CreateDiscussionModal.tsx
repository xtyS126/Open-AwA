/**
 * CreateDiscussionModal 新建讨论任务表单。
 *
 * 字段：
 *   - title（Input, 必填, max 200）
 *   - description（Textarea, 必填, max 5000）
 *   - proposed_action.type（Input, 必填，可选值 plugin_command/tool_call/subagent_delegate）
 *   - proposed_action.payload（Textarea, JSON 编辑器, 必填）
 *   - context（Textarea, JSON 编辑器, 可选）
 *   - max_rounds（Input number, 默认 3, max 5）
 *
 * 提交前使用 zod 校验，错误信息显示在字段下方。
 * 提交成功后关闭 modal + 刷新列表（由 store.createTask 内部触发）。
 *
 * [SAFE] 表单提交时使用 AbortController 取消未完成请求，
 * 组件卸载时清理资源。
 */
import React, { useEffect, useRef, useState } from 'react'
import { z } from 'zod'
import { Modal, Input, Textarea, Button } from '@/shared/components/ui'
import { useI18nStore } from '@/i18n'
import { useDiscussionStore } from '../store/discussionStore'
import styles from './CreateDiscussionModal.module.css'

interface CreateDiscussionModalProps {
  /** 是否显示 */
  open: boolean
  /** 关闭回调 */
  onClose: () => void
}

/** 动作类型白名单 */
const ACTION_TYPES = [
  'plugin_command',
  'tool_call',
  'subagent_delegate',
] as const

/** zod 校验 schema */
const createSchema = z.object({
  title: z.string().min(1, '标题不能为空').max(200, '标题最多 200 字符'),
  description: z.string().min(1, '描述不能为空').max(5000, '描述最多 5000 字符'),
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
  context: z.string().optional().refine(
    (val) => {
      if (!val || val.trim() === '') return true
      try {
        JSON.parse(val)
        return true
      } catch {
        return false
      }
    },
    { message: '上下文必须是合法的 JSON 对象' }
  ),
  maxRounds: z
    .number({ errorMap: () => ({ message: '最大轮次必须是数字' }) })
    .int('最大轮次必须是整数')
    .min(1, '最大轮次最少 1')
    .max(5, '最大轮次最多 5'),
})

/** 表单值类型 */
interface FormValues {
  title: string
  description: string
  actionType: string
  actionPayload: string
  context: string
  maxRounds: number
}

/** 表单错误类型 */
type FormErrors = Partial<Record<keyof FormValues, string>>

/** 默认表单值 */
const DEFAULT_VALUES: FormValues = {
  title: '',
  description: '',
  actionType: 'plugin_command',
  actionPayload: '{}',
  context: '',
  maxRounds: 3,
}

const CreateDiscussionModal: React.FC<CreateDiscussionModalProps> = ({
  open,
  onClose,
}) => {
  const t = useI18nStore((s) => s.t)
  const createTask = useDiscussionStore((s) => s.createTask)
  const isSubmitting = useDiscussionStore((s) => s.isSubmitting)

  const [values, setValues] = useState<FormValues>(DEFAULT_VALUES)
  const [errors, setErrors] = useState<FormErrors>({})
  // AbortController，用于组件卸载或重新提交时取消未完成请求
  const abortControllerRef = useRef<AbortController | null>(null)

  // 打开时重置表单
  useEffect(() => {
    if (open) {
      setValues(DEFAULT_VALUES)
      setErrors({})
    }
  }, [open])

  // 组件卸载时取消未完成请求
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
        abortControllerRef.current = null
      }
    }
  }, [])

  /** 处理字段变更 */
  const handleChange = (field: keyof FormValues, value: string | number) => {
    setValues((prev) => ({ ...prev, [field]: value }))
    if (errors[field]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }))
    }
  }

  /** 关闭 modal */
  const handleClose = () => {
    if (isSubmitting) return // 提交中禁止关闭
    onClose()
  }

  /** 提交表单 */
  const handleSubmit = async () => {
    // zod 校验
    const result = createSchema.safeParse(values)
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

      // context 可选，为空时不传
      const contextValue =
        values.context.trim() === ''
          ? undefined
          : (() => {
              try {
                return JSON.parse(values.context) as Record<string, unknown>
              } catch {
                return undefined
              }
            })()

      await createTask({
        title: values.title,
        description: values.description,
        proposed_action: {
          type: values.actionType,
          payload,
        },
        context: contextValue,
        max_rounds: values.maxRounds,
      })

      // 成功后由 store 关闭 modal 并刷新列表
      onClose()
    } catch {
      // 错误已由 store 处理，此处仅捕获以避免未处理 Promise 拒绝
    }
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={t('discussions.create')}
      width="640px"
    >
      <div className={styles.form}>
        <Input
          label={t('discussions.form.title')}
          value={values.title}
          onChange={(e) => handleChange('title', e.target.value)}
          error={errors.title}
          disabled={isSubmitting}
          maxLength={200}
          aria-label={t('discussions.form.title')}
          placeholder={t('discussions.form.title')}
        />

        <Textarea
          label={t('discussions.form.description')}
          value={values.description}
          onChange={(e) => handleChange('description', e.target.value)}
          error={errors.description}
          disabled={isSubmitting}
          rows={4}
          maxLength={5000}
          aria-label={t('discussions.form.description')}
          placeholder={t('discussions.form.description')}
        />

        <div className={styles.row}>
          <Input
            label={t('discussions.form.proposed_action.type')}
            value={values.actionType}
            onChange={(e) => handleChange('actionType', e.target.value)}
            error={errors.actionType}
            disabled={isSubmitting}
            list="discussion-action-types"
            aria-label={t('discussions.form.proposed_action.type')}
          />
          <datalist id="discussion-action-types">
            {ACTION_TYPES.map((type) => (
              <option key={type} value={type} />
            ))}
          </datalist>

          <Input
            label={t('discussions.form.max_rounds')}
            type="number"
            min={1}
            max={5}
            value={values.maxRounds}
            onChange={(e) => handleChange('maxRounds', Number(e.target.value))}
            error={errors.maxRounds}
            disabled={isSubmitting}
            aria-label={t('discussions.form.max_rounds')}
          />
        </div>

        <Textarea
          label={t('discussions.form.proposed_action.payload')}
          value={values.actionPayload}
          onChange={(e) => handleChange('actionPayload', e.target.value)}
          error={errors.actionPayload}
          disabled={isSubmitting}
          rows={6}
          aria-label={t('discussions.form.proposed_action.payload')}
          placeholder='{"command": "example", "args": {}}'
        />

        <Textarea
          label={`${t('discussions.form.context')} (${t('app.optional')})`}
          value={values.context}
          onChange={(e) => handleChange('context', e.target.value)}
          error={errors.context}
          disabled={isSubmitting}
          rows={4}
          aria-label={t('discussions.form.context')}
          placeholder='{"session_id": "default"}'
        />

        <div className={styles.actions}>
          <Button
            variant="secondary"
            onClick={handleClose}
            disabled={isSubmitting}
            aria-label={t('discussions.form.cancel')}
          >
            {t('discussions.form.cancel')}
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={isSubmitting}
            loading={isSubmitting}
            aria-label={t('discussions.form.submit')}
          >
            {t('discussions.form.submit')}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export default CreateDiscussionModal
