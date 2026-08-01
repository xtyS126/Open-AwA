import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import { Virtuoso } from 'react-virtuoso'
import { PanelLeft, Plus, Search, PencilLine, Trash2, RotateCcw } from 'lucide-react'
import type { ConversationSessionSummary } from '@/features/chat/types'
import { useI18nStore, t as i18nT } from '@/i18n'
import styles from './ConversationSidebar.module.css'

interface ConversationSidebarProps {
  open: boolean
  loading: boolean
  error: string | null
  conversations: ConversationSessionSummary[]
  activeSessionId: string
  search: string
  sortBy: 'last_message_at' | 'title'
  includeDeleted: boolean
  hasMore: boolean
  onToggle: () => void
  onSearchChange: (value: string) => void
  onSortChange: (value: 'last_message_at' | 'title') => void
  onIncludeDeletedChange: (value: boolean) => void
  onCreateConversation: () => void
  onSelectConversation: (sessionId: string) => void
  onRenameConversation: (sessionId: string, title: string) => Promise<void> | void
  onDeleteConversation: (sessionId: string) => Promise<void> | void
  onBatchDeleteConversations: (sessionIds: string[]) => Promise<void> | void
  onRestoreConversation: (sessionId: string) => Promise<void> | void
  onLoadMore: () => void
}

function formatTimestamp(value?: string | null): string {
  if (!value) {
    return i18nT('chat.history.noMessages')
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return i18nT('chat.history.unknownTime')
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function ConversationSidebar(props: ConversationSidebarProps) {
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const t = useI18nStore(s => s.t)
  const {
    open,
    loading,
    error,
    conversations,
    activeSessionId,
    search,
    sortBy,
    includeDeleted,
    hasMore,
    onToggle,
    onSearchChange,
    onSortChange,
    onIncludeDeletedChange,
    onCreateConversation,
    onSelectConversation,
    onRenameConversation,
    onDeleteConversation,
    onBatchDeleteConversations,
    onRestoreConversation,
    onLoadMore,
  } = props
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [selectedSessionIds, setSelectedSessionIds] = useState<string[]>([])

  useEffect(() => {
    if (!open) {
      setEditingSessionId(null)
      setEditingTitle('')
      setSelectedSessionIds([])
    }
  }, [open])

  useEffect(() => {
    setSelectedSessionIds((current) => current.filter((sessionId) => conversations.some((item) => item.session_id === sessionId && !item.deleted_at)))
  }, [conversations])

  const hasConversations = conversations.length > 0
  const renderedItems = useMemo(() => conversations, [conversations])
  const selectableSessionIds = useMemo(
    () => renderedItems.filter((item) => !item.deleted_at).map((item) => item.session_id),
    [renderedItems]
  )
  const allSelected = selectableSessionIds.length > 0 && selectableSessionIds.every((sessionId) => selectedSessionIds.includes(sessionId))

  const startRename = useCallback((item: ConversationSessionSummary) => {
    setEditingSessionId(item.session_id)
    setEditingTitle(item.title)
  }, [])

  const toggleSelected = useCallback((sessionId: string) => {
    setSelectedSessionIds((current) => current.includes(sessionId)
      ? current.filter((item) => item !== sessionId)
      : [...current, sessionId])
  }, [])

  const submitRename = useCallback(async () => {
    if (!editingSessionId || !editingTitle.trim()) {
      return
    }
    await onRenameConversation(editingSessionId, editingTitle.trim())
    setEditingSessionId(null)
    setEditingTitle('')
  }, [editingSessionId, editingTitle, onRenameConversation])

  // Virtuoso 虚拟滚动渲染回调 — 仅渲染可视区域内的会话项
  const renderConversationItem = useCallback((_index: number, item: ConversationSessionSummary) => {
    const isActive = item.session_id === activeSessionId
    const isDeleted = Boolean(item.deleted_at)

    return (
      <div
        className={`${styles['item']} ${isActive ? styles['active'] : ''} ${isDeleted ? styles['deleted'] : ''}`.trim()}
      >
        {editingSessionId === item.session_id ? (
          <>
            <input
              className={styles['renameInput']}
              aria-label={t('chat.history.rename')}
              value={editingTitle}
              onChange={(event) => setEditingTitle(event.target.value)}
              onClick={(event) => event.stopPropagation()}
              onKeyDown={async (event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  await submitRename()
                }
              }}
            />
            <div className={styles['renameActions']}>
              <button className={styles['primaryButton']} type="button" onClick={(event) => {
                event.stopPropagation()
                void submitRename()
              }}>
                {t('app.save')}
              </button>
              <button className={styles['secondaryButton']} type="button" onClick={(event) => {
                event.stopPropagation()
                setEditingSessionId(null)
                setEditingTitle('')
              }}>
                {t('app.cancel')}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className={styles['itemMain']}>
              {!isDeleted && (
                <input
                  className={styles['itemCheckbox']}
                  type="checkbox"
                  checked={selectedSessionIds.includes(item.session_id)}
                  onChange={() => toggleSelected(item.session_id)}
                  aria-label={t('chat.history.selectSession', { title: item.title || t('chat.newChat') })}
                />
              )}
              <button
                className={styles['itemSelectButton']}
                type="button"
                onClick={() => onSelectConversation(item.session_id)}
                aria-current={isActive ? 'page' : undefined}
                aria-label={item.title || t('chat.newChat')}
              >
                <span className={styles['itemHeader']}>
                  <span className={styles['itemTitle']}>{item.title || t('chat.newChat')}</span>
                  <span className={styles['metaText']}>{formatTimestamp(item.last_message_at || item.updated_at)}</span>
                </span>
                <span className={styles['itemSummary']}>
                  {item.last_message_preview || item.summary || t('chat.history.noSummary')}
                </span>
                <span className={styles['itemMeta']}>
                  <span className={styles['metaText']}>{t('chat.history.messageCount', { count: String(item.message_count) })}</span>
                  {isDeleted && <span className={styles['deletedText']}>{t('chat.history.deleted')}</span>}
                </span>
              </button>
            </div>
            <div className={styles['itemActions']}>
              {!isDeleted && (
                <button
                  className={styles['actionButton']}
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    startRename(item)
                  }}
                  title={t('chat.history.renameAction')}
                  aria-label={t('chat.history.renameAction')}
                >
                  <PencilLine size={15} />
                </button>
              )}
              {isDeleted ? (
                <button
                  className={styles['actionButton']}
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    onRestoreConversation(item.session_id)
                  }}
                  title={t('chat.history.restore')}
                  aria-label={t('chat.history.restore')}
                >
                  <RotateCcw size={15} />
                </button>
              ) : (
                <button
                  className={styles['actionButton']}
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    onDeleteConversation(item.session_id)
                  }}
                  title={t('chat.history.deleteAction')}
                  aria-label={t('chat.history.deleteAction')}
                >
                  <Trash2 size={15} />
                </button>
              )}
            </div>
          </>
        )}
      </div>
    )
  // startRename/toggleSelected/t 为稳定引用（useCallback/Zustand），无需额外重建
  }, [activeSessionId, editingSessionId, editingTitle, selectedSessionIds, submitRename, startRename, toggleSelected, t, onSelectConversation, onRestoreConversation, onDeleteConversation])

  return (
    <aside className={`${styles['sidebar']} ${open ? '' : styles['closed']}`.trim()} aria-label="聊天历史侧边栏">
      <div className={styles['header']}>
        <span className={styles['title']}>{t('chat.history.title')}</span>
        <div className={styles['headerActions']}>
          <button className={styles['iconButton']} type="button" onClick={onCreateConversation} title={t('chat.history.newChat')} aria-label={t('chat.history.newChat')}>
            <Plus size={16} />
          </button>
          <button className={styles['iconButton']} type="button" onClick={onToggle} title={open ? t('chat.collapseHistory') : t('chat.expandHistory')} aria-label={open ? t('chat.collapseHistory') : t('chat.expandHistory')}>
            <PanelLeft size={16} />
          </button>
        </div>
      </div>

      <div className={styles['filters']}>
        <div className={styles['searchRow']}>
          <Search size={15} aria-hidden="true" />
          <input
            className={styles['searchInput']}
            placeholder={t('chat.history.searchPlaceholder')}
            aria-label={t('chat.history.searchPlaceholder')}
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </div>
        <div className={styles['sortRow']}>
          <select
            className={styles['sortSelect']}
            value={sortBy}
            onChange={(event) => onSortChange(event.target.value as 'last_message_at' | 'title')}
            aria-label={t('chat.history.sortByTime')}
          >
            <option value="last_message_at">{t('chat.history.sortByTime')}</option>
            <option value="title">{t('chat.history.sortByName')}</option>
          </select>
        </div>
        <label className={styles['checkboxRow']}>
          <input type="checkbox" checked={includeDeleted} onChange={(event) => onIncludeDeletedChange(event.target.checked)} />
          <span>{t('chat.history.showDeleted')}</span>
        </label>
        <div className={styles['batchActions']}>
          <label className={styles['checkboxRow']}>
            <input
              type="checkbox"
              checked={allSelected}
              disabled={selectableSessionIds.length === 0}
              onChange={() => setSelectedSessionIds(allSelected ? [] : selectableSessionIds)}
            />
            <span>{t('chat.history.selectAll')}</span>
          </label>
          <div className={styles['batchButtons']}>
            <button
              className={styles['secondaryButton']}
              type="button"
              onClick={() => setSelectedSessionIds([])}
              disabled={selectedSessionIds.length === 0}
            >
              {t('chat.history.clearSelection')}
            </button>
            <button
              className={styles['dangerButton']}
              type="button"
              onClick={async () => {
                await onBatchDeleteConversations(selectedSessionIds)
                setSelectedSessionIds([])
              }}
              disabled={selectedSessionIds.length === 0}
            >
              {t('chat.history.batchDelete')} {selectedSessionIds.length > 0 ? `(${selectedSessionIds.length})` : ''}
            </button>
          </div>
        </div>
      </div>

      <div className={styles['content']}>
        {loading && !hasConversations && <div className={styles['loading']}>{t('chat.history.loading')}</div>}
        {error && <div className={styles['error']}>{error}</div>}
        {!loading && !error && !hasConversations && <div className={styles['empty']}>{t('chat.history.empty')}</div>}

        {hasConversations && (
          <Virtuoso
            data={renderedItems}
            itemContent={renderConversationItem}
            endReached={hasMore ? onLoadMore : undefined}
            style={{ height: '100%' }}
          />
        )}
      </div>
    </aside>
  )
}

export default memo(ConversationSidebar)
