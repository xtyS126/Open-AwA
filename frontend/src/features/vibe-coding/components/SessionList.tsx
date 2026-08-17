/**
 * ACP 会话列表组件。
 * 只展示服务端返回的安全会话字段，不接收或推导项目根路径。
 */
import { X } from 'lucide-react'
import { useI18nStore } from '@/i18n'
import type { AcpSession } from '@/shared/api/acpApi'

export interface SessionListProps {
  sessions: AcpSession[]
  selectedId: string | null
  onSelect: (id: string) => void
  onClose: (id: string) => void
}

function formatCreatedAt(value: string): string {
  const timestamp = Date.parse(value)
  if (Number.isNaN(timestamp)) return value
  return new Date(timestamp).toLocaleString()
}

export default function SessionList({ sessions, selectedId, onSelect, onClose }: SessionListProps) {
  const { t } = useI18nStore()

  if (sessions.length === 0) {
    return (
      <div
        style={{
          padding: '12px',
          fontSize: 'var(--text-sm)',
          color: 'var(--color-text-tertiary)',
          textAlign: 'center',
        }}
      >
        {t('vibeCoding.noSessions')}
      </div>
    )
  }

  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '4px' }}>
      {sessions.map((session) => {
        const isActive = session.session_id === selectedId
        return (
          <li
            key={session.session_id}
            onClick={() => onSelect(session.session_id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 10px',
              borderRadius: 'var(--radius-md)',
              cursor: 'pointer',
              background: isActive ? 'var(--color-primary-soft-bg)' : 'transparent',
              color: isActive ? 'var(--color-primary)' : 'var(--color-text)',
              border: '1px solid',
              borderColor: isActive ? 'var(--color-primary)' : 'transparent',
              fontSize: 'var(--text-sm)',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0, flex: 1 }}>
              <span style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {session.agent}
              </span>
              <span
                title={session.session_id}
                style={{
                  fontSize: 'var(--text-xs)',
                  color: 'var(--color-text-tertiary)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {session.session_id}
              </span>
              <time
                dateTime={session.created_at}
                style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)' }}
              >
                {formatCreatedAt(session.created_at)}
              </time>
            </div>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onClose(session.session_id)
              }}
              title={t('app.close')}
              aria-label={t('app.close')}
              style={{
                border: 'none',
                background: 'transparent',
                cursor: 'pointer',
                color: 'var(--color-text-tertiary)',
                padding: '4px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <X size={14} />
            </button>
          </li>
        )
      })}
    </ul>
  )
}
