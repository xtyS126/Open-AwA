/**
 * PermissionDialog 权限审批弹窗组件。
 *
 * 当 ACP 流接收到 `permission` 事件时，agent 已暂停并请求用户决策。
 * 本组件渲染权限请求详情（工具名、目标、命令、影响路径等）和可选项列表，
 * 用户点击某选项后回调 onSelect(optionId)，由上层调用 respondPermission 提交。
 */
import { useState } from 'react'
import { Modal } from '@/shared/components/ui'
import { useI18nStore } from '@/i18n'
import type { SuspendedPermission } from '@/shared/api/acpApi'
import styles from './PermissionDialog.module.css'

export interface PermissionDialogProps {
  /** 挂起的权限请求对象 */
  permission: SuspendedPermission
  /** 用户选择某选项后的回调（返回 Promise 以便按钮显示 loading） */
  onSelect: (optionId: string) => Promise<void>
  /** 取消（拒绝）回调 */
  onCancel: () => void
}

/** 权限审批弹窗 —— 展示权限请求详情并渲染可选项按钮 */
export default function PermissionDialog({
  permission,
  onSelect,
  onCancel,
}: PermissionDialogProps) {
  const { t } = useI18nStore()
  // 当前正在提交的选项 ID，用于禁用其他按钮并显示 loading
  const [submittingId, setSubmittingId] = useState<string | null>(null)

  /** 点击某个选项 —— 设置 loading 后调用 onSelect */
  const handleSelect = async (optionId: string) => {
    if (submittingId) return
    setSubmittingId(optionId)
    try {
      await onSelect(optionId)
    } finally {
      setSubmittingId(null)
    }
  }

  const options = permission.options ?? []
  // 是否有命令文本需要展示
  const hasCommand = Boolean(permission.command && permission.command.trim())
  // 是否有影响路径需要展示
  const hasPaths = Array.isArray(permission.paths) && permission.paths.length > 0

  return (
    <Modal
      open
      onClose={onCancel}
      title={t('vibeCoding.permission.title')}
      width="560px"
      footer={
        <div className={styles.footer}>
          <button
            type="button"
            className={styles.cancelBtn}
            onClick={onCancel}
            disabled={submittingId !== null}
          >
            {submittingId !== null ? t('vibeCoding.permission.processing') : t('vibeCoding.permission.cancel')}
          </button>
        </div>
      }
    >
      {/* 标题行：工具名 + kind 徽章 */}
      <div className={styles.headerRow} style={{ marginBottom: 'var(--space-3)' }}>
        {permission.tool_name && (
          <span className={styles.toolName}>{permission.tool_name}</span>
        )}
        {permission.tool_kind && (
          <span className={styles.kindBadge}>{permission.tool_kind}</span>
        )}
      </div>

      {/* 目标 + 动作 —— 仅在对应字段存在时渲染 */}
      {(permission.target || permission.action) && (
        <div className={styles.section} style={{ marginBottom: 'var(--space-3)' }}>
          {permission.target && (
            <div className={styles.kvRow}>
              <span className={styles.kvLabel}>{t('vibeCoding.permission.target')}</span>
              <span className={styles.kvValue}>{permission.target}</span>
            </div>
          )}
          {permission.action && (
            <div className={styles.kvRow}>
              <span className={styles.kvLabel}>{t('vibeCoding.permission.action')}</span>
              <span className={styles.kvValue}>{permission.action}</span>
            </div>
          )}
        </div>
      )}

      {/* 摘要 —— 仅在存在时渲染 */}
      {permission.summary && (
        <div className={styles.section} style={{ marginBottom: 'var(--space-3)' }}>
          <span className={styles.kvLabel}>{t('vibeCoding.permission.summary')}</span>
          <p className={styles.summary}>{permission.summary}</p>
        </div>
      )}

      {/* 命令展示 —— 等宽字体 */}
      {hasCommand && (
        <div className={styles.section} style={{ marginBottom: 'var(--space-3)' }}>
          <span className={styles.kvLabel}>{t('vibeCoding.permission.command')}</span>
          <pre className={styles.command}>{permission.command}</pre>
        </div>
      )}

      {/* 影响路径列表 */}
      {hasPaths && (
        <div className={styles.section} style={{ marginBottom: 'var(--space-3)' }}>
          <span className={styles.kvLabel}>{t('vibeCoding.permission.paths')}</span>
          <ul className={styles.pathList}>
            {permission.paths!.map((p, idx) => (
              <li key={`${idx}-${p}`} className={styles.pathItem}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 选项列表 */}
      <span className={styles.optionsTitle}>{t('vibeCoding.permission.selectOption')}</span>
      <ul className={styles.options} style={{ marginTop: 'var(--space-2)' }}>
        {options.map((opt) => {
          const isSubmitting = submittingId === opt.id
          const isDisabled = submittingId !== null && !isSubmitting
          return (
            <li key={opt.id}>
              <button
                type="button"
                className={styles.option}
                onClick={() => { void handleSelect(opt.id) }}
                disabled={isDisabled}
              >
                <span className={styles.optionLabel}>
                  <span>{opt.label}</span>
                  <span className={styles.optionKind}>{opt.kind}</span>
                </span>
                {opt.hint && <span className={styles.optionHint}>{opt.hint}</span>}
                {isSubmitting && (
                  <span className={styles.optionHint}>
                    {t('vibeCoding.permission.processing')}
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </Modal>
  )
}
