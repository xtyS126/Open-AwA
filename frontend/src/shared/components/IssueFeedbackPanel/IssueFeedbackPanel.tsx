/**
 * 全局问题反馈浮动面板。
 * 挂载在 AppShell 顶层（Outlet 之外），路由切换不卸载。
 * 通过 useIssueFeedbackStore 控制开闭与草稿状态。
 * z-index 9999，覆盖所有覆盖层。
 */
import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { useIssueFeedbackStore } from '@/shared/store/issueFeedbackStore'
import { useI18nStore } from '@/i18n'
import { useToast } from '@/shared/components/Toast'
import { issueFeedbackAPI } from '@/shared/api/issueFeedbackApi'
import type { IssueFeedbackType } from '@/shared/api/types'
import styles from './IssueFeedbackPanel.module.css'

/** 类型下拉选项列表 */
const TYPE_OPTIONS: Array<{ value: IssueFeedbackType; labelKey: string }> = [
  { value: 'bug', labelKey: 'issueFeedback.typeBug' },
  { value: 'suggestion', labelKey: 'issueFeedback.typeSuggestion' },
  { value: 'question', labelKey: 'issueFeedback.typeQuestion' },
  { value: 'other', labelKey: 'issueFeedback.typeOther' },
]

/** 标题最大长度 */
const TITLE_MAX_LENGTH = 200
/** 内容最大长度 */
const CONTENT_MAX_LENGTH = 10000

export default function IssueFeedbackPanel() {
  const { t } = useI18nStore()
  const { addToast, ToastContainer } = useToast()
  const isOpen = useIssueFeedbackStore((s) => s.isOpen)
  const submitting = useIssueFeedbackStore((s) => s.submitting)
  const draft = useIssueFeedbackStore((s) => s.draft)
  const close = useIssueFeedbackStore((s) => s.close)
  const setDraft = useIssueFeedbackStore((s) => s.setDraft)
  const clearDraft = useIssueFeedbackStore((s) => s.clearDraft)
  const setSubmitting = useIssueFeedbackStore((s) => s.setSubmitting)

  /** 是否展示"丢弃草稿"确认对话框 */
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  /** 草稿是否非空（标题或内容任一非空） */
  const isDraftDirty = Boolean(draft.title.trim() || draft.content.trim())

  /**
   * 关闭流程：若草稿非空则弹确认对话框，否则直接关闭。
   */
  const handleClose = () => {
    if (confirmDiscard) return
    if (isDraftDirty) {
      setConfirmDiscard(true)
      return
    }
    close()
  }

  /**
   * 丢弃草稿：清空草稿 + 关闭面板 + 关闭确认对话框。
   */
  const handleDiscard = () => {
    clearDraft()
    close()
    setConfirmDiscard(false)
  }

  /**
   * 保留草稿：仅关闭确认对话框，面板与草稿保持原状。
   */
  const handleKeepDraft = () => {
    setConfirmDiscard(false)
  }

  /**
   * 提交反馈：前端校验非空 -> 调用 API -> 成功清空草稿关闭 / 失败保留草稿。
   */
  const handleSubmit = async () => {
    if (submitting) return
    if (!draft.title.trim()) {
      addToast(t('issueFeedback.titleRequired'), 'warning')
      return
    }
    if (!draft.content.trim()) {
      addToast(t('issueFeedback.contentRequired'), 'warning')
      return
    }
    setSubmitting(true)
    try {
      await issueFeedbackAPI.submit({
        issue_type: draft.issue_type,
        title: draft.title.trim(),
        content: draft.content.trim(),
        page_url: draft.page_url,
      })
      addToast(t('issueFeedback.submitSuccess'), 'success')
      clearDraft()
      close()
    } catch {
      addToast(t('issueFeedback.submitFailed'), 'error')
    } finally {
      setSubmitting(false)
    }
  }

  /** ESC 键关闭：仅在面板打开且未弹确认对话框时触发 */
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !confirmDiscard) {
        handleClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
    // handleClose 依赖 isDraftDirty，但此处只需在 isOpen/confirmDiscard 变化时重新绑定
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, confirmDiscard])

  if (!isOpen) return null

  return (
    <>
      {/* 全屏遮罩，点击关闭 */}
      <div
        className={styles.overlay}
        onClick={handleClose}
        aria-hidden="true"
        data-testid="issue-feedback-overlay"
      />
      <div
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="issue-feedback-title"
        data-testid="issue-feedback-panel"
      >
        <div className={styles.header}>
          <h2 id="issue-feedback-title" className={styles.title}>
            {t('issueFeedback.title')}
          </h2>
          <button
            className={styles.closeBtn}
            onClick={handleClose}
            aria-label={t('issueFeedback.close')}
            type="button"
          >
            <X size={18} />
          </button>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label} htmlFor="issue-feedback-type">
            {t('issueFeedback.typeLabel')}
          </label>
          <select
            id="issue-feedback-type"
            className={styles.select}
            value={draft.issue_type}
            onChange={(e) =>
              setDraft({ issue_type: e.target.value as IssueFeedbackType })
            }
            disabled={submitting}
          >
            {TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {t(opt.labelKey)}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label} htmlFor="issue-feedback-title-input">
            {t('issueFeedback.titleLabel')}
          </label>
          <input
            id="issue-feedback-title-input"
            className={styles.input}
            type="text"
            maxLength={TITLE_MAX_LENGTH}
            value={draft.title}
            onChange={(e) => setDraft({ title: e.target.value })}
            placeholder={t('issueFeedback.titlePlaceholder')}
            disabled={submitting}
          />
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label} htmlFor="issue-feedback-content">
            {t('issueFeedback.contentLabel')}
          </label>
          <textarea
            id="issue-feedback-content"
            className={styles.textarea}
            maxLength={CONTENT_MAX_LENGTH}
            rows={6}
            value={draft.content}
            onChange={(e) => setDraft({ content: e.target.value })}
            placeholder={t('issueFeedback.contentPlaceholder')}
            disabled={submitting}
          />
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>{t('issueFeedback.currentPage')}</label>
          <div className={styles.pageUrl} title={draft.page_url}>
            {draft.page_url || '-'}
          </div>
        </div>

        <div className={styles.footer}>
          <button
            className={styles.cancelButton}
            onClick={handleClose}
            disabled={submitting}
            type="button"
          >
            {t('issueFeedback.cancel')}
          </button>
          <button
            className={styles.submitButton}
            onClick={handleSubmit}
            disabled={submitting}
            type="button"
            data-testid="issue-feedback-submit-btn"
          >
            {t('issueFeedback.submit')}
          </button>
        </div>

        {/* 丢弃草稿确认对话框，覆盖在面板之上 */}
        {confirmDiscard && (
          <div
            className={styles.confirmDialog}
            role="alertdialog"
            aria-labelledby="issue-feedback-discard-title"
            data-testid="issue-feedback-confirm-dialog"
          >
            <p id="issue-feedback-discard-title" className={styles.confirmText}>
              {t('issueFeedback.discardDraftConfirm')}
            </p>
            <div className={styles.confirmActions}>
              <button
                className={styles.cancelButton}
                onClick={handleKeepDraft}
                type="button"
              >
                {t('issueFeedback.keepDraft')}
              </button>
              <button
                className={styles.submitButton}
                onClick={handleDiscard}
                type="button"
              >
                {t('issueFeedback.discardDraft')}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Toast 容器，渲染反馈提示 */}
      <ToastContainer />
    </>
  )
}
