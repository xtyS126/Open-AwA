import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import { PencilLine, RotateCcw, Search, Trash2 } from 'lucide-react'
import { Virtuoso } from 'react-virtuoso'
import type { ConversationSessionSummary } from '@/features/chat/types'
import { t as i18nT, useI18nStore } from '@/i18n'
import styles from './ConversationManager.module.css'

export interface ConversationManagerProps {
  loading: boolean
  error: string | null
  conversations: ConversationSessionSummary[]
  activeSessionId: string
  search: string
  sortBy: 'last_message_at' | 'title'
  includeDeleted: boolean
  hasMore: boolean
  onSearchChange: (value: string) => void
  onSortChange: (value: 'last_message_at' | 'title') => void
  onIncludeDeletedChange: (value: boolean) => void
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

function ConversationManager({
  loading,
  error,
  conversations,
  activeSessionId,
  search,
  sortBy,
  includeDeleted,
  hasMore,
  onSearchChange,
  onSortChange,
  onIncludeDeletedChange,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
  onBatchDeleteConversations,
  onRestoreConversation,
  onLoadMore,
}: ConversationManagerProps) {
  const t = useI18nStore((state) => state.t)
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [selectedSessionIds, setSelectedSessionIds] = useState<string[]>([])

  useEffect(() => {
    setSelectedSessionIds((current) => current.filter(
      (sessionId) => conversations.some((conversation) => conversation.session_id === sessionId && !conversation.deleted_at),
    ))
  }, [conversations])

  const renderedItems = useMemo(() => conversations, [conversations])
  const selectableSessionIds = useMemo(
    () => renderedItems.filter((conversation) => !conversation.deleted_at).map((conversation) => conversation.session_id),
    [renderedItems],
  )
  const allSelected = selectableSessionIds.length > 0
    && selectableSessionIds.every((sessionId) => selectedSessionIds.includes(sessionId))

  const startRename = useCallback((conversation: ConversationSessionSummary) => {
    setEditingSessionId(conversation.session_id)
    setEditingTitle(conversation.title)
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

  const renderConversationItem = useCallback((_index: number, conversation: ConversationSessionSummary) => {
    const isActive = conversation.session_id === activeSessionId
    const isDeleted = Boolean(conversation.deleted_at)

    return (
      <div className={`${styles.item} ${isActive ? styles.active : ''} ${isDeleted ? styles.deleted : ''}`.trim()}>
        {editingSessionId === conversation.session_id ? (
          <>
            <input
              className={styles.renameInput}
              aria-label={t('chat.history.rename')}
              value={editingTitle}
              onChange={(event) => setEditingTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  void submitRename()
                }
              }}
            />
            <div className={styles.renameActions}>
              <button className={styles.primaryButton} type="button" onClick={() => void submitRename()}>
                {t('app.save')}
              </button>
              <button className={styles.secondaryButton} type="button" onClick={() => {
                setEditingSessionId(null)
                setEditingTitle('')
              }}>
                {t('app.cancel')}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className={styles.itemMain}>
              {!isDeleted && (
                <input
                  className={styles.itemCheckbox}
                  type="checkbox"
                  checked={selectedSessionIds.includes(conversation.session_id)}
                  onChange={() => toggleSelected(conversation.session_id)}
                  aria-label={t('chat.history.selectSession', { title: conversation.title || t('chat.newChat') })}
                />
              )}
              <button
                className={styles.itemSelectButton}
                type="button"
                onClick={() => onSelectConversation(conversation.session_id)}
                aria-current={isActive ? 'page' : undefined}
                aria-label={conversation.title || t('chat.newChat')}
              >
                <span className={styles.itemHeader}>
                  <span className={styles.itemTitle}>{conversation.title || t('chat.newChat')}</span>
                  <span className={styles.metaText}>{formatTimestamp(conversation.last_message_at || conversation.updated_at)}</span>
                </span>
                <span className={styles.itemSummary}>
                  {conversation.last_message_preview || conversation.summary || t('chat.history.noSummary')}
                </span>
                <span className={styles.itemMeta}>
                  <span className={styles.metaText}>{t('chat.history.messageCount', { count: String(conversation.message_count) })}</span>
                  {isDeleted && <span className={styles.deletedText}>{t('chat.history.deleted')}</span>}
                </span>
              </button>
            </div>
            <div className={styles.itemActions}>
              {!isDeleted && (
                <button className={styles.actionButton} type="button" onClick={() => startRename(conversation)} aria-label={t('chat.history.renameAction')}>
                  <PencilLine size={15} />
                </button>
              )}
              {isDeleted ? (
                <button className={styles.actionButton} type="button" onClick={() => onRestoreConversation(conversation.session_id)} aria-label={t('chat.history.restore')}>
                  <RotateCcw size={15} />
                </button>
              ) : (
                <button className={styles.actionButton} type="button" onClick={() => onDeleteConversation(conversation.session_id)} aria-label={t('chat.history.deleteAction')}>
                  <Trash2 size={15} />
                </button>
              )}
            </div>
          </>
        )}
      </div>
    )
  }, [activeSessionId, editingSessionId, editingTitle, onDeleteConversation, onRestoreConversation, onSelectConversation, selectedSessionIds, startRename, submitRename, t, toggleSelected])

  const hasConversations = conversations.length > 0

  return (
    <div className={styles.manager}>
      <div className={styles.filters}>
        <div className={styles.searchRow}>
          <Search size={15} aria-hidden="true" />
          <input
            className={styles.searchInput}
            placeholder={t('chat.history.searchPlaceholder')}
            aria-label={t('chat.history.searchPlaceholder')}
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </div>
        <div className={styles.sortRow}>
          <select className={styles.sortSelect} value={sortBy} onChange={(event) => onSortChange(event.target.value as 'last_message_at' | 'title')} aria-label={t('chat.history.sortByTime')}>
            <option value="last_message_at">{t('chat.history.sortByTime')}</option>
            <option value="title">{t('chat.history.sortByName')}</option>
          </select>
        </div>
        <label className={styles.checkboxRow}>
          <input type="checkbox" checked={includeDeleted} onChange={(event) => onIncludeDeletedChange(event.target.checked)} />
          <span>{t('chat.history.showDeleted')}</span>
        </label>
        <div className={styles.batchActions}>
          <label className={styles.checkboxRow}>
            <input
              type="checkbox"
              checked={allSelected}
              disabled={selectableSessionIds.length === 0}
              onChange={() => setSelectedSessionIds(allSelected ? [] : selectableSessionIds)}
            />
            <span>{t('chat.history.selectAll')}</span>
          </label>
          <div className={styles.batchButtons}>
            <button className={styles.secondaryButton} type="button" onClick={() => setSelectedSessionIds([])} disabled={selectedSessionIds.length === 0}>
              {t('chat.history.clearSelection')}
            </button>
            <button
              className={styles.dangerButton}
              type="button"
              onClick={() => onBatchDeleteConversations(selectedSessionIds)}
              disabled={selectedSessionIds.length === 0}
            >
              {t('chat.history.batchDelete')} {selectedSessionIds.length > 0 ? `(${selectedSessionIds.length})` : ''}
            </button>
          </div>
        </div>
      </div>

      <div className={styles.content}>
        {loading && !hasConversations && <div className={styles.loading}>{t('chat.history.loading')}</div>}
        {error && <div className={styles.error}>{error}</div>}
        {!loading && !error && !hasConversations && <div className={styles.empty}>{t('chat.history.empty')}</div>}
        {hasConversations && (
          <Virtuoso
            data={renderedItems}
            itemContent={renderConversationItem}
            endReached={hasMore ? onLoadMore : undefined}
            style={{ height: '100%' }}
          />
        )}
      </div>
    </div>
  )
}

export default memo(ConversationManager)
