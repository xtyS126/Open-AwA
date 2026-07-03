/**
 * 通知列表组件。
 * 展示通知项的标题、正文、时间与类型颜色标识。
 */
import { useI18nStore } from '@/i18n'
import type { NotificationItem } from '@/shared/api/notificationsApi'

export interface NotificationListProps {
  /** 通知列表 */
  notifications: NotificationItem[]
}

/** 根据通知类型推断颜色标识，便于视觉区分 */
function getTypeColor(notificationType?: string): string {
  switch (notificationType) {
    case 'error':
    case 'danger':
      return 'var(--color-error)'
    case 'warning':
      return 'var(--color-warning)'
    case 'success':
      return 'var(--color-success)'
    case 'info':
    default:
      return 'var(--color-info)'
  }
}

/** 将 ISO 时间字符串格式化为 HH:MM 简短展示 */
function formatTime(iso: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

/** 通知列表 —— 每项左侧颜色条标识类型，右侧显示时间 */
export default function NotificationList({ notifications }: NotificationListProps) {
  const { t } = useI18nStore()

  if (notifications.length === 0) {
    return (
      <div
        style={{
          padding: '12px',
          fontSize: 'var(--text-sm)',
          color: 'var(--color-text-tertiary)',
          textAlign: 'center',
        }}
      >
        {t('app.noData')}
      </div>
    )
  }

  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {notifications.map((notification) => {
        const color = getTypeColor(notification.notification_type)
        return (
          <li
            key={notification.id}
            style={{
              display: 'flex',
              gap: '8px',
              padding: '8px 10px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border-subtle)',
            }}
          >
            {/* 类型颜色条 */}
            <span
              aria-hidden="true"
              style={{
                width: '3px',
                flexShrink: 0,
                borderRadius: '2px',
                background: color,
              }}
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0, flex: 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                <span
                  style={{
                    fontSize: 'var(--text-sm)',
                    fontWeight: 500,
                    color: 'var(--color-text)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {notification.title}
                </span>
                <span
                  style={{
                    fontSize: 'var(--text-xs)',
                    color: 'var(--color-text-tertiary)',
                    flexShrink: 0,
                  }}
                >
                  {formatTime(notification.created_at)}
                </span>
              </div>
              {notification.body && (
                <span
                  style={{
                    fontSize: 'var(--text-xs)',
                    color: 'var(--color-text-secondary)',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {notification.body}
                </span>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
