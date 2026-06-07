/**
 * 权限请求弹窗组件。
 * 当 Agent 需要执行需要用户确认的操作时显示，
 * 提供 Allow（允许一次）、Always Allow（始终允许）、Deny（拒绝）三个操作。
 */
import { useState } from 'react'
import type { PermissionRequest } from '@/shared/api/securityApi'
import { appLogger } from '@/shared/utils/logger'
import styles from './PermissionDialog.module.css'

interface PermissionDialogProps {
  /** 权限请求数据 */
  request: PermissionRequest
  /** 用户回复回调 */
  onReply: (requestId: string, reply: 'once' | 'always' | 'reject', message?: string) => void
  /** 关闭弹窗回调 */
  onClose: () => void
}

/** 获取操作的友好显示名称 */
function getActionLabel(action: string): string {
  if (!action) return '未知操作'
  const actionMap: Record<string, string> = {
    'read': '读取文件',
    'write': '写入文件',
    'edit': '编辑文件',
    'execute': '执行命令',
    'bash': '执行 Shell',
    'delete': '删除文件',
    'web_search': '网页搜索',
    'web_fetch': '获取网页',
    'notify': '发送通知',
    'glob': '搜索文件',
    'grep': '搜索内容',
  }
  return actionMap[action] || action
}

/** 获取资源的友好显示文本 */
function getResourceLabel(resources: string[]): string {
  if (!resources || resources.length === 0) return '未知资源'
  if (resources.length <= 3) return resources.join(', ')
  return `${resources.slice(0, 3).join(', ')} 等 ${resources.length} 项资源`
}

export function PermissionDialog({ request, onReply, onClose }: PermissionDialogProps) {
  const [rejectMessage, setRejectMessage] = useState('')
  const [showRejectInput, setShowRejectInput] = useState(false)
  const [processing, setProcessing] = useState(false)

  const handleAllow = async () => {
    setProcessing(true)
    try {
      await onReply(request.id, 'once')
    } catch (err) {
      appLogger.error({ event: 'permission_dialog_reply_failed', message: `onReply allow 失败: ${err instanceof Error ? err.message : String(err)}`, extra: err instanceof Error ? { stack: err.stack } : undefined })
    } finally {
      setProcessing(false)
    }
  }

  const handleAlwaysAllow = async () => {
    setProcessing(true)
    try {
      await onReply(request.id, 'always')
    } catch (err) {
      appLogger.error({ event: 'permission_dialog_reply_failed', message: `onReply always allow 失败: ${err instanceof Error ? err.message : String(err)}`, extra: err instanceof Error ? { stack: err.stack } : undefined })
    } finally {
      setProcessing(false)
    }
  }

  const handleReject = async () => {
    setProcessing(true)
    try {
      await onReply(request.id, 'reject', rejectMessage || undefined)
    } catch (err) {
      appLogger.error({ event: 'permission_dialog_reply_failed', message: `onReply reject 失败: ${err instanceof Error ? err.message : String(err)}`, extra: err instanceof Error ? { stack: err.stack } : undefined })
    } finally {
      setProcessing(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.dialog} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <h3 className={styles.title}>权限请求</h3>
          {request.agent && (
            <span className={styles.agentBadge}>{request.agent}</span>
          )}
        </div>

        <div className={styles.body}>
          <div className={styles.field}>
            <span className={styles.label}>操作</span>
            <span className={styles.value}>{getActionLabel(request.action)}</span>
          </div>
          <div className={styles.field}>
            <span className={styles.label}>资源</span>
            <span className={styles.value}>{getResourceLabel(request.resources)}</span>
          </div>
          {request.metadata && Object.keys(request.metadata).length > 0 && (
            <div className={styles.metadata}>
              {Object.entries(request.metadata).map(([key, value]) => (
                <div key={key} className={styles.metadataItem}>
                  <span className={styles.metadataKey}>{key}</span>
                  <span className={styles.metadataValue}>{String(value)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className={styles.actions}>
          <button
            className={`${styles.btn} ${styles.btnAllow}`}
            onClick={handleAllow}
            disabled={processing}
          >
            允许一次
          </button>
          <button
            className={`${styles.btn} ${styles.btnAlways}`}
            onClick={handleAlwaysAllow}
            disabled={processing}
          >
            始终允许
          </button>
          <button
            className={`${styles.btn} ${styles.btnDeny}`}
            onClick={() => setShowRejectInput(!showRejectInput)}
            disabled={processing}
          >
            拒绝
          </button>
        </div>

        {showRejectInput && (
          <div className={styles.rejectSection}>
            <textarea
              className={styles.rejectInput}
              value={rejectMessage}
              onChange={(e) => setRejectMessage(e.target.value)}
              placeholder="可选：输入拒绝原因或修正建议..."
              rows={2}
            />
            <button
              className={`${styles.btn} ${styles.btnRejectConfirm}`}
              onClick={handleReject}
              disabled={processing}
            >
              确认拒绝
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default PermissionDialog
