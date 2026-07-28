/**
 * ACP 会话列表组件。
 * 展示活动会话，支持选中切换与关闭。
 */
import { X } from 'lucide-react'
import { useI18nStore } from '@/i18n'
import type { AcpSession } from '@/shared/api/acpApi'

export interface SessionListProps {
  /** 会话列表 */
  sessions: AcpSession[]
  /** 当前选中的会话 ID */
  selectedId: string | null
  /** 选中会话回调 */
  onSelect: (id: string) => void
  /** 关闭会话回调 */
  onClose: (id: string) => void
}

/** 从绝对路径中提取末尾两级，用于列表项简短展示 */
function shortPath(cwd: string): string {
  if (!cwd) return ''
  const parts = cwd.replace(/\\/g, '/').split('/').filter(Boolean)
  if (parts.length <= 2) return cwd
  return '.../' + parts.slice(-2).join('/')
}

/** 会话列表 —— 每项显示 agent 标识与简短工作目录，并提供关闭按钮 */
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
                title={session.cwd}
                style={{
                  fontSize: 'var(--text-xs)',
                  color: 'var(--color-text-tertiary)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {shortPath(session.cwd)}
              </span>
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
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
