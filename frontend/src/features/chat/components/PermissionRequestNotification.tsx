/**
 * 权限请求通知栏组件。
 * 在聊天区域顶部显示待处理的权限请求列表，
 * 每个请求显示操作类型、目标资源，以及允许/拒绝按钮。
 * 点击"详情"可展开完整的 PermissionDialog 弹窗。
 */
import { useState } from 'react'
import { ShieldAlert, ChevronDown, ChevronUp } from 'lucide-react'
import type { PermissionRequest } from '@/shared/api/securityApi'
import { PermissionDialog } from './PermissionDialog'
import styles from './PermissionRequestNotification.module.css'

interface PermissionRequestNotificationProps {
  /** 待处理的权限请求列表 */
  pendingRequests: PermissionRequest[]
  /** 批准权限请求（允许一次） */
  onApprove: (requestId: string) => Promise<void>
  /** 始终允许权限请求 */
  onApproveAlways: (requestId: string, rules?: string) => Promise<void>
  /** 拒绝权限请求 */
  onDeny: (requestId: string, reason?: string) => Promise<void>
}

/** 获取操作的友好显示名称 */
function getActionLabel(action: string): string {
  if (!action) return '未知操作'
  const actionMap: Record<string, string> = {
    'read': '读取',
    'write': '写入',
    'edit': '编辑',
    'execute': '执行命令',
    'bash': '执行 Shell',
    'delete': '删除',
    'web_search': '网页搜索',
    'web_fetch': '获取网页',
    'notify': '发送通知',
    'glob': '搜索文件',
    'grep': '搜索内容',
  }
  return actionMap[action] || action
}

/** 获取资源的友好显示文本（截断过长路径） */
function getResourceLabel(resources: string[]): string {
  if (!resources || resources.length === 0) return '未知资源'
  const first = resources[0]
  if (resources.length === 1) {
    return first.length > 60 ? first.slice(0, 57) + '...' : first
  }
  return `${first} 等 ${resources.length} 项`
}

export function PermissionRequestNotification({
  pendingRequests,
  onApprove,
  onApproveAlways,
  onDeny,
}: PermissionRequestNotificationProps) {
  const [expanded, setExpanded] = useState(true)
  const [dialogRequest, setDialogRequest] = useState<PermissionRequest | null>(null)
  const [processingIds, setProcessingIds] = useState<Set<string>>(new Set())

  if (pendingRequests.length === 0) {
    return null
  }

  const handleQuickApprove = async (requestId: string) => {
    setProcessingIds((prev) => new Set(prev).add(requestId))
    try {
      await onApprove(requestId)
    } finally {
      setProcessingIds((prev) => {
        const next = new Set(prev)
        next.delete(requestId)
        return next
      })
    }
  }

  const handleQuickDeny = async (requestId: string) => {
    setProcessingIds((prev) => new Set(prev).add(requestId))
    try {
      await onDeny(requestId)
    } finally {
      setProcessingIds((prev) => {
        const next = new Set(prev)
        next.delete(requestId)
        return next
      })
    }
  }

  const handleDialogReply = async (requestId: string, reply: 'once' | 'always' | 'reject', message?: string) => {
    if (reply === 'once') {
      await onApprove(requestId)
    } else if (reply === 'always') {
      await onApproveAlways(requestId, message)
    } else {
      await onDeny(requestId, message)
    }
    setDialogRequest(null)
  }

  return (
    <>
      <div className={styles.container}>
        <div
          className={styles.header}
          onClick={() => setExpanded(!expanded)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setExpanded(!expanded) }}
        >
          <div className={styles.headerLeft}>
            <ShieldAlert size={16} className={styles.icon} />
            <span className={styles.title}>
              权限请求 ({pendingRequests.length})
            </span>
          </div>
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>

        {expanded && (
          <div className={styles.list}>
            {pendingRequests.map((request) => {
              const isProcessing = processingIds.has(request.id)
              return (
                <div key={request.id} className={styles.item}>
                  <div className={styles.itemInfo}>
                    <span className={styles.actionBadge}>
                      {getActionLabel(request.action)}
                    </span>
                    <span className={styles.resourceText}>
                      {getResourceLabel(request.resources)}
                    </span>
                    <button
                      className={styles.detailBtn}
                      onClick={() => setDialogRequest(request)}
                      type="button"
                    >
                      详情
                    </button>
                  </div>
                  <div className={styles.itemActions}>
                    <button
                      className={`${styles.btn} ${styles.btnApprove}`}
                      onClick={() => void handleQuickApprove(request.id)}
                      disabled={isProcessing}
                      type="button"
                    >
                      允许
                    </button>
                    <button
                      className={`${styles.btn} ${styles.btnDeny}`}
                      onClick={() => void handleQuickDeny(request.id)}
                      disabled={isProcessing}
                      type="button"
                    >
                      拒绝
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {dialogRequest && (
        <PermissionDialog
          request={dialogRequest}
          onReply={handleDialogReply}
          onClose={() => setDialogRequest(null)}
        />
      )}
    </>
  )
}

export default PermissionRequestNotification
