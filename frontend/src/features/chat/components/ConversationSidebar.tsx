import { useEffect, useMemo, useState } from 'react'
import { PanelLeft, Plus, Search, PencilLine, Trash2, RotateCcw } from 'lucide-react'
import type { ConversationSessionSummary } from '@/features/chat/types'
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
    return '暂无消息'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '时间未知'
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function ConversationSidebar(props: ConversationSidebarProps) {
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

  const startRename = (item: ConversationSessionSummary) => {
    setEditingSessionId(item.session_id)
    setEditingTitle(item.title)
  }

  const toggleSelected = (sessionId: string) => {
    setSelectedSessionIds((current) => current.includes(sessionId)
      ? current.filter((item) => item !== sessionId)
      : [...current, sessionId])
  }

  const submitRename = async () => {
    if (!editingSessionId || !editingTitle.trim()) {
      return
    }
    await onRenameConversation(editingSessionId, editingTitle.trim())
    setEditingSessionId(null)
    setEditingTitle('')
  }

  return (
    <aside className={`${styles['sidebar']} ${open ? '' : styles['closed']}`.trim()} aria-label="聊天历史侧边栏">
      <div className={styles['header']}>
        <span className={styles['title']}>历史对话</span>
        <div className={styles['headerActions']}>
          <button className={styles['iconButton']} type="button" onClick={onCreateConversation} title="新建对话">
            <Plus size={16} />
          </button>
          <button className={styles['iconButton']} type="button" onClick={onToggle} title={open ? '收起历史记录' : '展开历史记录'}>
            <PanelLeft size={16} />
          </button>
        </div>
      </div>

      <div className={styles['filters']}>
        <div className={styles['searchRow']}>
          <Search size={15} />
          <input
            className={styles['searchInput']}
            placeholder="搜索标题或摘要"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </div>
        <div className={styles['sortRow']}>
          <select className={styles['sortSelect']} value={sortBy} onChange={(event) => onSortChange(event.target.value as 'last_message_at' | 'title')}>
            <option value="last_message_at">按时间排序</option>
            <option value="title">按名称排序</option>
          </select>
        </div>
        <label className={styles['checkboxRow']}>
          <input type="checkbox" checked={includeDeleted} onChange={(event) => onIncludeDeletedChange(event.target.checked)} />
          <span>显示最近删除</span>
        </label>
        <div className={styles['batchActions']}>
          <label className={styles['checkboxRow']}>
            <input
              type="checkbox"
              checked={allSelected}
              disabled={selectableSessionIds.length === 0}
              onChange={() => setSelectedSessionIds(allSelected ? [] : selectableSessionIds)}
            />
            <span>全选当前列表</span>
          </label>
          <div className={styles['batchButtons']}>
            <button
              className={styles['secondaryButton']}
              type="button"
              onClick={() => setSelectedSessionIds([])}
              disabled={selectedSessionIds.length === 0}
            >
              清空选择
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
              批量删除 {selectedSessionIds.length > 0 ? `(${selectedSessionIds.length})` : ''}
            </button>
          </div>
        </div>
      </div>

      <div className={styles['content']}>
        {loading && !hasConversations && <div className={styles['loading']}>正在加载历史对话...</div>}
        {error && <div className={styles['error']}>{error}</div>}
        {!loading && !error && !hasConversations && <div className={styles['empty']}>暂无历史对话</div>}

        {renderedItems.map((item) => {
          const isActive = item.session_id === activeSessionId
          const isDeleted = Boolean(item.deleted_at)

          return (
            <div
              key={item.session_id}
              className={`${styles['item']} ${isActive ? styles['active'] : ''} ${isDeleted ? styles['deleted'] : ''}`.trim()}
              onClick={() => onSelectConversation(item.session_id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelectConversation(item.session_id)
                }
              }}
              role="button"
              tabIndex={0}
              aria-current={isActive ? 'page' : undefined}
            >
              {editingSessionId === item.session_id ? (
                <>
                  <input
                    className={styles['renameInput']}
                    aria-label="重命名对话标题"
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
                      保存
                    </button>
                    <button className={styles['secondaryButton']} type="button" onClick={(event) => {
                      event.stopPropagation()
                      setEditingSessionId(null)
                      setEditingTitle('')
                    }}>
                      取消
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <div className={styles['itemHeader']}>
                    <div className={styles['itemHeading']}>
                      {!isDeleted && (
                        <input
                          className={styles['itemCheckbox']}
                          type="checkbox"
                          checked={selectedSessionIds.includes(item.session_id)}
                          onChange={() => toggleSelected(item.session_id)}
                          onClick={(event) => event.stopPropagation()}
                        />
                      )}
                      <span className={styles['itemTitle']}>{item.title || '新对话'}</span>
                    </div>
                    <span className={styles['metaText']}>{formatTimestamp(item.last_message_at || item.updated_at)}</span>
                  </div>
                  <div className={styles['itemSummary']}>
                    {item.last_message_preview || item.summary || '暂无摘要'}
                  </div>
                  <div className={styles['itemMeta']}>
                    <span className={styles['metaText']}>{item.message_count} 条消息</span>
                    {isDeleted && <span className={styles['deletedText']}>已删除，可恢复</span>}
                  </div>
                  <div className={styles['itemActions']} onClick={(event) => event.stopPropagation()}>
                    {!isDeleted && (
                      <button
                        className={styles['actionButton']}
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation()
                          startRename(item)
                        }}
                        title="重命名对话"
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
                        title="恢复对话"
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
                        title="删除对话"
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          )
        })}
      </div>

      {hasMore && (
        <button className={styles['loadMore']} type="button" onClick={onLoadMore}>
          加载更多
        </button>
      )}
    </aside>
  )
}

export default ConversationSidebar
